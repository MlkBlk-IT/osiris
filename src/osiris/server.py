"""OSIRIS — serveur MCP (transport stdio).

Six outils, un seul but : reduire le contexte, proteger le cache, bloquer
les boucles, empecher les cassees, partager le travail, reprendre apres un
crash — sans jamais controller le LLM ni dependre d'un provider.

Regle de design : l'agent ne calcule **jamais** de hash. Il transmet les
arguments bruts ; OSIRIS canonicalise, digeste et decide.
"""

from __future__ import annotations

import inspect
import json
import sys
import time
from typing import Any

from fastmcp import FastMCP

from osiris import audit as audit_mod
from osiris.config import settings
from osiris.core import (
    adaptive,
    compaction,
    compass,
    events,
    fileops,
    handoff,
    invariants,
    ledger,
    loopguard,
    memory,
    prefix,
    pressure,
    prune,
    refs,
    runtime,
)
from osiris.core import query as query_engine
from osiris.core.adaptive import (
    EXTERNALIZE_MIN_TOKENS,
    SCHEMA_ACCESS_TOKENS,
    measure_schema_tokens,
)
from osiris.core.errors import AccessDenied, InvalidInput
from osiris.core.ids import hash_args, sha256_hex
from osiris.core.manifest import build_manifest
from osiris.core.task_state import FileEntry, ToolResultEntry
from osiris.core.tokens import count_tokens

mcp = FastMCP(
    name="osiris",
    instructions=(
        "OSIRIS — context engine cache-aware. Utilise osiris.plan au debut d'une "
        "tache, osiris.observe apres chaque appel d'outil, osiris.precheck avant "
        "une action risquee, osiris.recall pour rehydrater un ref, "
        "osiris.checkpoint pour materialiser l'etat, osiris.handoff pour deleguer."
    ),
)

#: Au-dela de ce nombre de tokens, un resultat d'outil est externalise.
#: Ce seuil est celui de la politique adaptative (`EXTERNALIZE_MIN_TOKENS`),
#: aligne sur le regime reel mesure (~120 tok) : le garder a 800 en dur ici
#: annulait la politique adaptative (les deux conditions se cumulaient).
AUTO_EXTERNALIZE_TOKENS = EXTERNALIZE_MIN_TOKENS

#: Kinds acceptes par osiris.observe.
OBSERVE_KINDS = (
    "tool_result",
    "payload",
    "file",
    "decision",
    "constraint",
    "lesson",
    "test_result",
    "failure",
    "note",
    "contract",
    "head",
    "dropped",
)

#: Mode « dispatch only » : seul `osiris.call` est expose au client.
#:
#: Le tableau `tools` fait partie du prefixe mis en cache par le provider :
#: le modifier invalide le cache. Certains clients/transportes preferent un
#: point d'entree unique, stable dans le temps. Les six outils restent
#: definis (le dispatcher les appelle) mais ne sont pas exposes.
DISPATCH_ONLY = settings.dispatch_only


def _tool(name: str):
    """Enregistre un outil — sauf en mode dispatch-only."""

    def deco(fn):
        if not DISPATCH_ONLY:
            mcp.tool(name=name)(fn)
        return fn

    return deco


#: Phases du cycle agent, deduites du kind de `osiris.observe`.
PHASE_BY_KIND = {
    "file": "observation",
    "payload": "observation",
    "tool_result": "observation",
    "decision": "planning",
    "constraint": "planning",
    "lesson": "planning",
    "test_result": "verification",
    "failure": "verification",
    "note": "planning",
}


# --------------------------------------------------------------------------
# helpers internes
# --------------------------------------------------------------------------


def _zones(state) -> dict[str, Any]:
    """Calcule zones, drift et plan de prefill pour l'etat courant."""
    return prefix.analyze_prefix(
        objective=state.objective,
        constraints=state.constraints,
        decisions=state.decisions,
        plan_global=state.plan.steps,
        project_rules_digest=invariants.rules_digest(),
        client_contract_hash=state.hashes.get("client_contract_hash", ""),
        client_system_hash=state.hashes.get("client_system_hash", ""),
        previous=state.hashes,
        previous_pinned=prefix.load_pinned(state.hashes.get("pinned_tail", "")),
    )


def _remember_pinned(state) -> None:
    """Memorise l'etat des elements epingles (contraintes + decisions).

    Sans ce snapshot, on ne peut pas distinguer un APPEND d'une REECRITURE :
    deux collections peuvent avoir le meme hash final tout en n'ayant jamais
    partage un element. C'est ce snapshot qui rend l'invariant n°2 verifiable.
    """
    state.hashes["pinned_tail"] = prefix.pinned_snapshot(
        state.constraints, state.decisions
    )


def _issue_manifest(state, analysis: dict[str, Any]) -> dict[str, str]:
    """Produit le manifeste + seal et memorise le seal emis."""
    zones = analysis["zones"]
    manifest = build_manifest(
        task_id=state.task_id,
        objective=state.objective,
        plan_current=state.plan.current,
        plan_total=state.total_steps,
        invariants_count=len(invariants.active_ids()),
        files_count=len(state.files),
        refs_count=len(state.tool_results),
        budget_ok=state.budget.ok,
        zones=zones,
        decisions_count=len(state.decisions),
    )
    state.hashes.update(zones)
    state.hashes["issued_seal"] = manifest["seal"]
    _remember_pinned(state)
    return manifest


def _restore_from_checkpoint(state, ck_state: dict[str, Any]) -> None:
    """Fusion checkpoint + etat courant.

    Les champs append-only (objectif, contraintes, decisions) gardent la
    version la plus recente ; les champs remplacables (plan, fichiers,
    resultats, echecs) viennent du checkpoint.
    """
    restored = type(state).from_json(ck_state)
    state.plan = restored.plan
    state.files = restored.files
    state.tool_results = restored.tool_results
    state.failures = restored.failures
    state.budget.tokens_estimated = restored.budget.tokens_estimated
    state.budget.cost_estimated = restored.budget.cost_estimated
    state.budget.tool_calls = restored.budget.tool_calls


def _budget_payload(state) -> dict[str, Any]:
    return {
        "tokens_estimated": state.budget.tokens_estimated,
        "tokens_saved": state.budget.tokens_saved,
        "tokens_moved": state.budget.tokens_moved,
        "context_tokens": state.budget.context_tokens_current,
        "tokens_remaining": state.budget.tokens_remaining,
        "cost_estimated_usd": round(state.budget.cost_estimated, 6),
        "cost_remaining_usd": state.budget.cost_remaining,
        "tool_calls": state.budget.tool_calls,
        "max_tokens": state.budget.max_tokens,
        "max_tool_calls": state.budget.max_tool_calls,
        "phase": state.budget.phase,
        "ok": state.budget.ok,
    }


