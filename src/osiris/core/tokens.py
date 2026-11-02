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


# ---- Calibration et intervalle de confiance (P2) ---------------------------

_calibration_ratio = 1.0
_samples = 0


def update_calibration(text: str) -> float:
    """Mesure le ratio tiktoken/heuristic sur un echantillon et l'accumule.

    Retourne le ratio courant. Quand tiktoken est disponible, on compare
    le compte exact au ceil(chars/4). Sans tiktoken, le ratio reste 1.0.
    """
    global _calibration_ratio, _samples
    enc = _load_encoder()
    if enc is None or not text:
        return _calibration_ratio
    try:
        exact = len(enc.encode(text, disallowed_special=()))
    except Exception:
        return _calibration_ratio
    heuristic = max(1, math.ceil(len(text) / 4))
    if heuristic > 0:
        ratio = exact / heuristic
        _samples += 1
        _calibration_ratio = (_calibration_ratio * (_samples - 1) + ratio) / _samples
    return _calibration_ratio


def calibration_factor() -> float:
    """Facteur de calibration courant (1.0 = heuristique exacte)."""
    return _calibration_ratio


def count_tokens_with_confidence(text: str) -> tuple[int, int, int]:
    """Estimation avec intervalle de confiance [low, estimate, high].

    Sans tiktoken, l'heuristique chars/4 a une variance d'environ 15%.
    L'intervalle reflete cette variance. Le facteur de calibration,
    quand il est disponible, resserre le point central.
    """
    if not text:
        return (0, 0, 0)
    enc = _load_encoder()
    if enc is not None:
        try:
            exact = len(enc.encode(text, disallowed_special=()))
            return (exact, exact, exact)
        except Exception:
            pass
    point = max(1, math.ceil(len(text) / 4))
    if abs(_calibration_ratio - 1.0) > 0.01:
        point = max(1, round(point * _calibration_ratio))
    variance = max(1, round(point * 0.15))
    return (point - variance, point, point + variance)
