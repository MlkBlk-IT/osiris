"""Store de refs content-addressed.

Invariant structurale : une ref contient le hash de son contenu.
`mem://sha256:<hash>` — la lecture verifie le hash AVANT de renvoyer le
contenu. Toute divergence est signalee, jamais silencieuse.

La redaction precede le hash : le hash porte sur la version **stockee**.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from osiris.core.db import get_conn
from osiris.core.errors import IntegrityError
from osiris.core.ids import sha256_hex
from osiris.core.redact import redact_text
from osiris.core.tokens import count_tokens

REF_PREFIX = "mem://sha256:"


def make_ref(content_hash: str) -> str:
    return f"{REF_PREFIX}{content_hash}"


def parse_ref(ref: str) -> str | None:
    """Extrait le hash d'une ref, ou None si la ref est malformee."""
    if not ref.startswith(REF_PREFIX):
        return None
    digest = ref[len(REF_PREFIX) :].strip()
    return digest if re.fullmatch(r"[0-9a-f]{64}", digest) else None


def put(
    task_id: str | None,
    content: str,
    meta: dict[str, Any] | None = None,
    ttl: float = 0.0,
    redact: bool = True,
) -> dict[str, Any]:
    """Externalise un payload et renvoie sa ref auto-verifiable."""
    stored = content
    redactions = 0
    if redact:
        stored, redactions = redact_text(content)

    digest = sha256_hex(stored)
    ref = make_ref(digest)
    now = time.time()
    expires_at = (now + ttl) if ttl and ttl > 0 else None

    conn = get_conn()
    row = conn.execute("SELECT ref, created_at FROM refs WHERE ref = ?", (ref,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO refs (ref, task_id, content_hash, size_bytes, content, meta_json,"
            " redactions, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ref,
                task_id,
                digest,
                len(stored.encode("utf-8")),
                stored,
                json.dumps(meta or {}, ensure_ascii=False),
                redactions,
                now,
                expires_at,
            ),
        )
    return {
        "ref": ref,
        "content_hash": digest,
        "size_bytes": len(stored.encode("utf-8")),
        "tokens": count_tokens(stored),
        "redactions": redactions,
        "meta": meta or {},
    }


def get(ref: str, strict: bool = False) -> dict[str, Any] | None:
    """Recupere un payload et **verifie son integrite**."""
    digest = parse_ref(ref)
    if digest is None:
        return None
    row = get_conn().execute("SELECT * FROM refs WHERE ref = ?", (ref,)).fetchone()
    if row is None:
        return None

    content = row["content"]
    verified = sha256_hex(content) == digest == row["content_hash"]
    if not verified and strict:
        raise IntegrityError(f"integrite rompue pour {ref}")

    try:
        meta = json.loads(row["meta_json"] or "{}")
    except ValueError:
        meta = {}

    expired = row["expires_at"] is not None and row["expires_at"] < time.time()
    return {
        "ref": ref,
        "content": content,
        "verified": verified,
        "expired": expired,
        "size_bytes": row["size_bytes"],
        "tokens": count_tokens(content),
        "redactions": row["redactions"],
        "meta": meta,
        "created_at": row["created_at"],
    }


def verify(ref: str) -> bool:
    """Vrai si le contenu stocke correspond toujours a sa ref."""
    entry = get(ref)
    return bool(entry and entry["verified"])


def exists(ref: str) -> bool:
    row = get_conn().execute("SELECT 1 FROM refs WHERE ref = ?", (ref,)).fetchone()
    return row is not None


def _match_positions(text: str, query: str) -> list[int]:
    terms = [t for t in re.split(r"\s+", query.strip().lower()) if len(t) >= 2]
    if not terms:
        return []
    lowered = text.lower()
    positions: list[int] = []
    for term in terms:
        start = 0
        while True:
            idx = lowered.find(term, start)
            if idx == -1:
                break
            positions.append(idx)
            start = idx + len(term)
    return sorted(positions)


def _best_window(text: str, positions: list[int], window: int) -> int:
    """Choisit la fenetre de taille `window` contenant le plus de correspondances."""
    if not positions:
        return 0
    best_start = positions[0]
    best_count = -1
    for start in positions:
        count = sum(1 for p in positions if start <= p < start + window)
        if count > best_count:
            best_count = count
            best_start = start
            if count == len(positions):
                break
    return best_start


def excerpt(ref: str, query: str = "", budget_tokens: int = 0) -> dict[str, Any]:
    """Extrait cible d'un payload stocke.

    Sans `query` : contenu complet (tronque si un budget est donne).
    Avec `query`  : fenetre la plus dense autour des correspondances.

    C'est ce qui rend l'externalisation rentable : rappeler un extrait coute
    quelques centaines de tokens au lieu de plusieurs milliers.
    """
    entry = get(ref)
    if entry is None:
        return {"found": False, "ref": ref}
    content = entry["content"]
    total_chars = len(content)
    budget_chars = budget_tokens * 4 if budget_tokens and budget_tokens > 0 else 0

    if not query:
        if budget_chars and total_chars > budget_chars:
            return {
                "found": True,
                "ref": ref,
                "excerpt": content[:budget_chars],
                "offset": 0,
                "complete": False,
                "total_chars": total_chars,
                "tokens": count_tokens(content[:budget_chars]),
                "verified": entry["verified"],
            }
        return {
            "found": True,
            "ref": ref,
            "excerpt": content,
            "offset": 0,
            "complete": True,
            "total_chars": total_chars,
            "tokens": entry["tokens"],
            "verified": entry["verified"],
        }

    positions = _match_positions(content, query)
    if not positions:
        return {
            "found": True,
            "ref": ref,
            "excerpt": content[:budget_chars] if budget_chars else "",
            "offset": 0,
            "complete": False,
            "total_chars": total_chars,
            "tokens": count_tokens(content[:budget_chars]) if budget_chars else 0,
            "verified": entry["verified"],
            "note": "no_match",
        }

    window = budget_chars or max(200, min(total_chars, 1200))
    start = _best_window(content, positions, window)
    start = max(0, min(start, max(0, total_chars - window)))
    chunk = content[start : start + window]
    return {
        "found": True,
        "ref": ref,
        "excerpt": chunk,
        "offset": start,
        "complete": start == 0 and len(chunk) >= total_chars,
        "total_chars": total_chars,
        "tokens": count_tokens(chunk),
        "verified": entry["verified"],
        "matches": len(positions),
    }


def list_refs(task_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """Liste les refs stockees (pour l'audit de non-perte)."""
    sql = "SELECT ref, task_id, content_hash, size_bytes, redactions, created_at FROM refs"
    params: list[Any] = []
    if task_id:
        sql += " WHERE task_id = ?"
        params.append(task_id)
    sql += " ORDER BY created_at ASC LIMIT ?"
    params.append(limit)
    rows = get_conn().execute(sql, params).fetchall()
    return [
        {
            "ref": r["ref"],
            "task_id": r["task_id"],
            "content_hash": r["content_hash"],
            "size_bytes": r["size_bytes"],
            "redactions": r["redactions"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def prune_expired(max_age_s: float = 0, only_unaccessed: bool = True) -> dict[str, Any]:
    """Supprime les refs expirees (TTL passe) et optionnellement jamais relues.

    Invariant de securite : ne supprime que les refs dont le createur a
    explicitement fixe un TTL (expires_at IS NOT NULL) ET qui sont expirees.
    Si only_unaccessed=True, ne supprime que les refs qui n'ont aucune
    trace de recall dans les evenements.

    Retourne {removed, remaining, bytes_freed}.
    """
    conn = get_conn()
    now = time.time()

    sql = (
        "SELECT ref, size_bytes, created_at, expires_at FROM refs"
        " WHERE expires_at IS NOT NULL AND expires_at < ?"
    )
    params: list[Any] = [now]
    if max_age_s > 0:
        sql += " AND created_at < ?"
        params.append(now - max_age_s)

    rows = conn.execute(sql, params).fetchall()
    removed = 0
    bytes_freed = 0

    for row in rows:
        if only_unaccessed:
            access = conn.execute(
                "SELECT 1 FROM events WHERE kind = 'recall'"
                " AND payload_json LIKE ? LIMIT 1",
                (f'%{row["ref"]}%',),
            ).fetchone()
            if access is not None:
                continue

        conn.execute("DELETE FROM refs WHERE ref = ?", (row["ref"],))
        removed += 1
        bytes_freed += int(row["size_bytes"])

    remaining = conn.execute("SELECT COUNT(*) AS n FROM refs").fetchone()["n"]
    return {
        "removed": removed,
        "remaining": int(remaining),
        "bytes_freed": bytes_freed,
    }
