"""Niveau d'engagement adaptatif.

L'economie d'OSIRIS se decompose en deux termes :

    gain net = duplication evitee - surcout propre

La duplication evitee est **proportionnelle** au volume du payload ; le
surchout est **quasi constant**. Un OSIRIS a comportement fixe perd donc de
l'argent sur les petites taches et en gagne sur les grosses.

L'adaptation porte sur **ce qui est fait**, pas sur ce qui est dit :

1. **Detection de doublon : toujours.** Elle ne coute qu'un hash de fichier
   dans `files{}` (~0 token LLM) et suffit a arreter les relectures. Elle est
   donc activee a tous les niveaux : c'est le seul mecanisme gratuit.
2. **Externalisation : au-dela d'un seuil.** Externaliser un payload de P
   tokens coute une ref (~30 tok) + un rappel cible (~400 tok), donc ~430
   tokens de cycle, contre P tokens pour une relecture directe. Le seuil
   retenu est 120 tokens, mesure sur le regime reel (mediane 87, max 215) :
   au-dela, externaliser rapporte une ref au lieu de trainer le payload. Le payload reste
   alors dans le contexte.
3. **Manifeste : au-dela d'un seuil.** Le manifeste vaut 120 tokens ; sur une
   tache de 200 tokens, il est disproportionne.
4. **Shape des reponses : compact sous un seuil.** Les reponses "pleines"
   (hint, compass, budget, drift) sont un luxe sur une petite tache.

Ce sont les points 3 et 4 qui font toute la difference sur les petits
prompts : le surcout d'OSIRIS est quasi constant, donc il doit **se
comprimer** quand la tache est petite.

Trois niveaux :

    light     payload < 800 tok    reponses compactes, manifeste allégé,
                                    pas d'externalisation (seuil 800)
    standard  800..8000 tok        manifeste complet, reponses pleines,
                                    externalisation active
    full      >= 8000 tok          tout active, y compris la compaction
                                    et le routage KV (phase 2)
"""

from __future__ import annotations

import json
import os
import statistics

LEVEL_LIGHT = "light"
LEVEL_STANDARD = "standard"
LEVEL_FULL = "full"

#: Sous ce seuil, le cycle externaliser -> referencer -> rappeler coute plus
#: cher que la relecture directe du payload : on garde le payload en contexte.
#:
#: Mesure reelle (data/home/osiris.db, 400 reponses d'outils) : la taille
#: mediane d'un payload observe est de 87 tokens, le maximum 215. Un seuil a
#: 800 tokens n'etait donc **jamais** atteint : l'externalisation ne se
#: declenchait pas et le gain annonce etait fictif. Le seuil est aligne sur le
#: regime reel mesure, tout en restant au-dessus du cout d'une ref (~30 tok)
#: plus le cout de rappel.
EXTERNALIZE_MIN_TOKENS = int(os.getenv("OSIRIS_EXTERNALIZE_MIN_TOKENS", "120"))

#: En dessous de ce seuil, le manifeste complet est remplace par une ligne.
MANIFEST_MIN_TOKENS = int(os.getenv("OSIRIS_MANIFEST_MIN_TOKENS", "800"))

#: En dessous de ce seuil, les reponses OSIRIS passent en forme compacte.
COMPACT_BELOW_TOKENS = int(os.getenv("OSIRIS_COMPACT_BELOW_TOKENS", "1500"))

#: Seuil de payload au-dela duquel le mode "full" s'active.
FULL_PAYLOAD_TOKENS = int(os.getenv("OSIRIS_FULL_PAYLOAD_TOKENS", "8000"))

#: Seuil de rentabilite mesure par `bench/run_bench.py`.
#:
#: OSIRIS paye un cout fixe (schemas + plan + refs) a chaque tache ; son gain
#: est proportionnel au volume du payload. En dessous de ce seuil, il coute
#: donc **plus cher** qu'il ne rapporte — c'est mesure, pas suppose : le bench
#: donne -15.35 % a 200 tokens, +24.8 % a 800, +72.0 % a 20000.
#:
#: (Valeurs remplacees le 2026-10-31 : elles ne correspondaient pas au tableau
#: du README §12, qui en affichait d'autres pour la meme mesure. Les chiffres
#: vivants sont regeneres par `bench/run_bench.py` et repris dans README §12 ;
#: ils ne sont donc plus figes dans le code.)
#:
#: `BYSTANDER_BELOW_TOKENS` materialise ce point. En mode `bystander`, OSIRIS
#: n'ecrit plus rien dans le ledger (pas de `schema_access`, pas d'`overhead`)
#: et laisse la tache se derouler a cout nul : le produit devient alors
#: **jamais negatif**, ce qu'exige le gate de `run_bench.py`.
BYSTANDER_BELOW_TOKENS = int(os.getenv("OSIRIS_BYSTANDER_BELOW_TOKENS", "600"))