def _is_engaged(state) -> bool:
    """OSIRIS s'engage-t-il sur cette tache ?

    La decision est **prise une fois** (au `plan`) et memorisee dans les flags :
    la recomputer a chaque appel a partir du volume courant rendait le
    comportement incoherent (reponses pleines mais ecriture nulle). Une tache
    sans volume declare engage par defaut : l'agent a appele OSIRIS, il assume
    le cout — et ce cout doit etre **comptabilise**.
    """
    flag = state.flags.get("osiris_engaged")
    if flag is not None:
        return bool(flag)
    volume = int(state.flags.get("osiris_volume") or 0)
    return adaptive.should_engage(volume) if volume > 0 else True


def _finalize(task_id: str, payload: dict[str, Any], state=None) -> dict[str, Any]:
    """Enregistre le surcout propre d'OSIRIS et renvoie la reponse.

    Le surcout est la taille **reelle** de la reponse serialisee : c'est ce
    que l'agent paie pour lire OSIRIS. Le cout des schemas, paye une fois par
    tache cote client, est pose par `_record_schema_access()` (kind
    `schema_access`) et n'est donc pas double-compte ici.

    La reduction de charge utile est du ressort de chaque outil (cf. le mode
    `light` de `osiris.observe`) : aucun champ porteur d'information
    (`dup`, `loop`, `ref`, `hint`) ne doit etre supprime apres coup.
    """
    overhead = count_tokens(json.dumps(payload, ensure_ascii=False, default=str))
    engaged = _is_engaged(state) if state is not None else _is_engaged(_load(task_id))
    if engaged:
        ledger.record(task_id, "overhead", tokens_in=overhead, note="tool_response")
    return payload


def _load(task_id: str):
    """Charge l'etat d'une tache (None si elle n'existe pas)."""
    try:
        return runtime.get_task(task_id)
    except Exception:
        return None


def _credit_filtered_access(state, ref: str, selection: dict[str, Any], op: str) -> int:
    """Credit le cout evite par un acces **filtre** a un ref.

    Mesure de reference : ce que l'agent aurait paye pour un acces complet au
    meme contenu (payload observe, ou fichier qu'il aurait lu lui-meme).
    L'acces filtre a cout `tokens` : l'economie vaut `contenu_complet - lu`.

    C'est la **preuve par la mesure** du gain, sans exiger un accuse de
    reception supplementaire de l'agent : le cout evite est dans le ledger, il
    est verifiable ligne par ligne.

    Credit une seule fois par ref : au-dela, l'agent relit un extrait qu'il
    connait deja — ce n'est plus une relecture complete evitee, donc ce n'est
    plus un gain.
    """
    if not op or op == "excerpt":
        return 0
    entry = refs.get(ref)
    if entry is None:
        return 0
    full = int(entry.get("tokens") or 0)
    got = int(selection.get("tokens") or 0)
    gain = max(0, full - got)
    if gain <= 0:
        return 0
    note = f"ref:{ref}"
    already = (
        runtime.get_conn()
        .execute(
            "SELECT COUNT(*) AS n FROM ledger WHERE task_id = ? AND kind = 'saving' AND note = ?",
            (state.task_id, note),
        )
        .fetchone()
    )
    if int(already["n"]) > 0:
        return 0
    state.budget.tokens_saved += gain
    ledger.record(state.task_id, "saving", tokens_saved=gain, note=note)
    events.append(
        state.task_id,
        "saving",
        {"ref": ref, "tokens": gain, "kind": "filtered_access", "op": op},
    )
    return gain


def _task_volume(task_id: str) -> int:
    """Volume de payload connu pour une tache (0 = inconnu).

    Lit `osiris_volume` sur l'etat persiste. Sert a decider si OSIRIS
    s'engage : sous `BYSTANDER_BELOW_TOKENS`, il se retire completement.
    """
    try:
        state = runtime.get_task(task_id)
    except Exception:
        return 0
    if state is None:
        return 0
    try:
        return int(state.flags.get("osiris_volume") or 0)
    except (TypeError, ValueError):
        return 0


async def _record_schema_access(task_id: str, engaged: bool = True) -> None:
    """Comptabilise une seule fois par tache le cout des schemas d'outils.

    La mesure du cout (measure_schema_tokens) s'effectue toujours, meme en
    mode bystander : le client a charge les schemas. Mais l'imputation au
    ledger ne se fait que si OSIRIS est engage (P1) : en bystander, il se
    retire et ne compte pas ce qu'il n'a pas choisi de charger.
    """
    # Mesure paresseuse : `FastMCP.list_tools()` est async, donc le cout des
    # schemas ne peut pas etre connu avant la premiere tache. On le mesure ici
    # (on est deja dans une coroutine) puis on le met en cache dans
    # `adaptive.SCHEMA_ACCESS_TOKENS`.
    await measure_schema_tokens()
    if not engaged or SCHEMA_ACCESS_TOKENS <= 0:
        return
    row = (
        runtime.get_conn()
        .execute(
            "SELECT COUNT(*) AS n FROM ledger WHERE task_id = ? AND kind = 'schema_access'",
            (task_id,),
        )
        .fetchone()
    )
    if int(row["n"]) > 0:
        return
    ledger.record(
        task_id,
        "schema_access",
        tokens_in=SCHEMA_ACCESS_TOKENS,
        note="tool_schemas_once_per_task",
    )


def _compass(state) -> dict[str, Any]:
    usage = runtime.tool_usage(state.task_id)
    failing = {f.tool for f in state.failures.values() if f.count >= 2 and f.tool}
    return compass.recommend(
        objective=state.objective,
        current_step=state.current_step,
        known_tools=list(usage.keys()),
        blocked_tools=loopguard.blocked_tools(state.task_id),
        failing_tools=failing,
        forbidden_tools=set(),
        used_tools=[t for t, n in usage.items() if n <= 2],
    )


# --------------------------------------------------------------------------
# osiris.plan
# --------------------------------------------------------------------------


