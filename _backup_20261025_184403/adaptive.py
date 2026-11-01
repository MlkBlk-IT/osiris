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
   retenu est 800 tokens : sous ce seuil, le cycle externaliser -> referencer
   -> rappeler coute **plus cher** que la relecture directe. Le payload reste
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

import os

LEVEL_LIGHT = "light"
LEVEL_STANDARD = "standard"
LEVEL_FULL = "full"

#: Sous ce seuil, le cycle externaliser -> referencer -> rappeler coute plus
#: cher que la relecture directe du payload : on garde le payload en contexte.
EXTERNALIZE_MIN_TOKENS = int(os.getenv("OSIRIS_EXTERNALIZE_MIN_TOKENS", "800"))

#: En dessous de ce seuil, le manifeste complet est remplace par une ligne.
MANIFEST_MIN_TOKENS = int(os.getenv("OSIRIS_MANIFEST_MIN_TOKENS", "800"))

#: En dessous de ce seuil, les reponses OSIRIS passent en forme compacte.
COMPACT_BELOW_TOKENS = int(os.getenv("OSIRIS_COMPACT_BELOW_TOKENS", "1500"))

#: Seuil de payload au-dela duquel le mode "full" s'active.
FULL_PAYLOAD_TOKENS = int(os.getenv("OSIRIS_FULL_PAYLOAD_TOKENS", "8000"))

#: L'adaptation peut etre desactivee (benchmark comparatif, tests).
_ENABLED = os.getenv("OSIRIS_ADAPTIVE", "1") not in ("0", "false", "False")


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
    if payload_tokens < MANIFEST_MIN_TOKENS:
        return LEVEL_LIGHT
    if payload_tokens >= FULL_PAYLOAD_TOKENS:
        return LEVEL_FULL
    return LEVEL_STANDARD


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
    if level == LEVEL_FULL:
        return f"mode full ({payload_tokens} tok) : externalise, delgue"
    return f"mode standard ({payload_tokens} tok) : externalise les gros resultats"
