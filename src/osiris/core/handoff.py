"""`HandoffStore` — contrats de delegation entre agents.

Un handoff n'est pas un extrait de contexte : c'est un **contrat** minimal
et **executable** (tools autorisees, actions interdites, budget), accompagne
de refs que le sous-agent rappellera a la demande.
"""

from __future__ import annotations

import json
import time
from typing import Any

from osiris.core.db import get_conn
from osiris.core.ids import new_id
from osiris.core.task_state import TaskState

STATUS_OPEN = "open"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


def create(
    parent_task_id: str,
    mission: str,
    must_know: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    forbidden_actions: list[str] | None = None,
    files: list[str] | None = None,
    budget_tokens: int = 0,
    expires_at: float | None = None,
    context_refs: list[str] | None = None,
    state: TaskState | None = None,
) -> dict[str, Any]:
    """Cree un contrat de handoff et renvoie son identifiant."""
    handoff_id = new_id("h")
    must_know = list(must_know or [])
    allowed = list(allowed_tools or [])
    forbidden = list(forbidden_actions or [])
    files = list(files or [])

    refs = list(context_refs or [])
    if state is not None:
        # les fichiers deja lus par le parent deviennent des refs :
        # le sous-agent rappelle ce dont il a besoin au lieu de recoller le contenu.
        for path in files:
            entry = state.files.get(path)
            if entry and entry.ref and entry.ref not in refs:
                refs.append(entry.ref)

    contract = {
        "handoff_id": handoff_id,
        "mission": mission,
        "must_know": must_know,
        "allowed_tools": allowed,
        "forbidden_actions": forbidden,
        "files": files,
        "budget": {"tokens": int(budget_tokens)},
        "expires_at": expires_at or (time.time() + 3600),
        "context_refs": refs,
    }

    get_conn().execute(
        "INSERT INTO handoffs (handoff_id, task_id, parent_task_id, contract_json, status,"
        " result_json, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            handoff_id,
            handoff_id,
            parent_task_id,
            json.dumps(contract, ensure_ascii=False, default=str),
            STATUS_OPEN,
            None,
            time.time(),
            contract["expires_at"],
        ),
    )
    return {
        "handoff_id": handoff_id,
        "contract": contract,
        "contract_text": _render(contract),
        "context_refs": refs,
        "estimated_tokens": _estimate(contract),
    }


def _render(contract: dict[str, Any]) -> str:
    """Rendu compact et deterministe du contrat (transporte par l'agent)."""
    lines = [
        f"HANDOFF/1 id={contract['handoff_id']}",
        f"mission={contract['mission']}",
    ]
    if contract.get("must_know"):
        lines.append("must_know=" + " | ".join(contract["must_know"]))
    if contract.get("allowed_tools"):
        lines.append("allowed=" + ",".join(contract["allowed_tools"]))
    if contract.get("forbidden_actions"):
        lines.append("forbidden=" + ",".join(contract["forbidden_actions"]))
    # Les fichiers sont nommes : sans ca, le sous-agent ne sait pas quoi lire.
    # (Quand une ref existe, elle porte le contenu ; le chemin dit de quoi.)
    if contract.get("files"):
        lines.append("files=" + " | ".join(contract["files"]))
    if contract.get("context_refs"):
        lines.append("refs=" + ",".join(contract["context_refs"]))
    lines.append(f"budget_tokens={contract.get('budget', {}).get('tokens', 0)}")
    return "\n".join(lines)


def _estimate(contract: dict[str, Any]) -> int:
    """Estimation grossiere du cout de contexte du handoff (en tokens)."""
    from osiris.core.tokens import count_tokens

    return count_tokens(_render(contract)) + sum(20 for _ in contract.get("context_refs", []))


def get(handoff_id: str) -> dict[str, Any] | None:
    row = (
        get_conn().execute("SELECT * FROM handoffs WHERE handoff_id = ?", (handoff_id,)).fetchone()
    )
    if row is None:
        return None
    try:
        contract = json.loads(row["contract_json"] or "{}")
    except ValueError:
        contract = {}
    try:
        result = json.loads(row["result_json"]) if row["result_json"] else None
    except ValueError:
        result = None
    return {
        "handoff_id": row["handoff_id"],
        "parent_task_id": row["parent_task_id"],
        "status": row["status"],
        "contract": contract,
        "result": result,
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
    }


def complete(handoff_id: str, result: dict[str, Any], status: str = STATUS_COMPLETED) -> bool:
    """Cloture un handoff avec un resultat structure."""
    cur = get_conn().execute(
        "UPDATE handoffs SET status = ?, result_json = ? WHERE handoff_id = ?",
        (status, json.dumps(result, ensure_ascii=False, default=str), handoff_id),
    )
    return cur.rowcount > 0


def list_for(parent_task_id: str) -> list[dict[str, Any]]:
    rows = (
        get_conn()
        .execute(
            "SELECT handoff_id, status, created_at FROM handoffs WHERE parent_task_id = ?"
            " ORDER BY created_at ASC",
            (parent_task_id,),
        )
        .fetchall()
    )
    return [
        {
            "handoff_id": r["handoff_id"],
            "status": r["status"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