@_tool("osiris.plan")
async def osiris_plan(
    objective: str = "",
    steps: tuple[str, ...] = (),
    constraints: tuple[str, ...] = (),
    mode: str = "start",
    task_id: str = "",
    context_tokens: int = 0,
) -> dict[str, Any]:
    """Tache : plan, manifeste scelle. start | update | resume | status.

    Args:
        objective: Objectif.
        steps: Etapes.
        constraints: Regles.
        mode: start | update | resume | status.
        task_id: Tache a reprendre.
        context_tokens: Tokens du contexte (0 = inconnu).

    Returns:
        task_id, manifest, seal, mode, budget, next_step, compass, drift.
    """
    if mode not in ("start", "update", "resume", "status"):
        raise InvalidInput(f"mode invalide: {mode}")

    if mode == "status":
        # Decomposition de la pression contexte (P2-14) : ce qui occupe la
        # fenetre, ce qui est mesure et ce qui reste inconnu.
        state = runtime.get_task(task_id) or runtime.ensure_task(task_id)
        snapshot = pressure.snapshot(
            state,
            schema_tokens=SCHEMA_ACCESS_TOKENS,
            overhead_tokens=ledger.overhead(state.task_id),
            phase_budgets=settings.phase_budgets,
        )
        # P5: vue unifiee du gain net (module decision)
        from osiris.core import decision as decision_mod
        snapshot["net_gain"] = decision_mod.net_gain(state.task_id)
        runtime.save_task(state)
        return _finalize(
            state.task_id,
            {"task_id": state.task_id, "status": snapshot},
            state,
        )

    if mode == "start":
        state = runtime.create_task(objective, list(steps) or None, list(constraints) or None)
        events.append(state.task_id, "task_start", {"objective": objective})
        # Le volume doit etre connu AVANT toute ecriture : c'est lui qui decide
        # si OSIRIS s'engage ou reste bystander (cout nul).
        if context_tokens > 0:
            state.flags["osiris_volume"] = context_tokens
            runtime.save_task(state)
    else:
        state = runtime.get_task(task_id)
        if state is None:
            # Ne pas creer silencieusement une tache vide : `update`/`resume`
            # sur un identifiant inconnu est une erreur d'appel, pas une
            # nouvelle tache sans objectif.
            raise InvalidInput(f"tache inconnue: {task_id or '(vide)'}")
        if objective and objective != state.objective:
            state.objective = objective
        if steps:
            state.plan.steps = list(steps)
            state.plan.current = min(state.plan.current, max(0, len(steps) - 1))
        for constraint in constraints:
            state.add_constraint(constraint)
            memory.add(state.task_id, "constraint", constraint, scope="task")

    resume_info: dict[str, Any] = {}
    if mode == "resume":
        checkpoint = events.latest_checkpoint(state.task_id)
        if checkpoint:
            full = events.get_checkpoint(checkpoint["checkpoint_id"])
            if full:
                _restore_from_checkpoint(state, full["state"])
        unknown = events.open_actions(state.task_id)
        completed = events.completed_actions(state.task_id)
        resume_info = {
            "checkpoint": checkpoint["checkpoint_id"] if checkpoint else "",
            "done": list(state.plan.done),
            "current": state.current_step,
            "unknown_actions": [{"tool": a["tool"], "run_key": a["run_key"]} for a in unknown],
            "completed_actions": len(completed),
            "note": "verifie les actions inconnues avant de rejouer",
        }
        events.append(state.task_id, "resume", {"unknown": len(unknown)})

    analysis = _zones(state)
    # Volume **DECLARE** par l'agent. On ne prend plus le cumul des tokens
    # observes (il ne redescend jamais : le niveau montait a perpetuite) ni le
    # maximum historique (le niveau ne pouvait plus redescendre en `light`).
    declared = (
        context_tokens if context_tokens > 0 else int(state.flags.get("osiris_volume") or 0)
    )
    state.flags["osiris_peak_volume"] = max(
        int(state.flags.get("osiris_peak_volume") or 0), declared
    )
    if context_tokens > 0:
        state.budget.context_tokens_current = context_tokens
    if declared > 0:
        level = adaptive.level_for(declared)
        engaged = adaptive.should_engage(declared)
    else:
        # Volume inconnu : l'agent a appele `plan`, il veut de l'aide. On
        # engage — et donc on **comptabilise** le cout. Repondre en mode
        # bystander sans rien noter revenait a payer sans jamais l'ecrire.
        level = adaptive.LEVEL_STANDARD
        engaged = True
    state.flags["osiris_volume"] = declared
    state.flags["osiris_level"] = level
    state.flags["osiris_engaged"] = engaged

    # P1: les schemas ne sont imputes que si OSIRIS est engage. En mode
    # bystander, OSIRIS se retire : il ne compte pas les schemas qu'il n'a
    # pas choisi de charger.
    if mode == "start" and engaged:
        await _record_schema_access(state.task_id, engaged=True)

    if adaptive.wants_full_manifest(declared) or declared == 0:
        manifest = _issue_manifest(state, analysis)
    else:
        # tache petite : une ligne de manifeste suffit (le seal reste exact)
        seal = analysis["zones"]["prefix_hash"]
        state.hashes.update(analysis["zones"])
        state.hashes["issued_seal"] = f"sha256:{seal}"
        _remember_pinned(state)
        manifest = {
            "manifest": f"OSIRIS/1 {level}",
            "seal": f"sha256:{seal}",
        }

    compass_out = _compass(state)
    runtime.save_task(state)

    # OSIRIS doit etre rentable : si son surcout depasse son gain, on le dit.
    net = ledger.net_saving(state.task_id)
    warning = ""
    if net < 0:
        warning = (
            "surcout OSIRIS > gain sur cette tache : "
            "appelle osiris moins souvent (un observe par action utile, "
            "pas par action triviale)"
        )

    if level in (adaptive.LEVEL_LIGHT, adaptive.LEVEL_BYSTANDER):
        # Mode leger ou bystander : pas de compass, pas de budget detaille,
        # pas de resume. En `bystander` OSIRIS ne s'engage pas : sa reponse
        # doit donc etre minimale, sinon il coute des tokens sans rien
        # apporter (le bench mesurait -19 % de surcout a 200 tokens).
        return _finalize(
            state.task_id,
            {
                "task_id": state.task_id,
                "mode": level,
                "manifest": manifest["manifest"],
            },
            state,
        )

    return _finalize(
        state.task_id,
        {
            "task_id": state.task_id,
            "mode": level,
            "manifest": manifest["manifest"],
            "seal": manifest["seal"],
            "budget": {
                "ok": state.budget.ok,
                "remaining": state.budget.tokens_remaining,
                "calls": state.budget.tool_calls,
            },
            "next_step": state.current_step,
            "compass": {
                "rec": compass_out["recommended_tools"],
                "avoid": compass_out["avoid_tools"],
            },
            "drift": analysis["drift"]["verdict"],
            "guidance": adaptive.guidance(level, declared),
            **({"hint": warning} if warning else {}),
            **({"resume": resume_info} if resume_info else {}),
        },
        state,
    )


# --------------------------------------------------------------------------
# osiris.precheck
# --------------------------------------------------------------------------


