"""`CachePlanner` — zones de contexte, hashes, drift detection, `PrefillPlan`.

Modele des zones (corrige le 2026-10-31) :

    HEAD — IMMUABLE
      A1 system head        (client — observe, non controle)
      A2 regles projet      (OSIRIS)
    ZONE B — SEMI-STABLE
      B1 objectif / B2 plan global / B3 tool contract (client — non controle)
    ZONE A — TAIL APPEND-ONLY
      A3 contraintes        (OSIRIS, append-only)
      A4 decisions epinglees(OSIRIS, append-only)
    === CACHE BREAKPOINT ===
    ZONE C — WORKING SET  (refs, plan actif, etat courant)   -> prunable gratuitement
    ZONE D — VOLATILE TAIL (derniers tours, input, resultats frais)

Trois hashes, parce que le prefix cache est un *prefixe* :

  head_hash   = sha256(A1 + A2)              immuable : ne doit JAMAIS bouger
  zoneB_hash  = sha256(B1 + B2 + B3)         quasi-stable
  tail_hash   = sha256(A3 + A4)              append-only : croît normalement
  prefix_hash = sha256(head_hash + zoneB_hash)   <-- ce qui est reellement cache
  zoneA_hash  = sha256(head_hash + tail_hash)    <-- ZONE A complete

Deux corrections par rapport au modele initial :

1. **Les contraintes sont dans la queue append-only, pas dans le head.**
   Elles sont declarees append-only depuis le debut, mais leur contenu etait
   hache dans `head_hash` : ajouter une contrainte — geste courant — changeait
   `head_hash` et declenchait un DRIFT CRITIQUE alors que le prefixe cache etait
   intact. Le signal de derive criait au loup en permanence. Desormais un
   ajout est un APPEND ; seule la **reecriture** d'une contrainte ou d'une
   decision est une rupture semantique.

2. **Reecrire un element epingle est detecte explicitement.**
   `tail_hash` ne dit pas *ce qui* a change. Le drift compare donc les
   elements epingles eux-memes : un element retire ou remplace = rupture
   semantique critique (`cause = pinned_rewrite`), meme si le prefixe cache
   reste intact. C'est l'invariant n°2 d'AGENTS.md, enfinimplemente en place.

Consequence : **ajouter** une decision change `tail_hash` et `zoneA_hash`,
mais PAS `prefix_hash` : le cache tient, seul le delta est re-prefill.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from osiris.core.ids import canonical_json, sha256_hex
from osiris.core.tokens import count_tokens

#: Motifs de contenu dynamique qui cassent le prefix cache.
VOLATILE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("timestamp_iso", re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?\b")),
    (
        "uuid",
        re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
    ),
    ("epoch", re.compile(r"\b1[6-9]\d{8}\b")),
    ("date_slash", re.compile(r"\b\d{2}/\d{2}/\d{4}\b")),
    (
        "dynamic_field",
        re.compile(
            r"(?i)\b(session[_-]?id|request[_-]?id|trace[_-]?id|timestamp|current_time|"
            r"now|random[_-]?seed|nonce)\b\s*[:=]"
        ),
    ),
    ("build_id", re.compile(r"(?i)\bbuild[_-]?(id|number|hash)\b\s*[:=]\s*\S+")),
)

#: Verdicts de drift.
DRIFT_NONE = "none"
DRIFT_MINOR = "minor"
DRIFT_CRITICAL = "critical"
DRIFT_APPEND = "append"

#: Causes de rupture, distinguees du verdict.
CAUSE_HEAD = "head_changed"
CAUSE_PINNED = "pinned_rewrite"
CAUSE_ZONEB = "zoneB_changed"
CAUSE_APPEND = "pinned_appended"


def scan_volatile(text: str) -> list[str]:
    """Detecte les motifs dynamiques dans un texte."""
    found: list[str] = []
    for name, pattern in VOLATILE_PATTERNS:
        if pattern.search(text or ""):
            found.append(name)
    return found


def pinned_snapshot(constraints: list[str], decisions: list[str]) -> str:
    """Serialise les elements epingles (contraintes + decisions).

    Ce snapshot est stocke avec les hashes : il permet de distinguer un
    APPEND (ajout) d'une REECRITURE (retrait/remplacement) d'un element epingle.
    """
    return canonical_json(
        {"constraints": list(constraints or []), "decisions": list(decisions or [])}
    )


def load_pinned(raw: str | None) -> dict[str, list[str]]:
    """Deserialise un snapshot d'elements epingles."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "constraints": [str(x) for x in (data.get("constraints") or [])],
        "decisions": [str(x) for x in (data.get("decisions") or [])],
    }


