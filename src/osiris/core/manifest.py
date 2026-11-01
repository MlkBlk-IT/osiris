"""Manifeste scelle.

Petit bloc deterministe (100-150 tokens) que l'agent insere a position fixe
dans son contexte. Il porte le `SEAL` : le hash des zones stables.

Le manifeste est le **support passif** d'OSIRIS : meme si l'agent n'appelle
plus aucun outil, il transporte deja l'essentiel de l'etat utile.
"""

from __future__ import annotations

from osiris.core.ids import sha256_hex

MANIFEST_VERSION = "OSIRIS/1"
MAX_OBJECTIVE_CHARS = 64


def _escape(value: str) -> str:
    return (value or "").replace("\\", "/").replace('"', "'").replace("\n", " ").strip()


def _truncate(value: str, limit: int) -> str:
    value = value or ""
    return value if len(value) <= limit else value[: limit - 1] + "…"


def build_manifest(
    task_id: str,
    objective: str,
    plan_current: int,
    plan_total: int,
    invariants_count: int,
    files_count: int,
    refs_count: int,
    budget_ok: bool,
    zones: dict[str, str],
    decisions_count: int = 0,
    extra: str = "",
) -> dict[str, str]:
    """Construit le manifeste et son seal.

    Returns:
        {"manifest": <texte>, "seal": <hash>}
    """
    head = (
        f"{MANIFEST_VERSION} task={task_id}"
        f' obj="{_truncate(_escape(objective), MAX_OBJECTIVE_CHARS)}"'
        f" plan={plan_current}/{plan_total}"
    )
    mid = (
        f"inv={invariants_count} files={files_count} refs={refs_count}"
        f" dec={decisions_count} budget={'ok' if budget_ok else 'over'}"
    )
    seal = zones.get("prefix_hash") or sha256_hex(head + mid)
    lines = [head, mid]
    if extra:
        lines.append(extra)
    lines.append(f"SEAL=sha256:{seal}")
    return {"manifest": "\n".join(lines), "seal": f"sha256:{seal}"}


def parse_seal(text: str) -> str | None:
    """Extrait le seal d'un manifeste."""
    if not text:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("SEAL="):
            return line[len("SEAL=") :].strip()
    return None