@_tool("osiris.precheck")
def osiris_precheck(
    action: str = "",
    args: str = "",
    reason: str = "",
    task_id: str = "",
) -> dict[str, Any]:
    """Verifie une action avant qu'elle parte : invariant, doublon, budget.

    Args:
        action: Action (ex: git.commit).
        args: Arguments (JSON).
        reason: Pourquoi.
        task_id: Tache (vide = tache courante).

    Returns:
        verdict (allow|warn|block|suggest_alternative), reasons, required_action.
    """
    state = runtime.get_task(task_id) or runtime.ensure_task(task_id)
    reasons: list[str] = []
    required_action = ""
    alternative = ""
    invariant_id = ""

    violations = invariants.evaluate(
        action=action,
        args=args,
        flags=state.flags,
        budget_ok=state.budget.ok,
    )
    for violation in violations:
        reasons.append(f"{violation['id']}: {violation['message']}")
        invariant_id = invariant_id or violation["id"]
        required_action = required_action or violation.get("required_action", "")

    if not state.budget.ok:
        reasons.append("budget: budget de tache epuise")
        required_action = required_action or "reduce_scope"

    # Budget de phase : une phase ne doit pas affamer les autres.
    phase = state.budget.phase
    if phase and not state.budget.phase_ok(settings.phase_budgets):
        used = state.budget.phase_used(phase)
        limit = settings.phase_budgets.get(phase, 0)
        reasons.append(f"phase_budget: phase '{phase}' a {used} tokens (limite {limit})")
        required_action = required_action or "reduce_scope"

    # action destructive deja executee ?
    duplicate = False
    if action:
        row = (
            runtime.get_conn()
            .execute(
                "SELECT COALESCE(SUM(count), 0) AS n FROM fingerprints"
                " WHERE task_id = ? AND tool = ? AND args_hash = ?",
                (state.task_id, action, hash_args(args)),
            )
            .fetchone()
        )
        duplicate = int(row["n"]) >= 1

    if duplicate:
        reasons.append("duplicate: appel identique deja journalise")
        alternative = "utilise le ref deja stocke au lieu de rejouer"

    # Ordre des verdicts : `suggest_alternative` doit rester atteignable.
    # Avant, `reasons` (non vide des qu'il y a un doublon) passait avant
    # `duplicate` : le verdict `suggest_alternative` etait du code mort.
    verdict = "allow"
    if any(v["verdict"] == "block" for v in violations) or not state.budget.ok:
        verdict = "block"
    elif duplicate:
        verdict = "suggest_alternative"
    elif reasons or any(v["verdict"] == "warn" for v in violations):
        verdict = "warn"

    if verdict == "block" and not required_action:
        required_action = "resolve_violation"

    ledger.record(
        state.task_id,
        "precheck",
        tokens_in=count_tokens(f"{action} {args}"),
        note=f"{verdict}:{action}",
    )
    runtime.save_task(state)

    return _finalize(
        state.task_id,
        {
            "verdict": verdict,
            "reason": "invariant_violation"
            if invariant_id
            else ("budget" if not state.budget.ok else ""),
            "invariant": invariant_id,
            "reasons": reasons,
            "required_action": required_action,
            "alternative": alternative,
            "budget_ok": state.budget.ok,
        },
        state,
    )


# --------------------------------------------------------------------------
# osiris.observe
# --------------------------------------------------------------------------


