"""`PressureMeter` — decomposition de la pression sur le contexte.

Un serveur MCP **ne voit pas** la fenetre de contexte de son client : il ne
connait ni le system prompt, ni l'historique, ni les fichiers injectes. Toute
mesure de "place occupee" ser donc une invention... sauf a distinguer
explicitement ce qui est **declare** par l'agent de ce qui est **observe** par
OSIRIS.

Ce module fait cette separation au lieu de melanger les deux :

    declared   le nombre de tokens que l'agent declare (context_tokens)
    observed   ce qu'OSIRIS a vu passer (payloads, reponses d'outils)
    unknown    l'historique du client, que personne ne peut mesurer

C'est le meme esprit que le reste du produit : mieux vaut un "unknown"
explicitement signale qu'un chiffre flatteur et faux.
"""

from __future__ import annotations

from typing import Any

from osiris.core.tokens import count_tokens

#: Postes de la fenetre, avec leur source de verite.
PART_SYSTEM = "system_prompt"
PART_SCHEMAS = "tool_schemas"
PART_OSIRIS = "osiris_responses"
PART_PAYLOADS = "observed_payloads"
PART_REFS = "refs_stored"
PART_PINNED = "pinned_state"
PART_HISTORY = "client_history"

#: Postes dont la valeur est observee par OSIRIS.
OBSERVED_PARTS = (PART_SCHEMAS, PART_OSIRIS, PART_PAYLOADS, PART_REFS, PART_PINNED)


def snapshot(
    state,
    schema_tokens: int = 0,
    overhead_tokens: int = 0,
    phase_budgets: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Retourne une decomposition honnete de la pression contexte.

    `pressure_pct` est calcule sur la **fenetre declaree** quand elle existe,
    sinon sur l'estimation OSIRIS (avec `confidence = "estimated"`).
    """
    declared = int(getattr(state.budget, "context_tokens_current", 0) or 0)
    observed_total = int(getattr(state.budget, "tokens_estimated", 0) or 0)
    moved = int(getattr(state.budget, "tokens_moved", 0) or 0)
    saved = int(getattr(state.budget, "tokens_saved", 0) or 0)

    pinned_text = " ".join(
        list(state.constraints) + list(state.decisions) + list(state.lessons)
    )
    parts: dict[str, int] = {
        PART_SCHEMAS: int(schema_tokens or 0),
        PART_OSIRIS: int(overhead_tokens or 0),
        PART_PAYLOADS: observed_total,
        PART_REFS: moved,
        PART_PINNED: count_tokens(pinned_text) if pinned_text else 0,
        # Jamais mesure : c'est l'historique du client.
        PART_HISTORY: 0,
    }

    estimated = sum(parts[name] for name in OBSERVED_PARTS)
    window = declared or estimated
    max_tokens = int(getattr(state.budget, "max_tokens", 0) or 0)
    pressure = (window / max_tokens) if max_tokens else 0.0

    phase = str(getattr(state.budget, "phase", "") or "")
    phase_used = dict(getattr(state.budget, "phase_tokens", {}) or {})

    recommendation = ""
    if declared and max_tokens:
        if pressure >= 0.9:
            recommendation = "fenetre presque saturante : compacte ou drop avant de continuer"
        elif pressure >= 0.7:
            recommendation = "fenetre haute : externalise les prochains gros payloads"
        elif pressure >= 0.4:
            recommendation = "fenetre comfortable"
        else:
            recommendation = "fenetre large : OSIRIS peut se permettre d'etre bavard"

    return {
        "declared_context_tokens": declared,
        "estimated_context_tokens": estimated,
        "window_tokens": window,
        "max_tokens": max_tokens,
        "pressure_pct": round(pressure, 4),
        "confidence": "declared" if declared else "estimated",
        "unknown": [PART_HISTORY],
        "parts": parts,
        "tokens_moved": moved,
        "tokens_saved": saved,
        "phase": phase,
        "phase_used": phase_used,
        "phase_budgets": dict(phase_budgets or {}),
        "recommendation": recommendation,
    }
