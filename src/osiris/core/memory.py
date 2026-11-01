"""Memoire typee et adressable (`MemoryStore`).

Un registre, pas un moteur vectoriel. Chaque entree a un `kind` explicite,
un `scope` et un identifiant stable. On interroge par type, par scope, par
cle — jamais par similarite.
"""

from __future__ import annotations

import json
import time
from typing import Any

from osiris.core.db import get_conn
from osiris.core.ids import new_id

#: Kinds de memoire supportes.
KINDS = (
    "decision",
    "constraint",
    "lesson",
    "failure",
    "note",
    "invariant",
    "file",
    "tool_result",
    "handoff",
)

#: Scopes de memoire.
SCOPES = ("task", "project", "agent", "global")


def add(
    task_id: str | None,
    kind: str,
    body: str,
    scope: str = "task",
    pinned: bool = False,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ajoute une entree de memoire et renvoie son identifiant."""
    if kind not in KINDS:
        kind = "note"
    if scope not in SCOPES:
        scope = "task"
    conn = get_conn()
    mem_id = new_id("m")
    ts = time.time()
    row = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM memory").fetchone()
    seq = int(row["n"])
    conn.execute(
        "INSERT INTO memory (mem_id, task_id, scope, kind, body, pinned, meta_json,"
        " created_at, seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            mem_id,
            task_id,
            scope,
            kind,
            body,
            1 if pinned else 0,
            json.dumps(meta or {}, ensure_ascii=False),
            ts,
            seq,
        ),
    )
    return {
        "mem_id": mem_id,
        "kind": kind,
        "scope": scope,
        "pinned": pinned,
        "body": body,
        "created_at": ts,
    }


def list_entries(
    task_id: str | None = None,
    scope: str | None = None,
    kind: str | None = None,
    query: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Liste les entrees de memoire selon les filtres."""
    sql = "SELECT * FROM memory WHERE 1=1"
    params: list[Any] = []
    if task_id:
        sql += " AND (task_id = ? OR scope IN ('project', 'agent', 'global'))"
        params.append(task_id)
    if scope:
        sql += " AND scope = ?"
        params.append(scope)
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY seq ASC LIMIT ?"
    params.append(limit)

    rows = get_conn().execute(sql, params).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        if query:
            needle = query.lower()
            haystack = f"{row['kind']} {row['body']}".lower()
            if needle not in haystack:
                continue
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except ValueError:
            meta = {}
        out.append(
            {
                "mem_id": row["mem_id"],
                "task_id": row["task_id"],
                "scope": row["scope"],
                "kind": row["kind"],
                "body": row["body"],
                "pinned": bool(row["pinned"]),
                "meta": meta,
                "created_at": row["created_at"],
            }
        )
    return out


def pinned_entries(task_id: str | None = None) -> list[dict[str, Any]]:
    """Entrees epinglees : elles sont reinjectees verbatim, jamais resumees."""
    conn = get_conn()
    sql = "SELECT * FROM memory WHERE pinned = 1"
    params: list[Any] = []
    if task_id:
        sql += " AND (task_id = ? OR scope IN ('project', 'agent', 'global'))"
        params.append(task_id)
    sql += " ORDER BY seq ASC"
    rows = conn.execute(sql, params).fetchall()
    out = []
    for row in rows:
        out.append(
            {
                "mem_id": row["mem_id"],
                "scope": row["scope"],
                "kind": row["kind"],
                "body": row["body"],
                "created_at": row["created_at"],
            }
        )
    return out


def get(mem_id: str) -> dict[str, Any] | None:
    row = get_conn().execute("SELECT * FROM memory WHERE mem_id = ?", (mem_id,)).fetchone()
    if row is None:
        return None
    return {
        "mem_id": row["mem_id"],
        "task_id": row["task_id"],
        "scope": row["scope"],
        "kind": row["kind"],
        "body": row["body"],
        "pinned": bool(row["pinned"]),
        "created_at": row["created_at"],
    }
