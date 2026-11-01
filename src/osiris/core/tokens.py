"""Estimation de tokens.

Le compteur est *pluggable* et degrade proprement : si aucun compteur n'est
disponible, on retombe sur une approximation caracteres/4. Toute valeur
produite ici est une **estimation**, jamais une mesure provider.
"""

from __future__ import annotations

import math
from functools import lru_cache

_ENCODER_NAME = "heuristic"
_ENCODER = None


@lru_cache(maxsize=1)
def _load_encoder():
    """Charge l'encodeur une seule fois. Retourne None si indisponible."""
    global _ENCODER_NAME
    try:
        import tiktoken  # type: ignore

        enc = tiktoken.get_encoding("cl100k_base")
        _ENCODER_NAME = "tiktoken/cl100k_base"
        return enc
    except Exception:
        _ENCODER_NAME = "heuristic"
        return None


def estimator_name() -> str:
    """Nom du compteur effectivement utilise."""
    _load_encoder()
    return _ENCODER_NAME


def count_tokens(text: str) -> int:
    """Nombre de tokens estime pour `text`."""
    if not text:
        return 0
    enc = _load_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text, disallowed_special=()))
        except Exception:
            pass
    return max(1, math.ceil(len(text) / 4))


def estimate_tokens(text: str) -> int:
    """Alias explicite : toute valeur issue du compteur est une estimation."""
    return count_tokens(text)


def chars_to_tokens(chars: int) -> int:
    """Conversion caracteres -> tokens pour l'heuristique de fenetrage."""
    return max(1, math.ceil(chars / 4))
