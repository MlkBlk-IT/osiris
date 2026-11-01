"""Politique de budget.

Les valeurs par defaut sont des garde-fous generiques. L'utilisateur peut
les surcharger via `~/.osiris/policy.json` ou la variable `OSIRIS_POLICY`.
Aucun prix provider n'est code en dur : les prix viennent du fichier de
tarification de l'utilisateur (contrainte : aucune dependance provider).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from osiris.config import settings

DEFAULT_POLICY: dict[str, Any] = {
    "max_tokens": 200_000,
    "max_cost_usd": 5.0,
    "max_tool_calls": 120,
    "max_retries": 6,
    "max_cost_per_step_usd": 0.25,
    "max_calls_per_tool": 40,
    "loop": {
        "duplicate_limit": 2,  # au-dela -> suggest_alternative
        "failure_limit": 3,  # au-dela -> block
        "oscillation_window": 8,
        "runaway_calls": 25,  # appels sans progres
    },
    "prune": {
        "mode": "cache_ttl",
        "threshold_tokens": 40_000,
        "keep_recent_turns": 4,
    },
    "per_tool": {
        "shell.exec": {"max_calls": 30},
        "fs.write": {"max_calls": 40},
        "web.fetch": {"max_calls": 25},
    },
}

DEFAULT_PRICING: dict[str, Any] = {
    "default": {
        "input_per_mtok": 3.0,
        "output_per_mtok": 15.0,
        "cache_read_per_mtok": 0.30,
        "cache_write_per_mtok": 3.75,
    }
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {}


@dataclass(frozen=True)
class Policy:
    """Politique de budget effective."""

    data: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_POLICY))

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def tool_limit(self, tool: str) -> int:
        per_tool = self.get("per_tool", {}) or {}
        entry = per_tool.get(tool) or per_tool.get("*") or {}
        try:
            return int(entry.get("max_calls", self.get("max_calls_per_tool", 40)))
        except (TypeError, ValueError):
            return 40


def load_policy(path: Path | None = None) -> Policy:
    """Charge la politique en fusionnant les defauts et l'override utilisateur."""
    target = path or settings.policy_path
    return Policy(_deep_merge(DEFAULT_POLICY, _load_json(target)))


def load_pricing(path: Path | None = None) -> dict[str, Any]:
    """Charge la table de prix de l'utilisateur (aucun prix code en dur)."""
    target = path or settings.pricing_path
    merged = _deep_merge(DEFAULT_PRICING, _load_json(target))
    return merged.get("default", DEFAULT_PRICING["default"])
