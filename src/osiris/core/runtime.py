"""Runtime OSIRIS — facade d'etat utilisee par le serveur MCP.

Gere le cycle de vie des taches, la persistance de l'etat, et le pointeur
vers la tache courante (persiste sur disque pour survivre a un redemarrage
du serveur MCP entre deux sessions).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from osiris.config import settings
from osiris.core.db import get_conn
from osiris.core.ids import new_id
from osiris.core.task_state import TaskState


def _pointer_path() -> Path:
    return settings.home / "current_task"


def current_task_id() -> str | None:
    """Identifiant de la tache courante, ou None."""
    path = _pointer_path()
    try:
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            return value or None
    except OSError:
        return None
    return None


def set_current_task(task_id: str) -> None:
    settings.ensure_dirs()
    _pointer_path().write_text(task_id, encoding="utf-8")


def clear_current_task() -> None:
    path = _pointer_path()
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def save_task(state: TaskState) -> TaskState:
    """Persiste l'etat de la tache."""
    state.updated_at = time.time()
    get_conn().execute(
        "INSERT OR REPLACE INTO tasks (task_id, created_at, updated_at, state_json)"
        " VALUES (?, ?, ?, ?)",
        (state.task_id, state.created_at, state.updated_at, state.dumps()),
    )
    return state


def get_task(task_id: str | None = None) -> TaskState | None:
    """Charge une tache (par identifiant, ou la tache courante)."""
    tid = task_id or current_task_id()
    if not tid:
        return None
    row = get_conn().execute("SELECT state_json FROM tasks WHERE task_id = ?", (tid,)).fetchone()
    if row is None:
        if task_id is None:
            clear_current_task()
        return None
    try:
        return TaskState.loads(row["state_json"])
    except (ValueError, KeyError):
        return None


def list_tasks(limit: int = 50) -> list[dict[str, Any]]:
    """Liste les taches recentes."""
    rows = (
        get_conn()
        .execute(
            "SELECT task_id, created_at, updated_at, state_json FROM tasks"
            " ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        .fetchall()
    )
    out = []
    for row in rows:
        try:
            state = json.loads(row["state_json"])
        except ValueError:
            state = {}
        out.append(
            {
                "task_id": row["task_id"],
                "objective": state.get("objective", ""),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return out


def create_task(
    objective: str = "",
    steps: list[str] | None = None,
    constraints: list[str] | None = None,
    budget: dict[str, Any] | None = None,
) -> TaskState:
    """Cree une nouvelle tache."""
    from osiris.core.task_state import BudgetState, Plan

    state = TaskState(
        task_id=new_id("t"),
        objective=(objective or "").strip(),
        plan=Plan(steps=list(steps or [])),
    )
    for constraint in constraints or []:
        state.add_constraint(constraint)
    if budget:
        state.budget = BudgetState(
            max_tokens=int(budget.get("max_tokens", state.budget.max_tokens)),
            max_cost_usd=float(budget.get("max_cost_usd", state.budget.max_cost_usd)),
            max_tool_calls=int(budget.get("max_tool_calls", state.budget.max_tool_calls)),
        )
    save_task(state)
    set_current_task(state.task_id)
    return state


def ensure_task(task_id: str | None = None) -> TaskState:
    """Retourne la tache demandee, ou en cree une implicite."""
    state = get_task(task_id)
    if state is not None:
        return state
    if task_id:
        state = TaskState(task_id=task_id)
        save_task(state)
        set_current_task(task_id)
        return state
    return create_task(objective="tache implicite")


def bump_tool_usage(task_id: str, tool: str) -> int:
    """Compte les appels d'outils par tache et par outil."""
    conn = get_conn()
    now = time.time()
    row = conn.execute(
        "SELECT calls FROM tool_usage WHERE task_id = ? AND tool = ?", (task_id, tool)
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO tool_usage (task_id, tool, calls, last_at) VALUES (?, ?, 1, ?)",
            (task_id, tool, now),
        )
        return 1
    calls = int(row["calls"]) + 1
    conn.execute(
        "UPDATE tool_usage SET calls = ?, last_at = ? WHERE task_id = ? AND tool = ?",
        (calls, now, task_id, tool),
    )
    return calls


def tool_calls(task_id: str) -> int:
    row = (
        get_conn()
        .execute(
            "SELECT COALESCE(SUM(calls), 0) AS n FROM tool_usage WHERE task_id = ?", (task_id,)
        )
        .fetchone()
    )
    return int(row["n"])


def tool_usage(task_id: str) -> dict[str, int]:
    rows = (
        get_conn()
        .execute(
            "SELECT tool, calls FROM tool_usage WHERE task_id = ? ORDER BY calls DESC", (task_id,)
        )
        .fetchall()
    )
    return {r["tool"]: int(r["calls"]) for r in rows}


def known_tools(task_id: str | None = None) -> list[str]:
    """Outils observes dans cette tache (base du Tool Compass)."""
    if not task_id:
        return []
    return list(tool_usage(task_id).keys())
