"""Tests du moteur d'invariants (regles declaratives anti-casse)."""

from __future__ import annotations

import pytest

from osiris.config import settings
from osiris.core import invariants

RULES = """
[[invariant]]
id = "tests-before-commit"
when   = { tool = "git.commit" }
require = { state = "tests_passed" }
message = "ne pas committer si les tests echouent"

[[invariant]]
id = "no-test-edit"
when   = { path_glob = "tests/**" }
verdict = "block"
message = "ne pas modifier les tests sans approbation"

[[invariant]]
id = "budget"
when   = { always = true }
require = { budget_ok = true }
message = "ne pas depasser le budget"
"""


@pytest.fixture(autouse=True)
def rules_file():
    path = settings.home / ".osiris" / "invariants.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(RULES, encoding="utf-8")
    yield path
    if path.exists():
        path.unlink()


def test_invariant_blocks_commit_when_tests_failed():
    violations = invariants.evaluate("git.commit", '{"message":"x"}', flags={"tests_passed": False})
    ids = {v["id"] for v in violations}
    assert "tests-before-commit" in ids
    assert "budget" not in ids  # budget_ok par defaut


def test_invariant_allows_commit_when_tests_passed():
    violations = invariants.evaluate("git.commit", '{"message":"x"}', flags={"tests_passed": True})
    ids = {v["id"] for v in violations}
    assert "tests-before-commit" not in ids


def test_path_glob_invariant_blocks_editing_tests():
    violations = invariants.evaluate(
        "fs.write", '{"path":"tests/Profile.Tests.ps1","content":"x"}', flags={}
    )
    assert any(v["id"] == "no-test-edit" for v in violations)


def test_path_glob_invariant_ignores_other_paths():
    violations = invariants.evaluate("fs.write", '{"path":"src/Profile.psm1"}', flags={})
    assert not any(v["id"] == "no-test-edit" for v in violations)


def test_budget_invariant_blocks_when_budget_exceeded():
    violations = invariants.evaluate("shell.exec", "{}", flags={}, budget_ok=False)
    assert any(v["id"] == "budget" for v in violations)


def test_invariant_with_glob_tool_pattern():
    path = settings.home / ".osiris" / "invariants.toml"
    path.write_text(
        '[[invariant]]\nid = "no-git"\nwhen = { tool = "git.*" }\n'
        'verdict = "block"\nmessage = "git interdit ici"\n',
        encoding="utf-8",
    )
    violations = invariants.evaluate("git.push", "{}", flags={})
    assert any(v["id"] == "no-git" for v in violations)


def test_rules_digest_changes_with_the_rules():
    first = invariants.rules_digest()
    path = settings.home / ".osiris" / "invariants.toml"
    path.write_text(
        RULES + "\n[[invariant]]\nid = 'x'\nwhen = { always = true }\n", encoding="utf-8"
    )
    assert invariants.rules_digest() != first
