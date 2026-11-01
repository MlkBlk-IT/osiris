"""Identifiants, hashes et canonicalisation.

Regle : l'agent ne calcule jamais de hash. Il transmet les arguments bruts,
OSIRIS canonicalise et digeste. L'agent paie donc zero token de calcul.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

_WS = re.compile(r"\s+")


def new_id(prefix: str) -> str:
    """Identifiant court, unique et lisible : `pfx_1a2b3c4d5e6f`."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def sha256_hex(data: bytes | str) -> str:
    """SHA-256 hexadecimal d'un contenu bytes ou str (utf-8)."""
    if isinstance(data, str):
        data = data.encode("utf-8", errors="replace")
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj: Any) -> str:
    """JSON canonique : cles triees, separateurs compacts, UTF-8 preserve."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        norm = _WS.sub(" ", value).strip()
        # normalise les separateateurs de chemin pour stabiliser les hashes
        if norm.startswith(("/", "./")) or re.match(r"^[A-Za-z]:[\\/]", norm):
            norm = norm.replace("\\", "/")
        return norm
    if isinstance(value, dict):
        return {k: _normalize_value(v) for k, v in sorted(value.items()) if v is not None}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def canonical_args(args: str | dict | None) -> str:
    """Canonicalise des arguments d'outil recues sous forme de texte JSON.

    - JSON valide -> parse, trie les cles, retire les nulls, normalise les chaines.
    - JSON invalide -> texte brut normalise (espaces compresses).
    """
    if args is None:
        return ""
    if isinstance(args, dict):
        obj: Any = args
    else:
        text = args.strip()
        if not text:
            return ""
        try:
            obj = json.loads(text)
        except (ValueError, TypeError):
            return _WS.sub(" ", text)
    return canonical_json(_normalize_value(obj))


def hash_args(args: str | dict | None) -> str:
    """Hash court et stable des arguments canoniques."""
    return sha256_hex(canonical_args(args))[:16]


def hash_text(text: str, length: int = 16) -> str:
    return sha256_hex(text)[:length]


def normalize_path(path: str | Path) -> str:
    """Chemin normalise (separateurs /, casse preservee)."""
    return str(path).replace("\\", "/")


def short_hash(full_hash: str, length: int = 16) -> str:
    """Tronque un hash pour l'affichage."""
    return full_hash[:length]
