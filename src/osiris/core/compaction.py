"""`Compactor` — trim / compact / clear de la zone de travail.

Ce qu'un serveur MCP **ne peut pas** faire : compacter la fenetre du client.
Seul l'hote peut retirer des messages de son historique (cf. la SPEC
`compaction-mcp`, qui dit exactement cela : le serveur fournit les artefacts,
l'hote execute la reduction).

Ce qu'un serveur MCP **peut** faire, et c'est utile : preparer la reduction.

    trim    retire de la zone de travail les entrées anciennes (fichiers lus,
            resultats d'outils) tout en gardant la trace (hash + ref)
    compact produit un resume structure de l'etat utile (contraintes,
            decisions, lecons, plan) a budget de tokens
    clear   reinitialise la zone de travail en gardant les elements epingles

Invariant : **rien n'est detruit**. `trim` et `clear` ne font que sortir des
entrees du jeu actif ; le journal, les refs et le checkpoint restent
intacts, donc l'audit de non-perte continue de passer.
"""

from __future__ import annotations

import time
from typing import Any

from osiris.core.tokens import count_tokens


def trim(state, keep_last: int = 5, keep_files: int = 10) -> dict[str, Any]:
    """Retire les resultats d'outils anciens de la zone de travail.

    Les refs restent dans la base ; seul l'index actif est allege.
    """
    keep_last = max(0, int(keep_last))
    removed = 0
    reclaimed = 0

    keys = sorted(
        state.tool_results.items(),
        key=lambda item: getattr(item[1], "created_at", 0.0),
    )
    for key, entry in keys[:-keep_last] if keep_last else keys:
        reclaimed += int(getattr(entry, "tokens", 0) or 0)
        removed += 1
        del state.tool_results[key]

    paths = sorted(
        state.files.items(),
        key=lambda item: getattr(item[1], "last_read_at", 0.0),
    )
    for path, entry in paths[:-keep_files] if keep_files else paths:
        reclaimed += int(getattr(entry, "size_bytes", 0) or 0) // 4
        removed += 1
        del state.files[path]

    return {
        "op": "trim",
        "removed_entries": removed,
        "reclaimed_tokens": reclaimed,
        "remaining_files": len(state.files),
        "remaining_tool_results": len(state.tool_results),
    }


def compact(state, budget_tokens: int = 1200) -> dict[str, Any]:
    """Resume structure de l'etat utile, a budget de tokens.

    Contenu par ordre de valeur : contraintes, decisions, lecons, plan,
    budget, invariants. Les elements epingles passent en premier.
    """
    blocks: list[str] = []
    spent = 0

    def add(label: str, values: list[str]) -> None:
        nonlocal spent
        if not values:
            return
        chunk = "\n".join(f"- {value}" for value in values)
        cost = count_tokens(f"{label}\n{chunk}")
        if spent + cost > budget_tokens and blocks:
            return
        spent += cost
        blocks.append(f"{label}\n{chunk}")

    add("CONTRAINTES", list(state.constraints))
    add("DECISIONS", list(state.decisions))
    add("LECONS", list(state.lessons))
    add(
        "PLAN",
        [
            f"[{'x' if step in state.plan.done else ' '}] {step}"
            for step in state.plan.steps
        ],
    )
    add("BUDGET", [f"phase={state.budget.phase} calls={state.budget.tool_calls}"])

    text = "\n\n".join(blocks)
    return {
        "op": "compact",
        "text": text,
        "tokens": count_tokens(text),
        "budget_tokens": budget_tokens,
        "truncated": spent >= budget_tokens,
    }


def clear(state, keep_pinned: bool = True) -> dict[str, Any]:
    """Reinitialise la zone de travail (garde les elements epingles)."""
    removed = len(state.files) + len(state.tool_results) + len(state.failures)
    reclaimed = sum(
        int(getattr(entry, "tokens", 0) or 0) for entry in state.tool_results.values()
    )
    state.files.clear()
    state.tool_results.clear()
    state.failures.clear()
    if not keep_pinned:
        state.decisions.clear()
        state.constraints.clear()
        state.lessons.clear()
    return {
        "op": "clear",
        "removed_entries": removed,
        "reclaimed_tokens": reclaimed,
        "kept_pinned": keep_pinned,
        "ts": time.time(),
    }