#: Alias interne conserve pour compatibilite.
_load_pinned = load_pinned


def rewritten_pins(
    previous_pinned: dict[str, list[str]] | None,
    current_pinned: dict[str, list[str]] | None,
) -> list[str]:
    """Elements epingles retires ou remplaces (donc reecrits).

    Un ajout n'apparait pas ici : seule la **disparition** d'un element
    epingle compte comme reecriture.
    """
    if not previous_pinned or not current_pinned:
        return []
    broken: list[str] = []
    for key in ("constraints", "decisions"):
        prev = previous_pinned.get(key) or []
        cur = set(current_pinned.get(key) or [])
        for item in prev:
            if item not in cur:
                broken.append(f"{key}:{item[:60]}")
    return broken


def compute_zones(
    objective: str,
    constraints: list[str],
    decisions: list[str],
    plan_global: list[str],
    project_rules_digest: str,
    client_system_hash: str = "",
    client_contract_hash: str = "",
) -> dict[str, str]:
    """Calcule les hashes de zones a partir de leur contenu canonique."""
    a1 = client_system_hash or "client:unknown"
    a2 = project_rules_digest
    a3 = canonical_json(list(constraints))
    a4 = canonical_json(list(decisions))
    b1 = objective
    b2 = canonical_json(list(plan_global))
    b3 = client_contract_hash or "client:unknown"

    head_hash = sha256_hex(f"{a1}|{a2}")
    zoneB_hash = sha256_hex(f"{b1}|{b2}|{b3}")
    tail_hash = sha256_hex(f"{a3}|{a4}")
    prefix_hash = sha256_hex(f"{head_hash}|{zoneB_hash}")
    zoneA_hash = sha256_hex(f"{head_hash}|{tail_hash}")
    return {
        "head_hash": head_hash,
        "zoneB_hash": zoneB_hash,
        "tail_hash": tail_hash,
        "prefix_hash": prefix_hash,
        "zoneA_hash": zoneA_hash,
    }