@_tool("osiris.observe")
def osiris_observe(
    kind: str = "tool_result",
    tool: str = "",
    args: str = "",
    result: str = "",
    status: str = "ok",
    path: str = "",
    seal: str = "",
    context_tokens: int = 0,
) -> dict[str, Any]:
    """Consigne une action : doublons, boucles, externalisation.

    Args:
        kind: tool_result | payload | file | decision | constraint | lesson |
            test_result | failure | note | contract | head | dropped.
        tool: Outil.
        args: Arguments (JSON).
        result: Resultat (ou ref, pour kind=dropped).
        status: ok | error | skipped.
        path: Chemin (kind=file).
        seal: Seal (ecart = derive).
        context_tokens: Taille declaree de ton contexte (0 = inconnu).

    Returns:
        ok, ref, moved, saved, dup, loop, hint, seal, drift.
    """
    if kind not in OBSERVE_KINDS:
        kind = "note"

    state = runtime.ensure_task()
    ref_out = ""
    tokens_moved = 0
    tokens_saved = 0
    hint = ""
    dup = False
    volume_hint = 0
    handled = False

    # Dernier tour **avant** d'ecrire l'evenement courant : c'est la base de
    # la mesure du delai de cache. (Mesurer apres aurait toujours donne 0.)
    last_turn = events.last_turn_ts(state.task_id)

    events.append(
        state.task_id,
        "observe",
        {"kind": kind, "tool": tool, "args": args, "status": status, "path": path},
    )

    # -- cas speciaux ------------------------------------------------------
    if kind == "file" and path:
        try:
            info = fileops.read_text(path)
        except AccessDenied as exc:
            return _finalize(
                state.task_id,
                {
                    "ok": False,
                    "ref": "",
                    "saved": 0,
                    "dup": False,
                    "loop": "allow",
                    "hint": f"acces refuse: {exc}",
                    "drift": "none",
                },
            )
        file_tokens = count_tokens(str(info["content"]))
        volume_hint = file_tokens
        previous = state.files.get(info["path"])
        dup = bool(previous and previous.content_hash == info["sha256"])
        if adaptive.should_externalize(file_tokens):
            entry = prune.externalize(
                state.task_id,
                str(info["content"]),
                # `in_context: false` : le fichier est lu **cote serveur**, son
                # contenu n'est jamais entre dans la fenetre du modele. Le
                # premier acces au ref est donc celui qui evite la lecture
                # complete : le gain se mesure a ce moment-la.
                meta={"path": info["path"], "in_context": False},
            )
            ref_out = entry["ref"]
            # Le contenu du fichier est lu **cote serveur** : il n'est jamais
            # entre dans le contexte du modele. C'est donc un deplacement,
            # pas une economie. Crediter ici une economie inventait 11 534
            # tokens "gagnes" pour 2 494 tokens reellement observes.
            tokens_moved = entry["tokens_moved"]
            events.append(
                state.task_id,
                "externalize",
                {"ref": ref_out, "kind": "file", "path": info["path"], "tokens": tokens_moved},
            )
        handled = True
        # sinon : hash seul. La detection de doublon reste possible, sans le
        # cout d'une ref (~30 tokens) ni d'un stockage.
        state.files[info["path"]] = FileEntry(
            path=info["path"],
            content_hash=info["sha256"],
            mtime=info["mtime"],
            last_read_at=time.time(),
            ref=ref_out or None,
            size_bytes=int(info["size_bytes"]),
        )
        if dup:
            hint = (
                "deja lu, hash inchange : ne relis pas"
                if not ref_out
                else "deja lu, hash inchange : utilise le ref au lieu de relire"
            )

    elif kind == "payload" and result:
        payload_tokens = count_tokens(result)
        volume_hint = payload_tokens
        if adaptive.should_externalize(payload_tokens):
            entry = prune.externalize(
                state.task_id, result, meta={"tool": tool, "in_context": True}
            )
            ref_out = entry["ref"]
            # Deplace, pas encore sorti : l'economie sera creditee quand
            # l'agent accusera reception de la suppression (kind="dropped").
            tokens_moved = entry["tokens_moved"]
            events.append(
                state.task_id,
                "externalize",
                {"ref": ref_out, "kind": "payload", "tokens": tokens_moved},
            )
        else:
            hint = "payload trop petit pour etre externalise : garde-le en contexte"
        handled = True

    elif kind == "decision" and result:
        state.add_decision(result)
        memory.add(state.task_id, "decision", result, scope="task", pinned=True)
        events.append(state.task_id, "decision", {"text": result})
        handled = True

    elif kind == "constraint" and result:
        state.add_constraint(result)
        memory.add(state.task_id, "constraint", result, scope="task", pinned=True)
        events.append(state.task_id, "constraint", {"text": result})
        handled = True

    elif kind == "lesson" and result:
        state.lessons.append(result)
        memory.add(state.task_id, "lesson", result, scope="project")
        events.append(state.task_id, "lesson", {"text": result})
        handled = True

    elif kind == "test_result":
        passed = status == "ok"
        state.set_flag("tests_passed", passed)
        state.set_flag("tests_failed", not passed)
        memory.add(
            state.task_id,
            "note",
            f"tests {'PASS' if passed else 'FAIL'}",
            scope="task",
        )
        events.append(state.task_id, "test_result", {"passed": passed, "tool": tool})
        handled = True

    elif kind == "failure" and result:
        sig = loopguard.error_signature(result)
        state.failures.setdefault(sig, None)
        from osiris.core.task_state import FailureEntry

        entry = state.failures.get(sig)
        if entry is None:
            entry = FailureEntry(
                signature=sig,
                tool=tool,
                args_hash=hash_args(args),
                count=1,
                first_at=time.time(),
                last_at=time.time(),
            )
        else:
            entry.count += 1
            entry.last_at = time.time()
        state.failures[sig] = entry
        memory.add(state.task_id, "failure", result[:400], scope="task")
        events.append(state.task_id, "failure", {"signature": sig})
        handled = True

    elif kind == "contract" and result:
        # Le contrat d'outils du client fait partie de la zone B : il change
        # -> le prefixe cache meurt. On le surveille, et surtout on detecte
        # le contenu **volatil** qu'il contient (timestamps, UUIDs, build id) :
        # c'est la cause n°1 de mort du prefix cache en pratique.
        state.hashes["client_contract_hash"] = sha256_hex(result)
        volatile = prefix.scan_volatile(result)
        state.flags["contract_volatile"] = volatile
        events.append(
            state.task_id,
            "contract",
            {"hash": state.hashes["client_contract_hash"], "volatile": volatile},
        )
        hint = "contract outil enregistre : un changement ici casse le prefix cache"
        if volatile:
            hint = (
                f"ATTENTION contenu volatil dans le contract ({', '.join(volatile)}) : "
                "il change a chaque tour et casse le prefix cache. "
                "Retire timestamps/UUIDs/build-id du contract."
            )
        handled = True

    elif kind == "head" and result:
        # System head du client : c'est la zone la plus sensible du cache.
        state.hashes["client_system_hash"] = sha256_hex(result)
        volatile = prefix.scan_volatile(result)
        state.flags["head_volatile"] = volatile
        events.append(
            state.task_id,
            "head",
            {"hash": state.hashes["client_system_hash"], "volatile": volatile},
        )
        hint = "system head enregistre"
        if volatile:
            hint = (
                f"ATTENTION contenu volatil dans le head ({', '.join(volatile)}) : "
                "ce head invalide le prefix cache a chaque requete."
            )
        handled = True

    elif kind == "dropped" and result:
        # Accuse de reception : l'agent confirme avoir retire le payload de
        # son contexte. C'est la SEULE occasion de crediter une economie
        # reelle — jusqu'ici le ledger credait des tokens qui n'etaient
        # jamais entres dans la fenetre.
        entry = refs.get(result.strip())
        if entry is None:
            hint = "ref inconnue : aucune economie a crediter"
        else:
            tokens_saved = entry["tokens"]
            state.budget.tokens_saved += tokens_saved
            ledger.record(
                state.task_id,
                "saving",
                tokens_saved=tokens_saved,
                note=f"dropped:{entry['ref']}",
            )
            events.append(
                state.task_id,
                "dropped",
                {"ref": entry["ref"], "tokens": tokens_saved},
            )
            hint = f"{tokens_saved} tokens prouvent retires du contexte"
        handled = True

    elif kind == "note" and result:
        memory.add(state.task_id, "note", result, scope="task")
        events.append(state.task_id, "note", {"text": result[:400]})
        handled = True

    # -- cas general : resultat d'outil ------------------------------------
    # Un kind deja traite ne doit pas etre recompte comme un resultat
    # d'outil (double comptage des tokens et des appels de boucle).
    _SPECIAL_KINDS = ("file", "decision", "constraint", "contract", "head", "dropped")
    if not handled and (kind == "tool_result" or (tool and kind not in _SPECIAL_KINDS)):
        runtime.bump_tool_usage(state.task_id, tool)
        state.budget.tool_calls += 1
        verdict = loopguard.record(state.task_id, tool, args, result or "", status)
        loop_verdict = verdict["verdict"]
        if verdict.get("detail"):
            hint = f"{verdict['reason']}: {verdict['detail']}"
        if verdict["verdict"] == "suggest_alternative":
            dup = True
        events.append(
            state.task_id,
            "action",
            {"tool": tool, "args": args, "status": status},
            run_key=events.make_run_key(tool, args),
            action_state=events.STATE_SUCCEEDED if status == "ok" else events.STATE_FAILED,
        )
        # externalisation automatique d'un gros resultat
        result_tokens = count_tokens(result) if result else 0
        volume_hint = max(volume_hint, result_tokens)
        if (
            result
            and result_tokens > AUTO_EXTERNALIZE_TOKENS
            and adaptive.should_externalize(result_tokens)
        ):
            entry = prune.externalize(
                state.task_id, result, meta={"tool": tool, "in_context": True}
            )
            ref_out = ref_out or entry["ref"]
            # Le resultat **etait** dans le contexte du modele, mais il n'en
            # sortira que si l'agent le retire. C'est donc un deplacement ;
            # l'economie est creditee a l'accuse de reception (kind=dropped).
            tokens_moved += entry["tokens_moved"]
            events.append(
                state.task_id,
                "externalize",
                {"ref": entry["ref"], "kind": "tool_result", "tokens": entry["tokens_moved"]},
            )
            cache_key = sha256_hex(f"{tool}|{hash_args(args)}")
            state.tool_results[cache_key] = ToolResultEntry(
                cache_key=cache_key,
                ref=entry["ref"],
                size_bytes=entry["size_bytes"],
                tokens=entry["tokens"],
                created_at=time.time(),
            )
    else:
        loop_verdict = "allow"

    # -- comptabilite des tokens ------------------------------------------
    observed = count_tokens(result) if kind in ("tool_result", "payload") else 0
    state.budget.tokens_estimated += observed
    state.budget.tokens_moved += tokens_moved
    # `tokens_saved` reste a 0 ici : une economie n'est creditee que sur
    # accuse de reception (kind="dropped"), donc sur une preuve.
    ledger.record(
        state.task_id,
        "observe",
        tokens_in=observed,
        tokens_moved=tokens_moved,
        note=kind,
    )

    # -- budget par phase ----------------------------------------------------
    phase = PHASE_BY_KIND.get(kind, "")
    if phase:
        state.budget.phase = phase
        state.budget.phase_tokens[phase] = (
            state.budget.phase_tokens.get(phase, 0) + observed
        )

    # -- drift + prune automatique ------------------------------------------
    analysis = _zones(state)
    # On retient l'etat epingle courant : le prochain appel saura ainsi
    # distinguer un ajout d'une REECRITURE.
    _remember_pinned(state)
    drift = analysis["drift"]
    issued = state.hashes.get("issued_seal", "")
    if seal and issued and seal != issued:
        drift = {
            "verdict": "critical",
            "changed": ["client_head"],
            "cause": "seal_mismatch",
            "cache_broken": True,
            "semantic_break": False,
            "cache_hit_estimate": 0.0,
            "action": "restore_head_and_alert",
        }
        hint = hint or "seal porte par l'agent different de l'etat OSIRIS : head derive"

    events.append(
        state.task_id,
        "prefix",
        {"prefix_hash": analysis["zones"]["prefix_hash"], "drift": drift["verdict"]},
    )

    # -- prune : declenche sur la fenetre COURANTE, pas sur un cumul -------
    # Le seuil (40k) est une taille de contexte ; le comparer a un cumul de
    # tokens traites n'a aucun sens et se declenchait au bon hasard.
    window_tokens = state.budget.context_tokens_current or state.budget.tokens_estimated
    prune_info = prune.evaluate(
        current_tokens=window_tokens,
        mode=settings.prune_mode,
        elapsed_since_last_turn_s=prune.elapsed_since(last_turn),
        ttl_s=settings.cache_ttl_s,
        threshold_tokens=settings.prune_threshold_tokens,
    )
    if prune_info["should_prune"]:
        candidates = prune.select_candidates(state)
        reclaimable = sum(int(c.get("tokens") or 0) for c in candidates)
        if reclaimable:
            net = prune.net_saving(
                reclaimable,
                window_tokens,
                prune_info["cache_mort_prob"],
                touches_prefix=prune_info["can_prune_prefix"],
            )
            hint = hint or (
                f"fenetre au-dessus du seuil ({prune_info['threshold_tokens']} tok) : "
                f"{reclaimable} tok recyclables dans {len(candidates)} ref(s) "
                f"(net {net}, cache_mort={prune_info['cache_mort_prob']}) — "
                "retire ces refs de ton contexte puis appelle "
                "osiris.observe(kind='dropped', result=<ref>)"
            )

    # -- niveau adaptatif ----------------------------------------------------
    # Le volume est la fenetre **declaree** par l'agent : elle peut
    # redescendre. Le max historique (le plus gros payload vu) ne redescendait
    # jamais : le niveau restait bloque a `full` pour le reste de la tache.
    declared = (
        context_tokens if context_tokens > 0 else int(state.flags.get("osiris_volume") or 0)
    )
    if context_tokens > 0:
        state.budget.context_tokens_current = context_tokens
    state.flags["osiris_volume"] = declared
    state.flags["osiris_peak_volume"] = max(
        int(state.flags.get("osiris_peak_volume") or 0), declared
    )
    level = (
        adaptive.level_for(declared)
        if declared > 0
        else (state.flags.get("osiris_level") or adaptive.LEVEL_STANDARD)
    )
    state.flags["osiris_level"] = level
    compact = level in (adaptive.LEVEL_LIGHT, adaptive.LEVEL_BYSTANDER)

    runtime.save_task(state)

    # Le protocole doit etre **decouvrable** par l'agent : sans indice, il ne
    # sait pas qu'il existe une voie pour prouver l'economie (kind="dropped")
    # ni que l'acces filtre est le vrai levier.
    if ref_out and not hint:
        hint = (
            f"ref {ref_out} : relis-la ciblee "
            "(recall op=grep|range|outline, budget_tokens) — un acces filtre "
            "coute bien moins que le contenu complet ; si tu retires le payload "
            "de ton contexte, appelle observe(kind='dropped', result=<ref>)"
        )

    if compact:
        # Mode leger ou bystander : on ne renvoie que ce qui porte une decision.
        # "mode" est deja connu (plan), "loop" n'interesse que s'il signale
        # un probleme. Le reste est du bruit pour l'agent.
        # En `bystander`, OSIRIS ne s'engage pas : sa reponse doit donc etre
        # minimale, sinon il coute des tokens sans rien apporter.
        response: dict[str, Any] = {
            "ok": True,
            "dup": dup,
        }
        if loop_verdict != "allow":
            response["loop"] = loop_verdict
        if ref_out:
            response["ref"] = ref_out
        if tokens_saved:
            response["saved"] = tokens_saved
        if hint:
            response["hint"] = hint
        return _finalize(state.task_id, response, state)

    return _finalize(
        state.task_id,
        {
            "ok": True,
            "ref": ref_out,
            "moved": tokens_moved,
            "saved": tokens_saved,
            "dup": dup,
            "loop": loop_verdict,
            "hint": hint,
            "drift": drift["verdict"],
            "mode": level,
        },
        state,
    )