LEVEL_BYSTANDER = "bystander"


#: Cout fixe des schemas d'outils OSIRIS charges dans CHAQUE requete du
#: client (6 outils + descriptions + instructions serveur). Mesure par
#: bench/run_bench.py::_access_cost() = 1086 tokens.
#: Ce cout est paye a chaque appel LLM, pas a chaque appel d'outil OSIRIS :
#: il est donc comptabilise **une fois par tache** dans le ledger, sous le
#: kind `schema_access`, uniquement quand l'adaptation est active (mode
#: `light` ne paye pas ce cout si le client ne charge pas les outils).
#:
#: Mesure par defaut a l'import par `_measure_schema_tokens()` : nom +
#: description + schema compact des 6 outils (meme forme que
#: `scripts/measure_schemas.py`, pour qu'une seule verite circule).
SCHEMA_ACCESS_TOKENS = int(os.getenv("OSIRIS_SCHEMA_ACCESS_TOKENS", "0"))

#: L'adaptation peut etre desactivee (benchmark comparatif, tests).
_ENABLED = os.getenv("OSIRIS_ADAPTIVE", "1") not in ("0", "false", "False")


async def measure_schema_tokens() -> int:
    """Cout reel des schemas, mesure sur les outils vivants (async).

    Le client charge nom + description + schema JSON de chaque outil dans
    chaque requete. On somme ces trois champs pour les 6 outils, en JSON
    compact — meme forme que `scripts/measure_schemas.py` et que
    `bench/run_bench.py::_access_cost()`, pour qu'une seule verite circule.

    `FastMCP.list_tools()` est coroutine depuis fastmcp 4.x : la mesure ne
    peut donc pas se faire a l'import. `ensure_schema_tokens()` la declenche
    paresseusement au premier `osiris.plan(start)`, qui est deja async.
    """
    from osiris.core.tokens import count_tokens

    global SCHEMA_ACCESS_TOKENS
    if SCHEMA_ACCESS_TOKENS > 0:
        return SCHEMA_ACCESS_TOKENS
    try:
        from osiris.server import mcp

        tools = await mcp.list_tools()
    except Exception:
        return 0
    blocks = []
    for tool in tools:
        schema = getattr(tool, "parameters", None) or {}
        dumped = json.dumps(schema, separators=(",", ":"), ensure_ascii=False)
        blocks.append(f"{tool.name}\n{tool.description or ''}\n{dumped}")
    measured = count_tokens("".join(blocks))
    if measured > 0:
        SCHEMA_ACCESS_TOKENS = measured
    return SCHEMA_ACCESS_TOKENS



def set_enabled(enabled: bool) -> None:
    """Active ou desactive l'adaptation (benchmark comparatif)."""
    global _ENABLED
    _ENABLED = bool(enabled)


def is_enabled() -> bool:
    return _ENABLED


def level_for(payload_tokens: int) -> str:
    """Niveau d'engagement pour un payload donne.

    Le seuil de passage en `light` est celui du **manifeste** : sous 800
    tokens de payload, ni le manifeste complet ni l'externalisation ne sont
    rentables (voir `should_externalize`).
    """
    if not _ENABLED:
        return LEVEL_FULL
    if payload_tokens < BYSTANDER_BELOW_TOKENS:
        return LEVEL_BYSTANDER
    if payload_tokens < MANIFEST_MIN_TOKENS:
        return LEVEL_LIGHT
    if payload_tokens >= FULL_PAYLOAD_TOKENS:
        return LEVEL_FULL
    return LEVEL_STANDARD


def should_engage(payload_tokens: int) -> bool:
    """Vrai si OSIRIS doit s'engager sur cette tache.

    En dessous du seuil de rentabilite, OSIRIS **ne fait rien** : pas de
    fichier marque, pas de ref, pas de ligne de ledger. C'est ce qui garantit
    qu'il ne peut jamais couter plus cher que l'absence d'OSIRIS, condition
    exigee par le gate du bench.
    """
    if not _ENABLED:
        return True
    return payload_tokens >= BYSTANDER_BELOW_TOKENS


