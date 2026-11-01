"""Journal append-only et checkpoints (`RecoveryJournal`).

Chaque action d'outil produit deux evenements : `begin` puis `result`.
- `begin` sans `result` => action d'etat **unknown** (crash) -> verifier,
  ne jamais rejouer a l'aveugle.
- `begin` + `result(succeeded)` => action resolue -> skip au resume.
- `begin` + `result(failed)` => action echouee -> retry autorise.

Le journal est la source de verite : checkpoints, audit LOSSLESS et reprise
s'en derivent tous.
"""

from __future__ import annotations

import json
import time
from typing import Any

from osiris.core.db import get_conn
from osiris.core.ids import sha256_hex

#: Etats possibles d'une action.
STATE_BEGIN = "begin"
STATE_SUCCEEDED = "succeeded"
STATE_FAILED = "failed"
STATE_UNKNOWN = "unknown"


def append(
    task_id: str,
    kind: str,
    payload: dict[str, Any] | None = None,
    run_key: str | None = None,
    action_state: str | None = None,
) -> int:
    """Ajoute un evenement au journal. Retourne son numero de sequence."""
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO events (task_id, ts, kind, action_state, run_key, payload_json)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            task_id,
            time.time(),
            kind,
            action_state,
            run_key,
            json.dumps(payload or {}, ensure_ascii=False, default=str),
        ),
    )
    return int(cur.lastrowid or 0)


def make_run_key(tool: str, args: str | None, state_version: str = "") -> str:
    """Cle d'idempotence d'une action."""
    return sha256_hex(f"{tool}|{args or ''}|{state_version}")[:16]


def begin_action(
    task_id: str, tool: str, args: str | None, run_key: str | None = None
) -> dict[str, Any]:
    """Ouvre une action. Renvoie le `run_key` et la sequence."""
    key = run_key or make_run_key(tool, args)
    seq = append(
        task_id,
        "action",
        {"tool": tool, "args": args or ""},
        run_key=key,
        action_state=STATE_BEGIN,
    )
    return {"run_key": key, "seq": seq}


def end_action(
    task_id: str,
    run_key: str,
    state: str,
    payload: dict[str, Any] | None = None,
) -> int:
    """Cloture une action (succeeded / failed)."""
    return append(
        task_id,
        "action",
        payload or {},
        run_key=run_key,
        action_state=state,
    )


def open_actions(task_id: str) -> list[dict[str, Any]]:
    """Actions begun sans resultat : etat `unknown` a verifier au resume."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT seq, ts, kind, run_key, payload_json FROM events"
        " WHERE task_id = ? AND action_state = ? ORDER BY seq ASC",
        (task_id, STATE_BEGIN),
    ).fetchall()
    closed = {
        r["run_key"]
        for r in conn.execute(
            "SELECT DISTINCT run_key FROM events WHERE task_id = ? AND action_state IN (?, ?)",
            (task_id, STATE_SUCCEEDED, STATE_FAILED),
        ).fetchall()
        if r["run_key"]
    }
    out = []
    for row in rows:
        if row["run_key"] in closed:
            continue
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except ValueError:
            payload = {}
        out.append(
            {
                "seq": row["seq"],
                "ts": row["ts"],
                "run_key": row["run_key"],
                "tool": payload.get("tool", ""),
                "args": payload.get("args", ""),
                "state": STATE_UNKNOWN,
            }
        )
    return out


def completed_actions(task_id: str) -> list[dict[str, Any]]:
    """Actions resolues (succeeded) — a skip au resume."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT seq, ts, run_key, payload_json FROM events"
        " WHERE task_id = ? AND action_state = ? ORDER BY seq ASC",
        (task_id, STATE_SUCCEEDED),
    ).fetchall()
    out = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except ValueError:
            payload = {}
        out.append(
            {
                "seq": row["seq"],
                "run_key": row["run_key"],
                "tool": payload.get("tool", ""),
                "args": payload.get("args", ""),
            }
        )
    return out


def last_turn_ts(task_id: str) -> float | None:
    """Horodatage du dernier tour observe (base du delai de cache).

    C'est cette mesure qui manquait : le TTL du prefix cache etait compare a
    un `elapsed_since_last_turn_s=0.0` code en dur, donc le prune du prefixe
    ne pouvait jamais se declencher.
    """
    row = (
        get_conn()
        .execute(
            "SELECT MAX(ts) AS ts FROM events WHERE task_id = ?"
            " AND kind IN ('observe', 'action', 'prefix')",
            (task_id,),
        )
        .fetchone()
    )
    if row is None or row["ts"] is None:
        return None
    return float(row["ts"])


def history(task_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Historique des evenements (plus recents d'abord)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT seq, ts, kind, action_state, run_key, payload_json FROM events"
        " WHERE task_id = ? ORDER BY seq DESC LIMIT ?",
        (task_id, limit),
    ).fetchall()
    out = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except ValueError:
            payload = {}
        out.append(
            {
                "seq": row["seq"],
                "ts": row["ts"],
                "kind": row["kind"],
                "action_state": row["action_state"],
                "run_key": row["run_key"],
                "payload": payload,
            }
        )
    return out


# -- checkpoints ------------------------------------------------------------


def save_checkpoint(task_id: str, label: str, state: dict[str, Any]) -> dict[str, Any]:
    """Materielise un snapshot de l'etat + l'offset du journal."""
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) AS off FROM events WHERE task_id = ?", (task_id,)
    ).fetchone()
    offset = int(row["off"])
    checkpoint_id = f"ckpt://{task_id}/{offset}"
    conn.execute(
        "INSERT OR REPLACE INTO checkpoints (checkpoint_id, task_id, journal_offset, label,"
        " state_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            checkpoint_id,
            task_id,
            offset,
            label,
            json.dumps(state, ensure_ascii=False, default=str),
            time.time(),
        ),
    )
    return {
        "checkpoint_id": checkpoint_id,
        "journal_offset": offset,
        "label": label,
        "created_at": time.time(),
    }


def list_checkpoints(task_id: str) -> list[dict[str, Any]]:
    rows = (
        get_conn()
        .execute(
            "SELECT checkpoint_id, journal_offset, label, created_at FROM checkpoints"
            " WHERE task_id = ? ORDER BY journal_offset DESC",
            (task_id,),
        )
        .fetchall()
    )
    return [
        {
            "checkpoint_id": r["checkpoint_id"],
            "journal_offset": r["journal_offset"],
            "label": r["label"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def get_checkpoint(checkpoint_id: str) -> dict[str, Any] | None:
    row = (
        get_conn()
        .execute("SELECT * FROM checkpoints WHERE checkpoint_id = ?", (checkpoint_id,))
        .fetchone()
    )
    if row is None:
        return None
    try:
        state = json.loads(row["state_json"] or "{}")
    except ValueError:
        state = {}
    return {
        "checkpoint_id": row["checkpoint_id"],
        "task_id": row["task_id"],
        "journal_offset": row["journal_offset"],
        "label": row["label"],
        "state": state,
        "created_at": row["created_at"],
    }


def latest_checkpoint(task_id: str) -> dict[str, Any] | None:
    rows = list_checkpoints(task_id)
    return rows[0] if rows else None