def detect_drift(
    previous: dict[str, str],
    current: dict[str, str],
    previous_pinned: dict[str, list[str]] | None = None,
    current_pinned: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Compare deux jeux de hashes et qualifie la derive.

    - `head_hash` change   -> CRITICAL : le cache est mort, rollback possible.
    - element epingle reecrit -> CRITICAL semantique : le prefixe cache est
      intact mais l'etat de la tache a change de sens.
    - `zoneB_hash` change  -> MINOR    : le plan ou le contract ont bouge.
    - ajout d'un element epingle -> APPEND (cache preserve).
    """
    prev = previous or {}
    cur = current or {}
    verdict = DRIFT_NONE
    cause = ""
    changed: list[str] = []

    head_changed = bool(
        prev.get("head_hash") and cur.get("head_hash") and prev["head_hash"] != cur["head_hash"]
    )
    zoneB_changed = bool(
        prev.get("zoneB_hash")
        and cur.get("zoneB_hash")
        and prev["zoneB_hash"] != cur["zoneB_hash"]
    )
    tail_changed = bool(
        prev.get("tail_hash") and cur.get("tail_hash") and prev["tail_hash"] != cur["tail_hash"]
    )
    broken = rewritten_pins(previous_pinned, current_pinned)

    if head_changed:
        verdict = DRIFT_CRITICAL
        cause = CAUSE_HEAD
        changed.append("head")
    elif broken:
        verdict = DRIFT_CRITICAL
        cause = CAUSE_PINNED
        changed.append("pinned")
    elif zoneB_changed:
        verdict = DRIFT_MINOR
        cause = CAUSE_ZONEB
        changed.append("zoneB")
    elif tail_changed:
        verdict = DRIFT_APPEND
        cause = CAUSE_APPEND
        changed.append("tail")

    # Le prefixe cache n'est reellement invalide que si le head a bouge.
    cache_broken = head_changed
    return {
        "verdict": verdict,
        "cause": cause,
        "changed": changed,
        "rewritten": broken,
        "cache_broken": cache_broken,
        "semantic_break": bool(broken),
        "cache_hit_estimate": 0.0 if cache_broken else (0.9 if zoneB_changed else 1.0),
        "action": (
            "restore_head_and_alert"
            if cache_broken
            else "alert_pinned_rewrite"
            if broken
            else "rebuild_zoneB"
            if zoneB_changed
            else "none"
        ),
    }


def cache_mort_probability(elapsed_s: float, ttl_s: float) -> float:
    """Probabilite que le prefix cache soit expire.

    Modele **deterministe** : un prefixe cache survit `ttl_s`, au-dela il est
    mort. La probabilite est donc un seuil, pas une rampe :

    - `elapsed < ttl`  -> cache vivant, P(mort) = 0
    - `elapsed >= ttl` -> cache mort,  P(mort) = 1

    (Avant correction : `elapsed / ttl`. Cette rampe lineaire inventait une
    mortalite de 50 % a mi-TTL et, pire, `mode_allows_prefix` autorisait le
    prune du prefixe des 0.9*TTL — donc la destruction d'un cache encore
    chaud. La rampe etait aussi utilisee pour penaliser le gain alors que le
    prune de la zone de travail ne coute rien quand le cache est vivant.)
    """
    if ttl_s <= 0:
        return 1.0
    if elapsed_s <= 0:
        return 0.0
    return 0.0 if elapsed_s < ttl_s else 1.0


def build_prefill_plan(
    zones: dict[str, str],
    stable_tokens: int,
    volatile_tokens: int,
    warnings: list[str] | None = None,
    risk: str = "low",
) -> dict[str, Any]:
    """Construit le `PrefillPlan` (format de la spec)."""
    cached = stable_tokens
    fresh = volatile_tokens
    return {
        "prefix_hash": zones.get("prefix_hash", ""),
        "stable_blocks": [
            "system_head",
            "project_rules",
            "objective",
            "plan_global",
            "tool_contract",
        ],
        "cache_breakpoints": ["after_zoneB"],
        "volatile_tail": ["constraints", "pinned_decisions", "refs", "active_plan", "recent_turns"],
        "estimated_cached_tokens": cached,
        "estimated_fresh_tokens": fresh,
        "risk": risk,
        "warnings": list(warnings or []),
        "head_hash": zones.get("head_hash", ""),
        "zoneB_hash": zones.get("zoneB_hash", ""),
        "tail_hash": zones.get("tail_hash", ""),
        "zoneA_hash": zones.get("zoneA_hash", ""),
    }


def analyze_prefix(
    objective: str,
    constraints: list[str],
    decisions: list[str],
    plan_global: list[str],
    project_rules_digest: str,
    client_contract_hash: str = "",
    client_system_hash: str = "",
    previous: dict[str, str] | None = None,
    previous_pinned: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Point d'entree principal : calcule zones, drift et plan de prefill."""
    zones = compute_zones(
        objective=objective,
        constraints=constraints,
        decisions=decisions,
        plan_global=plan_global,
        project_rules_digest=project_rules_digest,
        client_system_hash=client_system_hash,
        client_contract_hash=client_contract_hash,
    )
    current_pinned = {"constraints": list(constraints), "decisions": list(decisions)}
    drift = detect_drift(previous or {}, zones, previous_pinned, current_pinned)

    # Ce qui est reellement cache = head + zoneB (system head, regles,
    # objectif, plan, contrat). Les elements epingles sont dans la queue :
    # ils ne sont PAS dans le prefixe cache.
    stable_text = canonical_json(
        [project_rules_digest, objective, list(plan_global), client_contract_hash]
    )
    stable_tokens = count_tokens(stable_text)
    volatile_tokens = count_tokens(
        canonical_json([list(constraints), list(decisions)])
    )

    warnings: list[str] = []
    if drift["cache_broken"]:
        warnings.append("head_changed: le prefix cache est invalide, il faut restaurer le head")
    if drift["semantic_break"]:
        warnings.append(
            "pinned_rewrite: un element epingle a ete reecrit ("
            + "; ".join(drift["rewritten"][:3])
            + ") — l'etat de la tache a change de sens"
        )
    if drift["verdict"] == DRIFT_MINOR:
        warnings.append("zoneB_changed: re-prefill partiel du prefixe, impact faible")
    if drift["verdict"] == DRIFT_APPEND:
        warnings.append("decision_appended: append-only, cache preserve, cout = delta")

    plan = build_prefill_plan(
        zones=zones,
        stable_tokens=stable_tokens,
        volatile_tokens=volatile_tokens,
        warnings=warnings,
        risk="high"
        if drift["cache_broken"] or drift["semantic_break"]
        else ("medium" if drift["verdict"] == DRIFT_MINOR else "low"),
    )
    return {"zones": zones, "drift": drift, "prefill_plan": plan}


def serialize_zones(zones: dict[str, str]) -> str:
    return json.dumps(zones, sort_keys=True)


def now() -> float:
    return time.time()