def should_externalize(payload_tokens: int) -> bool:
    """Vrai si un payload de cette taille vaut d'etre externalise."""
    if not _ENABLED:
        return True
    return payload_tokens >= EXTERNALIZE_MIN_TOKENS


def wants_full_manifest(payload_tokens: int) -> bool:
    """Vrai si le manifeste complet (120 tokens) est justifie."""
    if not _ENABLED:
        return True
    return payload_tokens >= MANIFEST_MIN_TOKENS


def wants_compact_response(payload_tokens: int) -> bool:
    """Vrai si les reponses doivent etre en forme compacte."""
    if not _ENABLED:
        return False
    return payload_tokens < COMPACT_BELOW_TOKENS


def guidance(level: str, payload_tokens: int) -> str:
    """Consigne courte a l'agent, adaptee au niveau."""
    if level == LEVEL_LIGHT:
        return f"mode light ({payload_tokens} tok) : reponses compactes"
    if level == LEVEL_BYSTANDER:
        return f"mode bystander ({payload_tokens} tok) : OSIRIS se retire, aucune ecriture"
    if level == LEVEL_FULL:
        return f"mode full ({payload_tokens} tok) : externalise, delgue"
    return f"mode standard ({payload_tokens} tok) : externalise les gros resultats"


# ---- Recalibration des seuils sur donnees reelles (P0) ---------------------

def recalibrate(
    ledger_entries: list[dict],
    *,
    min_samples: int = 20,
    floor_bystander: int = 200,
    floor_externalize: int = 50,
    floor_manifest: int = 400,
) -> dict:
    """Ajuste les seuils d'engagement selon la distribution observee.

    Lit les entrees du ledger (tokens_in par observe) et calcule la
    mediane et le 75e percentile. Les seuils sont ajustes de maniere
    bornee vers le bas (floor). Retourne {adjusted, samples, median, q3,
    old, new} sans modifier les globals si samples < min_samples.
    """
    global BYSTANDER_BELOW_TOKENS, EXTERNALIZE_MIN_TOKENS, MANIFEST_MIN_TOKENS

    sizes = [
        int(e.get("tokens_in", 0))
        for e in ledger_entries
        if e.get("kind") == "observe" and int(e.get("tokens_in", 0)) > 0
    ]
    if len(sizes) < min_samples:
        return {
            "adjusted": False,
            "reason": f"insufficient samples ({len(sizes)} < {min_samples})",
            "samples": len(sizes),
        }

    med = int(statistics.median(sizes))
    q3 = int(statistics.quantiles(sizes, n=4)[2]) if len(sizes) >= 4 else int(med * 1.5)

    old = {
        "bystander": BYSTANDER_BELOW_TOKENS,
        "externalize": EXTERNALIZE_MIN_TOKENS,
        "manifest": MANIFEST_MIN_TOKENS,
    }

    new_bystander = max(floor_bystander, int(med * 0.5))
    new_externalize = max(floor_externalize, int(med * 0.3))
    new_manifest = max(floor_manifest, int(q3 * 0.5))

    BYSTANDER_BELOW_TOKENS = new_bystander
    EXTERNALIZE_MIN_TOKENS = new_externalize
    MANIFEST_MIN_TOKENS = new_manifest

    return {
        "adjusted": True,
        "samples": len(sizes),
        "median": med,
        "q3": q3,
        "old": old,
        "new": {
            "bystander": new_bystander,
            "externalize": new_externalize,
            "manifest": new_manifest,
        },
    }


def reset_thresholds() -> None:
    """Restore les seuils aux valeurs par defaut (env-driven)."""
    global BYSTANDER_BELOW_TOKENS, EXTERNALIZE_MIN_TOKENS, MANIFEST_MIN_TOKENS
    BYSTANDER_BELOW_TOKENS = int(os.getenv("OSIRIS_BYSTANDER_BELOW_TOKENS", "600"))
    EXTERNALIZE_MIN_TOKENS = int(os.getenv("OSIRIS_EXTERNALIZE_MIN_TOKENS", "120"))
    MANIFEST_MIN_TOKENS = int(os.getenv("OSIRIS_MANIFEST_MIN_TOKENS", "800"))