# --------------------------------------------------------------------------
# osiris.recall
# --------------------------------------------------------------------------


@_tool("osiris.recall")
def osiris_recall(
    ref: str = "",
    task_id: str = "",
    scope: str = "",
    query: str = "",
    kind: str = "",
    budget_tokens: int = 800,
    op: str = "",
    start: int = 0,
    end: int = 0,
) -> dict[str, Any]:
    """Rehydrate un ref, ou restitue l'etat / la memoire d'une tache.

    Args:
        ref: Ref (mem://...).
        task_id: Tache.
        scope: task | project | agent | global.
        query: Filtre texte (extrait cible si un ref est fourni).
        kind: Type de memoire.
        budget_tokens: Budget tokens.
        op: Operation de selection cote serveur quand `ref` est fourni :
            excerpt | grep | count | range | head | tail | outline | aggregate | jsonl.
            (count = nombre de lignes qui matchent `query`, ~3 tokens.)
        start: Premiere ligne (1-based) pour op=range.
        end: Derniere ligne (inclusive) pour op=range.

    Returns:
        items, found, state, budget, open_actions.
    """
    state = runtime.get_task(task_id) or runtime.ensure_task(task_id)

    if ref:
        # Selection **cote serveur** : seul le resultat entre dans le
        # contexte. C'est le levier qui remplace le "recall puis relis tout".
        selection = query_engine.run(
            ref,
            op=op or "excerpt",
            query=query,
            start=start,
            end=end,
            budget_tokens=budget_tokens,
        )
        if not selection.get("found"):
            return _finalize(
                state.task_id,
                {
                    "found": False,
                    "items": [],
                    "note": selection.get("note", "ref inconnue"),
                },
                state,
            )
        credited = _credit_filtered_access(state, ref, selection, op)
        runtime.save_task(state)
        payload: dict[str, Any] = {
            "found": True,
            "items": [selection],
            "total_chars": selection.get("total_chars", 0),
            "op": selection.get("op", "excerpt"),
            "matches": selection.get("matches", 0),
        }
        if credited:
            payload["saved"] = credited
        return _finalize(state.task_id, payload, state)

    entries = memory.list_entries(
        task_id=state.task_id,
        scope=scope or None,
        kind=kind or None,
        query=query or None,
        limit=50,
    )
    items: list[dict[str, Any]] = []
    spent = 0
    for entry in entries:
        cost = count_tokens(entry["body"])
        if spent + cost > budget_tokens and items:
            break
        spent += cost
        items.append(
            {
                "mem_id": entry["mem_id"],
                "kind": entry["kind"],
                "scope": entry["scope"],
                "pinned": entry["pinned"],
                "body": entry["body"],
            }
        )

    return _finalize(
        state.task_id,
        {
            "found": True,
            "items": items,
            "task_id": state.task_id,
            "state": {
                "objective": state.objective,
                "plan_current": state.plan.current,
                "plan_total": state.total_steps,
                "current_step": state.current_step,
                "done": list(state.plan.done),
                "decisions": list(state.decisions),
                "constraints": list(state.constraints),
                "flags": dict(state.flags),
            },
            "budget": {
                "ok": state.budget.ok,
                "remaining": state.budget.tokens_remaining,
                "saved": state.budget.tokens_saved,
                "moved": state.budget.tokens_moved,
                "phase": state.budget.phase,
            },
            "open_actions": [
                {"tool": a["tool"], "run_key": a["run_key"]}
                for a in events.open_actions(state.task_id)
            ],
        },
        state,
    )


