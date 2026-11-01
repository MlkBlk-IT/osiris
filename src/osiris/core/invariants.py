"""`InvariantEngine` — regles anti-casse declaratives.

Source : `.osiris/invariants.toml` (projet) + `~/.osiris/invariants.toml`
(global). Format TOML (stdlib `tomllib`, aucune dependance).

```toml
[[invariant]]
id = "tests-before-commit"
when   = { tool = "git.commit" }
require = { state = "tests_passed" }
message = "ne pas committer si les tests echouent"
```
"""

from __future__ import annotations

import fnmatch
import json
import tomllib
from pathlib import Path
from typing import Any

from osiris.config import settings
from osiris.core.ids import sha256_hex

#: Fichiers d'invariantscharges, par ordre de priorite.
PROJECT_FILE = Path(".osiris") / "invariants.toml"


def _load_file(path: Path) -> list[dict[str, Any]]:
    try:
        if not path.is_file():
            return []
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        return []
    entries = data.get("invariant")
    if isinstance(entries, dict):
        entries = [entries]
    return [e for e in (entries or []) if isinstance(e, dict)]


def load_rules() -> list[dict[str, Any]]:
    """Charge les invariants projet + globaux."""
    rules = _load_file(settings.home / PROJECT_FILE)
    rules += _load_file(Path.cwd() / PROJECT_FILE)
    return rules


def rules_digest() -> str:
    """Digest des regles chargees (entre dans le hash de zone A)."""
    payload = json.dumps(load_rules(), sort_keys=True, ensure_ascii=False, default=str)
    return sha256_hex(payload)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return []


def _extract_paths(args: str | dict | None) -> list[str]:
    """Extrait les valeurs qui ressemblent a des chemins dans des arguments."""
    candidates: list[str] = []
    if isinstance(args, dict):
        obj: Any = args
    else:
        text = (args or "").strip()
        if not text:
            return []
        try:
            obj = json.loads(text)
        except (ValueError, TypeError):
            return []
    stack = [obj]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
        elif isinstance(node, str):
            if "/" in node or "\\" in node or node.count(".") >= 1:
                candidates.append(node.replace("\\", "/"))
    return candidates


def _matches_tool(action: str, patterns: list[str]) -> bool:
    action_l = (action or "").lower()
    for pattern in patterns:
        p = pattern.lower()
        if fnmatch.fnmatch(action_l, p) or action_l.startswith(p):
            return True
    return False


def _matches_path(action: str, args: str | dict | None, patterns: list[str]) -> bool:
    paths = _extract_paths(args)
    if not paths:
        return False
    for path in paths:
        for pattern in patterns:
            p = pattern.replace("\\", "/")
            if fnmatch.fnmatch(path, p) or fnmatch.fnmatch(path, f"*/{p.lstrip('/')}"):
                return True
    return False


def evaluate(
    action: str,
    args: str | dict | None = None,
    flags: dict[str, bool] | None = None,
    budget_ok: bool = True,
    fingerprint_seen: bool = False,
) -> list[dict[str, Any]]:
    """Evalue les invariants contre une action.

    Returns:
        Liste de violations : [{"id", "message", "verdict", "required_action"}]
    """
    flags = flags or {}
    violations: list[dict[str, Any]] = []

    for rule in load_rules():
        rule_id = str(rule.get("id", "invariant"))
        message = str(rule.get("message", rule_id))
        default_verdict = str(rule.get("verdict", "block"))
        when = rule.get("when") or {}
        require = rule.get("require") or {}
        required_action = str(rule.get("required_action", ""))

        applies = True
        tools = _as_list(when.get("tool"))
        if tools and not _matches_tool(action, tools):
            applies = False
        paths = _as_list(when.get("path_glob"))
        if paths and not _matches_path(action, args, paths):
            applies = False
        if when.get("always") is False:
            applies = False
        when_flags = when.get("flag") or {}
        if isinstance(when_flags, dict):
            for name, expected in when_flags.items():
                if bool(flags.get(name)) != bool(expected):
                    applies = False
        if when.get("fingerprint_seen") is True and not fingerprint_seen:
            applies = False

        if not applies:
            continue

        violated = False
        required_states = _as_list(require.get("state"))
        for state in required_states:
            if not flags.get(state):
                violated = True
                required_action = required_action or f"set_{state}"
        if require.get("budget_ok") is True and not budget_ok:
            violated = True
            required_action = required_action or "reduce_scope"
        if not require:
            # regle purement conditionnelle : elle s'applique des que `when` est vrai
            # (ex: "ne jamais modifier tests/**")
            violated = True

        if violated:
            violations.append(
                {
                    "id": rule_id,
                    "message": message,
                    "verdict": default_verdict,
                    "required_action": required_action,
                }
            )
        elif default_verdict == "warn" and require:
            violations.append(
                {
                    "id": rule_id,
                    "message": message,
                    "verdict": "warn",
                    "required_action": required_action,
                }
            )

    return violations


def active_ids() -> list[str]:
    """Identifiants des invariants charges (pour le manifeste)."""
    return [str(r.get("id", "")) for r in load_rules() if r.get("id")]
