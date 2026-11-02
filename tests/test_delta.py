"""Tests des deltas P0-P5 : recalibration, confidence tokens, prune refs,
credit loop savings, decision module, schema conditionnel."""

from __future__ import annotations

import time

import pytest
from fastmcp import Client

from osiris.server import mcp


def _data(result):
    data = getattr(result, "data", None)
    if data is None:
        data = getattr(result, "structured_content", None)
    if isinstance(data, dict) and "result" in data and len(data) == 1:
        data = data["result"]
    return data


@pytest.fixture
async def client():
    async with Client(mcp) as c:
        yield c

# ---------------------------------------------------------------------------
# P0 — recalibration des seuils
# ---------------------------------------------------------------------------

def test_recalibrate_adjusts_thresholds_with_enough_samples():
    from osiris.core import adaptive

    entries = [{"kind": "observe", "tokens_in": 500 + i * 10} for i in range(30)]
    result = adaptive.recalibrate(entries, min_samples=20)
    assert result["adjusted"] is True
    assert result["samples"] == 30
    assert "median" in result
    assert "q3" in result
    assert result["old"]["bystander"] == 600
    assert result["new"]["bystander"] != 600
    adaptive.reset_thresholds()
    assert adaptive.BYSTANDER_BELOW_TOKENS == 600
    assert adaptive.EXTERNALIZE_MIN_TOKENS == 120


def test_recalibrate_insufficient_samples():
    from osiris.core import adaptive

    entries = [{"kind": "observe", "tokens_in": 500} for _ in range(5)]
    result = adaptive.recalibrate(entries, min_samples=20)
    assert result["adjusted"] is False
    assert "insufficient" in result["reason"]


def test_recalibrate_respects_floors():
    from osiris.core import adaptive

    # Tres petits payloads : les seuils ne descendent pas sous les floors
    entries = [{"kind": "observe", "tokens_in": 10 + i} for i in range(25)]
    result = adaptive.recalibrate(
        entries, min_samples=20,
        floor_bystander=200, floor_externalize=50, floor_manifest=400,
    )
    assert result["adjusted"] is True
    assert result["new"]["bystander"] >= 200
    assert result["new"]["externalize"] >= 50
    assert result["new"]["manifest"] >= 400
    adaptive.reset_thresholds()


# ---------------------------------------------------------------------------
# P2 — confidence interval sur l'estimation de tokens
# ---------------------------------------------------------------------------

def test_count_tokens_with_confidence_returns_interval():
    from osiris.core.tokens import count_tokens_with_confidence

    low, point, high = count_tokens_with_confidence("hello world " * 100)
    assert low <= point <= high
    assert low > 0
    assert high >= point  # variance >= 0


def test_count_tokens_with_confidence_empty():
    from osiris.core.tokens import count_tokens_with_confidence

    assert count_tokens_with_confidence("") == (0, 0, 0)


def test_count_tokens_with_confidence_exact_when_tiktoken_available():
    """Si tiktoken est disponible, l'intervalle est degeneré (exact)."""
    from osiris.core.tokens import _load_encoder, count_tokens_with_confidence

    enc = _load_encoder()
    if enc is None:
        pytest.skip("tiktoken non installe")
    text = "def f(x):\n    return x + 1\n" * 50
    low, point, high = count_tokens_with_confidence(text)
    assert low == point == high


def test_calibration_factor_starts_at_one():
    from osiris.core.tokens import calibration_factor

    assert calibration_factor() == 1.0


# ---------------------------------------------------------------------------
# P1 — schema conditionnel : bystander ne charge pas les schemas
# ---------------------------------------------------------------------------

async def test_bystander_does_not_charge_schema_access(client):
    """En mode bystander, _record_schema_access n'ecrit pas dans le ledger."""
    from osiris.core import ledger, runtime

    data = _data(await client.call_tool("osiris.plan", {
        "objective": "petit", "context_tokens": 100,
    }))
    assert data["mode"] == "bystander"
    state = runtime.get_task()
    overhead = ledger.overhead(state.task_id)
    assert overhead == 0, f"bystander doit avoir un overhead nul, pas {overhead}"