# --------------------------------------------------------------------------
# osiris.checkpoint
# --------------------------------------------------------------------------


@_tool("osiris.checkpoint")
def osiris_checkpoint(label: str = "", mode: str = "snapshot", task_id: str = "") -> dict[str, Any]:
    """Snapshot d'etat, ou cloture avec rapport, ou compaction.

    Args:
        label: Etiquette.
        mode: snapshot | final | compact | trim | clear.
        task_id: Tache.

    Returns:
        checkpoint_id, journal_offset, integrity, report (en mode final).
    """
    state = runtime.get_task(task_id) or runtime.ensure_task(task_id)

    # -- compaction de la zone de travail ----------------------------------
    # Un serveur MCP ne peut pas compacter la fenetre du client : il prepare
    # les artefacts (resume, tri, raz de la zone de travail) et l'hote
    # executes la reduction reelle.
    if mode in ("compact", "trim", "clear"):
        if mode == "compact":
            result = compaction.compact(state)
        elif mode == "trim":
            result = compaction.trim(state)
        else:
            result = compaction.clear(state)
        runtime.save_task(state)
        events.append(state.task_id, "compaction", {"mode": mode})
        ledger.record(
            state.task_id,
            "compaction",
            tokens_in=int(result.get("tokens", 0)),
            note=mode,
        )
        # P3: prune les refs expirees (TTL passe) et jamais relues
        pruned = refs.prune_expired(only_unaccessed=True)
        if pruned["removed"] > 0:
            result["pruned_refs"] = pruned["removed"]
            result["bytes_freed"] = pruned["bytes_freed"]
        return _finalize(state.task_id, {"mode": mode, **result}, state)

    checkpoint = events.save_checkpoint(state.task_id, label, state.to_json())
    events.append(state.task_id, "checkpoint", {"label": label, "mode": mode})

    integrity = audit_mod.audit_task(state.task_id)
    runtime.save_task(state)

    # En mode `light`, la charge utile doit rester minimale : on ne renvoie que
    # ce qui porte une decision (l'identifiant du checkpoint, le verdict
    # d'integrite et la preuve de non-perte). Les compteurs et le chemin du
    # rapport restent sur disque — ils ne coutent rien au contexte.
    compact = (state.flags.get("osiris_level") or adaptive.LEVEL_STANDARD) == adaptive.LEVEL_LIGHT

    payload: dict[str, Any] = {
        "checkpoint_id": checkpoint["checkpoint_id"],
        "integrity": "lossless" if integrity["lossless"] else "violation",
        "information_perdue": integrity["items_dropped"],
    }
    if not compact:
        payload["journal_offset"] = checkpoint["journal_offset"]
        payload["items_verified"] = integrity["items_verified"]
        payload["items_externalized"] = integrity["items_externalized"]

    if mode == "final":
        # P4: crediter les economies de boucles (doublons evites) avant le
        # rapport final — preuve : le 2e appel etait identique au 1er.
        ledger.credit_loop_savings(state.task_id, state.budget)
        report = audit_mod.write_report(state.task_id)
        # Un rapport est un artefact sur disque, pas du contexte : on renvoie
        # un seul chemin (le markdown) + son digest. Les 3 rapports (md, json,
        # html) partagent la meme base : md/json/html sont derivables.
        if not compact:
            payload["report"] = report["markdown"]
            payload["report_digest"] = report["report_digest"]

    return _finalize(state.task_id, payload, state)


# --------------------------------------------------------------------------
# osiris.handoff
# --------------------------------------------------------------------------


@_tool("osiris.handoff")
def osiris_handoff(
    mission: str = "",
    must_know: tuple[str, ...] = (),
    allowed_tools: tuple[str, ...] = (),
    forbidden_actions: tuple[str, ...] = (),
    files: tuple[str, ...] = (),
    budget_tokens: int = 0,
    mode: str = "create",
    handoff_id: str = "",
    result: str = "",
) -> dict[str, Any]:
    """Contrat de delegation (create), ou son resultat (complete/collect).

    Args:
        mission: Mission du sous-agent.
        must_know: Faits indispensables (remplacent le contexte parent).
        allowed_tools: Outils.
        forbidden_actions: Interdits.
        files: Fichiers.
        budget_tokens: Budget tokens.
        mode: create | complete | collect.
        handoff_id: Handoff vise.
        result: Resultat (JSON).

    Returns:
        handoff_id, contract, context_refs, estimated_tokens (create) ;
        status, result (complete / collect).
    """
    state = runtime.ensure_task()

    if mode == "complete":
        if not handoff_id:
            raise InvalidInput("handoff_id requis en mode complete")
        payload: dict[str, Any] = {}
        if result:
            try:
                payload = json.loads(result)
            except (ValueError, TypeError):
                payload = {"summary": result}
        ok = handoff.complete(handoff_id, payload)
        events.append(state.task_id, "handoff_complete", {"handoff_id": handoff_id})
        return _finalize(
            state.task_id,
            {"handoff_id": handoff_id, "status": "completed" if ok else "unknown"},
            state,
        )

    if mode == "collect":
        if not handoff_id:
            raise InvalidInput("handoff_id requis en mode collect")
        entry = handoff.get(handoff_id)
        if entry is None:
            return {"handoff_id": handoff_id, "status": "unknown"}
        return _finalize(
            state.task_id,
            {
                "handoff_id": handoff_id,
                "status": entry["status"],
                "result": entry["result"],
            },
            state,
        )

    # Les refs disponibles sont transmises au sous-agent : sans elles, le
    # contrat de delegation transportait un contexte vide (`context_refs=None`
    # code en dur) et le sous-agent relisait tout depuis zero.
    context_refs = [entry.ref for entry in state.tool_results.values() if entry.ref]
    context_refs += [entry.ref for entry in state.files.values() if entry.ref]

    created = handoff.create(
        parent_task_id=state.task_id,
        mission=mission,
        must_know=must_know,
        allowed_tools=allowed_tools,
        forbidden_actions=forbidden_actions,
        files=files,
        budget_tokens=budget_tokens,
        context_refs=context_refs or None,
        state=state,
    )
    state.handoffs[created["handoff_id"]] = {
        "mission": mission,
        "status": "open",
        "estimated_tokens": created["estimated_tokens"],
    }
    events.append(
        state.task_id,
        "handoff",
        {"handoff_id": created["handoff_id"], "tokens": created["estimated_tokens"]},
    )
    ledger.record(
        state.task_id,
        "handoff",
        tokens_in=created["estimated_tokens"],
        note=created["handoff_id"],
    )
    runtime.save_task(state)

    return _finalize(
        state.task_id,
        {
            "handoff_id": created["handoff_id"],
            "contract": created["contract_text"],
            "estimated_tokens": created["estimated_tokens"],
        },
        state,
    )


