"""`PruneEngine` — externalisation reversible et cache-aware.

Regle centrale :

> OSIRIS ne prune que si l'economie future de tokens depasse le cout estime
> du cache miss provoque.

Concretement :
- tout ce qui est **apres** le breakpoint (zones C et D) est prunable
  **gratuitement** — il ne touche pas au prefixe ;
- tout ce qui est **avant** (zones A et B) n'est prunable que dans la
  fenetre de cache mort (`cache_ttl`), la ou le re-prefill n'est pas un
  cout supplementaire.

Invariant de securite : le prune **deplace** un payload vers un ref. Il ne le
supprime jamais. L'information reste recuperable (contrainte de la spec).
"""

from __future__ import annotations

import time
from typing import Any

from osiris.core import refs
from osiris.core.prefix import cache_mort_probability

#: Modes de pruning.
MODE_CACHE_TTL = "cache_ttl"
MODE_CONSERVATIVE = "conservative"
MODE_BALANCED = "balanced"
MODE_AGGRESSIVE = "aggressive"

MODES = (MODE_CACHE_TTL, MODE_CONSERVATIVE, MODE_BALANCED, MODE_AGGRESSIVE)

#: Seuils (tokens) a partir desquels on prune, par mode.
MODE_THRESHOLDS: dict[str, int] = {
    MODE_CACHE_TTL: 40_000,
    MODE_CONSERVATIVE: 80_000,
    MODE_BALANCED: 40_000,
    MODE_AGGRESSIVE: 20_000,
}

#: Modes autorises a toucher la zone prefixee (A/B).
PREFIX_SAFE_MODES = frozenset({MODE_CACHE_TTL})


def mode_allows_prefix(mode: str, cache_mort_prob: float) -> bool:
    """Vrai si ce mode a le droit de modifier la zone prefixee."""
    if mode not in PREFIX_SAFE_MODES:
        return False
    # en `cache_ttl`, on ne touche au prefixe que si le cache est probablement mort
    return cache_mort_prob >= 0.9


def evaluate(
    current_tokens: int,
    mode: str = MODE_CACHE_TTL,
    elapsed_since_last_turn_s: float = 0.0,
    ttl_s: float = 300.0,
    threshold_tokens: int | None = None,
) -> dict[str, Any]:
    """Decide s'il faut pruner, et avec quel risque cache.

    Returns:
        {"should_prune", "mode", "reason", "cache_risk", "cache_mort_prob",
         "can_prune_prefix", "threshold_tokens"}
    """
    mode = mode if mode in MODES else MODE_CACHE_TTL
    threshold = threshold_tokens if threshold_tokens is not None else MODE_THRESHOLDS[mode]
    mort = cache_mort_probability(elapsed_since_last_turn_s, ttl_s)
    can_prefix = mode_allows_prefix(mode, mort)

    if current_tokens < threshold:
        return {
            "should_prune": False,
            "mode": mode,
            "reason": f"contexte sous le seuil ({current_tokens} < {threshold})",
            "cache_risk": "none",
            "cache_mort_prob": round(mort, 3),
            "can_prune_prefix": can_prefix,
            "threshold_tokens": threshold,
        }

    if mode == MODE_CONSERVATIVE:
        return {
            "should_prune": True,
            "mode": mode,
            "reason": "seuil atteint ; on ne touche qu'a la zone de travail",
            "cache_risk": "none",
            "cache_mort_prob": round(mort, 3),
            "can_prune_prefix": False,
            "threshold_tokens": threshold,
        }

    if mode == MODE_BALANCED:
        return {
            "should_prune": True,
            "mode": mode,
            "reason": "seuil atteint ; zone de travail uniquement (prefixe preserve)",
            "cache_risk": "none",
            "cache_mort_prob": round(mort, 3),
            "can_prune_prefix": False,
            "threshold_tokens": threshold,
        }

    if mode == MODE_AGGRESSIVE:
        return {
            "should_prune": True,
            "mode": mode,
            "reason": "seuil bas ; externalisation large",
            "cache_risk": "low" if can_prefix else "none",
            "cache_mort_prob": round(mort, 3),
            "can_prune_prefix": can_prefix,
            "threshold_tokens": threshold,
        }

    # cache_ttl
    if mort >= 0.9:
        return {
            "should_prune": True,
            "mode": mode,
            "reason": "cache probablement expire : pruner le prefixe ne coute rien",
            "cache_risk": "none",
            "cache_mort_prob": round(mort, 3),
            "can_prune_prefix": True,
            "threshold_tokens": threshold,
        }
    return {
        "should_prune": True,
        "mode": mode,
        "reason": "zone de travail seulement : le prefixe est encore vivant",
        "cache_risk": "none",
        "cache_mort_prob": round(mort, 3),
        "can_prune_prefix": False,
        "threshold_tokens": threshold,
    }


def externalize(
    task_id: str | None,
    content: str,
    meta: dict[str, Any] | None = None,
    ttl: float = 0.0,
) -> dict[str, Any]:
    """Deplace un payload vers un ref. Ne supprime rien.

    `tokens_moved` et non `tokens_saved` : deplacer un payload ne prouve pas
    qu'il a quitte la fenetre du modele. L'economie n'est creditee que quand
    l'agent accuse reception de la suppression (`observe(kind="dropped")`).
    """
    entry = refs.put(task_id, content, meta=meta, ttl=ttl)
    entry["tokens_moved"] = max(0, entry["tokens"])
    return entry


def net_saving(
    tokens_saved: int,
    prefix_tokens: int,
    cache_mort_prob: float,
    touches_prefix: bool = False,
) -> int:
    """Economie nette = tokens gagnes - cout de re-prefill eventuel.

    `touches_prefix` indique si le prune modifie la zone prefixee (A/B).

    - Prune de la **zone de travail** (C/D) : gratuit. Le prefixe n'est pas
      touche, il n'y a aucun re-prefill a payer — meme si le cache est vivant.
      C'etait une erreur de le penaliser avec `prefix_tokens * prob`.
    - Prune du **prefixe** : coute un re-prefill, sauf si le cache est mort
      (fenetre TTL expiree), auquel cas il n'y a rien a re-prefill.
    """
    if not touches_prefix:
        return int(tokens_saved)
    if cache_mort_prob >= 0.9:
        return int(tokens_saved)
    return int(tokens_saved - prefix_tokens * cache_mort_prob)


def select_candidates(state, max_items: int = 20) -> list[dict[str, Any]]:
    """Payloads eligibles a l'externalisation (fichiers lus, resultats outils)."""
    out: list[dict[str, Any]] = []
    for path, entry in state.files.items():
        if entry.ref and entry.size_bytes:
            out.append(
                {
                    "kind": "file",
                    "target": path,
                    "ref": entry.ref,
                    "size_bytes": entry.size_bytes,
                    # Le contenu du fichier est deja externalise : son cout en
                    # tokens se mesure sur la taille stockee du ref, pas sur le
                    # chemin. `count_tokens(path) * 0` renvoyait toujours 0 et
                    # faussait le classement des candidats (et donc le choix
                    # des payloads a externaliser).
                    "tokens": max(0, int(entry.size_bytes) // 4),
                }
            )
    for cache_key, entry in state.tool_results.items():
        if entry.ref and entry.size_bytes:
            out.append(
                {
                    "kind": "tool_result",
                    "target": cache_key,
                    "ref": entry.ref,
                    "size_bytes": entry.size_bytes,
                    "tokens": entry.tokens,
                }
            )
    return out[:max_items]


def elapsed_since(last_ts: float | None) -> float:
    if not last_ts:
        return 0.0
    return max(0.0, time.time() - last_ts)