async def test_engaged_task_charges_schema_access(client):
    """En mode standard, _record_schema_access ecrit dans le ledger."""
    from osiris.core import ledger, runtime

    data = _data(await client.call_tool("osiris.plan", {
        "objective": "gros", "context_tokens": 5000,
    }))
    assert data["mode"] != "bystander"
    state = runtime.get_task()
    overhead = ledger.overhead(state.task_id)
    assert overhead > 0, f"standard doit avoir un overhead > 0, pas {overhead}"


# ---------------------------------------------------------------------------
# P3 — prune des refs expirees
# ---------------------------------------------------------------------------

def test_prune_expired_removes_expired_refs():
    from osiris.core import refs

    entry = refs.put("task-stale", "temporary content here", ttl=0.001)
    assert refs.exists(entry["ref"])
    time.sleep(0.02)  # laisser le TTL expirer
    result = refs.prune_expired(only_unaccessed=True)
    assert result["removed"] >= 1
    assert not refs.exists(entry["ref"])


def test_prune_expired_keeps_unexpired_refs():
    from osiris.core import refs

    entry = refs.put("task-fresh", "persistent content", ttl=3600)
    result = refs.prune_expired(only_unaccessed=True)
    assert result["removed"] == 0
    assert refs.exists(entry["ref"])


def test_prune_expired_keeps_accessed_expired_refs():
    """Une ref expiree mais deja relue n'est pas supprimee (securite)."""
    from osiris.core import events, refs, runtime

    runtime.create_task("task-acc")
    entry = refs.put("task-acc", "accessed content", ttl=0.001)
    # Simuler un recall
    events.append("task-acc", "recall", {"ref": entry["ref"], "op": "grep"})
    time.sleep(0.02)
    result = refs.prune_expired(only_unaccessed=True)
    # La ref a ete recue, elle ne doit pas etre supprimee
    assert result["removed"] == 0
    assert refs.exists(entry["ref"])


def test_storage_cost_returns_size():
    from osiris.core import ledger, refs

    refs.put("task-sc", "x" * 400, ttl=0)
    cost = ledger.storage_cost("task-sc")
    assert cost["refs"] >= 1
    assert cost["bytes"] >= 400


# ---------------------------------------------------------------------------
# P4 — credit des economies de boucles
# ---------------------------------------------------------------------------

async def test_credit_loop_savings_no_duplicates():
    """Sans doublon, credit_loop_savings retourne 0."""
    from osiris.core import ledger, runtime

    state = runtime.create_task("no-loop")
    ledger.record(state.task_id, "observe", tokens_in=500, tokens_moved=0)
    saved = ledger.credit_loop_savings(state.task_id)
    assert saved == 0


async def test_credit_loop_savings_idempotent():
    """Un deuxieme appel ne recredite pas."""
    from osiris.core import ledger, runtime

    state = runtime.create_task("idemp")
    # Simuler des doublons manuellement
    ledger.record(state.task_id, "observe", tokens_in=1000, tokens_moved=0,
                  note="loop_guard:saved:500")
    ledger.record(state.task_id, "observe", tokens_in=1000, tokens_moved=0,
                  note="loop_guard:saved:500")
    first = ledger.credit_loop_savings(state.task_id)
    second = ledger.credit_loop_savings(state.task_id)
    assert first == second  # idempotent


# ---------------------------------------------------------------------------
# P5 — module decision
# ---------------------------------------------------------------------------

def test_decision_net_gain_structure():
    from osiris.core import decision, runtime

    state = runtime.create_task("dec-task")
    gain = decision.net_gain(state.task_id)
    assert "proved_savings" in gain
    assert "loop_savings" in gain
    assert "total_savings" in gain
    assert "overhead" in gain
    assert "net" in gain
    assert "storage" in gain
    assert gain["net"] == gain["total_savings"] - gain["overhead"]


def test_decision_gain_breakdown_empty():
    from osiris.core import decision, runtime

    state = runtime.create_task("dec-empty")
    breakdown = decision.gain_breakdown(state.task_id)
    assert breakdown == []


def test_decision_gain_breakdown_with_data():
    from osiris.core import decision, ledger, runtime

    state = runtime.create_task("dec-data")
    ledger.record(state.task_id, "saving", tokens_saved=300, note="dropped")
    ledger.record(state.task_id, "schema_access", tokens_in=200)
    breakdown = decision.gain_breakdown(state.task_id)
    kinds = {e["kind"] for e in breakdown}
    assert "saving" in kinds
    assert "schema_access" in kinds