# --------------------------------------------------------------------------
# point d'entree unique (mode dispatch-only)
# --------------------------------------------------------------------------

if DISPATCH_ONLY:

    @mcp.tool(name="osiris.call")
    async def osiris_call(op: str, args: str = "") -> dict[str, Any]:
        """Point d'entree unique : `op` = plan|precheck|observe|recall|checkpoint|handoff.

        Le tableau `tools` du client fait partie du prefixe mis en cache par
        le provider : plus il est petit et stable, moins le cache est invalide.
        En mode dispatch-only, OSIRIS n'expose que ce point d'entree ; les six
        outils restent disponibles en interne.

        Args:
            op: Operation a executer.
            args: Arguments de l'operation, en JSON.

        Returns:
            Le resultat de l'operation demandee.
        """
        handlers = {
            "plan": osiris_plan,
            "precheck": osiris_precheck,
            "observe": osiris_observe,
            "recall": osiris_recall,
            "checkpoint": osiris_checkpoint,
            "handoff": osiris_handoff,
        }
        handler = handlers.get(op)
        if handler is None:
            raise InvalidInput(f"op inconnue: {op}")
        kwargs: dict[str, Any] = {}
        if args:
            try:
                parsed = json.loads(args)
            except (TypeError, ValueError) as exc:
                raise InvalidInput(f"args illisibles: {exc}") from exc
            if not isinstance(parsed, dict):
                raise InvalidInput("args doivent etre un objet JSON")
            kwargs = parsed
        result = handler(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result


# --------------------------------------------------------------------------
# resources MCP (lecture directe, sans aller-retour d'outil)
# --------------------------------------------------------------------------


@mcp.resource("osiris://task/{task_id}/manifest")
def osiris_manifest_resource(task_id: str) -> str:
    """Manifeste et zones d'une tache.

    Une resource se lit sans appel d'outil : l'hote peut l'injecter dans son
    contexte a cout quasi nul, la ou un appel d'outil coute un aller-retour.
    """
    state = runtime.get_task(task_id)
    if state is None:
        return ""
    analysis = _zones(state)
    return json.dumps(
        {
            "task_id": task_id,
            "zones": analysis["zones"],
            "drift": analysis["drift"],
            "objective": state.objective,
        },
        ensure_ascii=False,
    )


@mcp.resource("osiris://task/{task_id}/status")
def osiris_status_resource(task_id: str) -> str:
    """Pression contexte d'une tache (decomposition mesuree/inconnue)."""
    state = runtime.get_task(task_id)
    if state is None:
        return ""
    snapshot = pressure.snapshot(
        state,
        schema_tokens=SCHEMA_ACCESS_TOKENS,
        overhead_tokens=ledger.overhead(task_id),
        phase_budgets=settings.phase_budgets,
    )
    return json.dumps(snapshot, ensure_ascii=False)


@mcp.resource("osiris://ref/{ref}")
def osiris_ref_resource(ref: str) -> str:
    """Contenu brut d'un ref (lecture directe, hash verifie en amont)."""
    entry = refs.get(ref)
    if entry is None:
        return ""
    return entry["content"]


# --------------------------------------------------------------------------
# prompts MCP
# --------------------------------------------------------------------------


@mcp.prompt(name="osiris/task-resume")
def osiris_task_resume_prompt(task_id: str) -> str:
    """Modele de reprise de tache apres un crash ou un changement de contexte."""
    state = runtime.get_task(task_id)
    if state is None:
        return (
            f"Reprendre la tache {task_id}. Appelle osiris.plan(mode='resume', "
            f"task_id='{task_id}') pour recharger le checkpoint, puis "
            "verifie les actions inconnues avant de les rejouer."
        )
    resume = events.latest_checkpoint(task_id)
    unknown = events.open_actions(task_id)
    lines = [
        f"Reprendre la tache {task_id} : {state.objective}",
        f"Etape courante : {state.current_step} / {state.total_steps}",
        f"Checkpoint : {resume['checkpoint_id'] if resume else 'aucun'}",
        "Decisions epinglees :",
    ]
    lines += [f"- {decision}" for decision in state.decisions[-10:]]
    if unknown:
        lines.append("Actions inconnues (a verifier avant rejeu) :")
        lines += [f"- {action['tool']} ({action['run_key']})" for action in unknown]
    lines.append(
        f"Appelle osiris.plan(mode='resume', task_id='{task_id}') puis "
        "osiris.precheck avant toute action."
    )
    return "\n".join(lines)


def _arg_value(argv: list[str], name: str, default: str) -> str:
    """Valeur d'un flag `--name valeur` ou `--name=valeur`."""
    for index, item in enumerate(argv):
        if item == name and index + 1 < len(argv):
            return argv[index + 1]
        if item.startswith(name + "="):
            return item.split("=", 1)[1]
    return default


def main() -> None:
    """Lance le serveur MCP.

    - **stdio** (defaut) : `python -m osiris` — transport lance par le client
      MCP (Claude Desktop, Claude Code, MiniMax Code).
    - **streamable-http** : `python -m osiris --http --port 8771`
      -> endpoint MCP sur `http://127.0.0.1:8771/mcp`.

    Le mode HTTP sert aux clients qui exigent une URL (connecteur distant,
    tunnel HTTPS). Il expose alors le serveur sur le reseau : a n'utiliser
    que sur une interface de confiance, ou derriere un reverse proxy TLS.
    """
    settings.ensure_dirs()
    argv = sys.argv[1:]
    if "--http" in argv:
        host = _arg_value(argv, "--host", "127.0.0.1")
        port = int(_arg_value(argv, "--port", "8771"))
        path = _arg_value(argv, "--path", "/mcp")
        mcp.run(transport="streamable-http", host=host, port=port, path=path)
        return
    mcp.run()


if __name__ == "__main__":
    main()
