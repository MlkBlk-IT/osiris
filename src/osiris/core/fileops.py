"""Operations filesystem sandboxees.

OSIRIS lit des fichiers pour les hasher et les externaliser. Cette surface
est donc reellement attaquable : racines autorisees, taille maximale,
resolution de liens, lecture tolerante aux erreurs d'encodage.

OSIRIS n'ecrit **jamais** dans les fichiers de l'agent.
"""

from __future__ import annotations

import os
from pathlib import Path

from osiris.config import settings
from osiris.core.errors import AccessDenied


def resolve_allowed(path_str: str) -> Path:
    """Resout un chemin et verifie qu'il est sous une racine autorisee."""
    if not path_str or not path_str.strip():
        raise AccessDenied("chemin vide")
    raw = path_str.strip().strip('"').strip("'")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        resolved = candidate.resolve()
    except OSError as exc:  # pragma: no cover - depend du FS
        raise AccessDenied(f"chemin illisible: {raw}") from exc

    if not settings.is_path_allowed(resolved):
        raise AccessDenied(
            f"chemin hors racine autorisee: {resolved} "
            f"(racines: {', '.join(str(r) for r in settings.allowed_roots)})"
        )
    return resolved


def read_text(path_str: str, max_bytes: int | None = None) -> dict[str, object]:
    """Lit un fichier de maniere sandboxee.

    Returns:
        {"path", "content", "size_bytes", "mtime", "sha256", "truncated"}
    """
    from osiris.core.ids import sha256_hex

    limit = max_bytes if max_bytes is not None else settings.max_file_bytes
    resolved = resolve_allowed(path_str)
    if not resolved.is_file():
        raise AccessDenied(f"pas un fichier: {resolved}")

    size = resolved.stat().st_size
    mtime = resolved.stat().st_mtime
    if size > limit:
        raise AccessDenied(
            f"fichier trop volumineux ({size} octets > {limit}) ; hash seul possible"
        )

    raw = resolved.read_bytes()
    content = raw.decode("utf-8", errors="replace")
    return {
        "path": str(resolved),
        "content": content,
        "size_bytes": len(raw),
        "mtime": mtime,
        "sha256": sha256_hex(content),
        "truncated": False,
    }


def stat_file(path_str: str) -> dict[str, object]:
    """Statistiques d'un fichier sans le lire (hash impossible sans lecture)."""
    resolved = resolve_allowed(path_str)
    if not resolved.is_file():
        raise AccessDenied(f"pas un fichier: {resolved}")
    st = resolved.stat()
    return {
        "path": str(resolved),
        "size_bytes": st.st_size,
        "mtime": st.st_mtime,
    }


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def atomic_write(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Ecriture atomique (utilisee uniquement pour les rapports OSIRIS)."""
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding=encoding)
    os.replace(tmp, path)
