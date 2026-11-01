"""Tests de la preuve de non-perte (audit LOSSLESS)."""

from __future__ import annotations

from osiris import audit as audit_mod
from osiris.core import refs, runtime
from osiris.core.db import get_conn


def _externalize(task_id: str, text: str) -> str:
    entry = refs.put(task_id, text)
    return entry["ref"]


def test_audit_is_lossless_after_externalization():
    state = runtime.create_task("audit")
    _externalize(state.task_id, "contenu externe")

    result = audit_mod.audit_task(state.task_id)
    assert result["lossless"] is True
    assert result["items_externalized"] == 1
    assert result["items_verified"] == 1
    assert result["items_dropped"] == 0
    assert result["integrity_violations"] == []


def test_audit_detects_a_tampered_payload():
    state = runtime.create_task("audit")
    ref = _externalize(state.task_id, "contenu externe")
    get_conn().execute("UPDATE refs SET content = ? WHERE ref = ?", ("pirate", ref))

    result = audit_mod.audit_task(state.task_id)
    assert result["lossless"] is False
    assert len(result["integrity_violations"]) == 1
    assert result["integrity_violations"][0]["issue"] == "hash_mismatch"


def test_metrics_separate_exact_estimated_and_verifiable():
    state = runtime.create_task("metrics")
    _externalize(state.task_id, "payload")

    m = audit_mod.metrics(state.task_id)
    assert set(m) == {"exact", "estimated", "verifiable"}
    assert m["verifiable"]["lossless"] is True
    assert m["exact"]["prefix_stability"] == 1.0
    assert "tokens_observed" in m["estimated"]
    assert "cache_hit_estimate" in m["estimated"]


def test_report_contains_the_expected_sections():
    state = runtime.create_task("rapport")
    _externalize(state.task_id, "payload")
    paths = audit_mod.write_report(state.task_id)

    md = paths["markdown"]
    text = open(md, encoding="utf-8").read()
    assert "# OSIRIS" in text
    assert "## Economie" in text
    assert "## Cache" in text
    assert "## Integrite" in text
    assert "LOSSLESS" in text

    import json

    data = json.loads(open(paths["json"], encoding="utf-8").read())
    assert data["verifiable"]["lossless"] is True

    html = open(paths["html"], encoding="utf-8").read()
    assert html.startswith("<!doctype html>")
    assert "LOSSLESS" in html
