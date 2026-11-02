"""Politique de gain net centralisee (P5).

Regroupe les calculs de gain net disperses dans prune.py, ledger.py et
server.py. Module additif : les modules existants conservent leurs propres
fonctions. Ce module offre une vue unifiee pour l'audit et le dashboard.

Structure : {proved_gain, loop_gain, fixed_cost, storage_cost} -> net.
"""

from __future__ import annotations

from typing import Any

from osiris.core import ledger
from osiris.core.db import get_conn


def net_gain(task_id: str) -> dict[str, Any]:
    """Gain net complet d'OSIRIS sur une tache.

    Decompose le gain en ses composantes :
    - proved_savings : economies prouvees (kind=saving)
    - loop_savings : economies de boucles (doublons evites)
    - overhead : surcout propre d'OSIRIS (schemas + reponses)
    - storage : cout de stockage des refs (disque, pas LLM)

    net = proved_savings + loop_savings - overhead
    """
    proved = ledger.tokens_saved_exact(task_id)
    loop = ledger.loop_credits(task_id)
    overhead = ledger.overhead(task_id)
    storage = ledger.storage_cost(task_id)

    return {
        "task_id": task_id,
        "proved_savings": proved,
        "loop_savings": loop,
        "total_savings": proved + loop,
        "overhead": overhead,
        "net": proved + loop - overhead,
        "storage": storage,
    }


def gain_breakdown(task_id: str) -> list[dict[str, Any]]:
    """Ventilation detaillee du gain par source.

    Sources : dropped, filtered_access, loop_credit, overhead, schema_access.
    """
    rows = (
        get_conn()
        .execute(
            "SELECT kind, COALESCE(SUM(tokens_saved), 0) AS saved,"
            " COALESCE(SUM(tokens_in), 0) AS cost, COUNT(*) AS n, note"
            " FROM ledger WHERE task_id = ? GROUP BY kind, note ORDER BY saved DESC",
            (task_id,),
        )
        .fetchall()
    )
    return [
        {
            "kind": r["kind"],
            "note": r["note"],
            "entries": int(r["n"]),
            "tokens_saved": int(r["saved"]),
            "tokens_cost": int(r["cost"]),
            "net": int(r["saved"]) - int(r["cost"]),
        }
        for r in rows
    ]
