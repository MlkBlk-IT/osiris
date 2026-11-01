"""Tests de l'etat de tache, de la memoire et du journal."""

from __future__ import annotations

from osiris.core import events, ledger, memory, runtime
from osiris.core.task_state import BudgetState, Plan, TaskState


def test_task_state_roundtrip():
    state = TaskState(objective="corriger le bug")
    state.plan = Plan(steps=["lire", "corriger"], current=1)
    state.add_constraint("ne pas modifier les tests")
    state.add_decision("utiliser -ErrorAction Stop")
    state.set_flag("tests_passed", True)

    restored = TaskState.loads(state.dumps())
    assert restored.objective == state.objective
    assert restored.plan.steps == state.plan.steps
    assert restored.constraints == state.constraints
    assert restored.decisions == state.decisions
    assert restored.flag("tests_passed") is True


def test_decisions_are_append_only_and_deduplicated():
    state = TaskState()
    state.add_decision("decision A")
    state.add_decision("decision A")
    state.add_decision("decision B")
    assert state.decisions == ["decision A", "decision B"]


def test_budget_remaining_and_ok():
    budget = BudgetState(max_tokens=1000, max_cost_usd=1.0, max_tool_calls=10)
    assert budget.ok is True
    budget.tokens_estimated = 900
    assert budget.tokens_remaining == 100
    budget.tokens_estimated = 1200
    assert budget.ok is False
    assert budget.tokens_remaining == 0


def test_memory_is_typed_and_filterable():
    memory.add("t1", "decision", "utiliser Stop", pinned=True)
    memory.add("t1", "lesson", "toujours verifier le hash")
    memory.add("t1", "note", "sans importance")

    decisions = memory.list_entries(task_id="t1", kind="decision")
    assert len(decisions) == 1
    assert decisions[0]["pinned"] is True
    assert decisions[0]["body"] == "utiliser Stop"

    pinned = memory.pinned_entries("t1")
    assert len(pinned) == 1


def test_journal_distinguishes_succeeded_failed_and_unknown():
    events.append("t1", "action", {"tool": "x"}, run_key="k1", action_state=events.STATE_BEGIN)
    events.append("t1", "action", {"tool": "y"}, run_key="k2", action_state=events.STATE_BEGIN)
    events.end_action("t1", "k2", events.STATE_FAILED)

    open_actions = events.open_actions("t1")
    assert len(open_actions) == 1
    assert open_actions[0]["state"] == events.STATE_UNKNOWN
    assert open_actions[0]["run_key"] == "k1"

    completed = events.completed_actions("t1")
    assert completed == []


def test_checkpoint_records_the_journal_offset():
    events.append("t1", "x", {})
    ckpt = events.save_checkpoint("t1", "label", {"a": 1})
    assert ckpt["journal_offset"] >= 1
    restored = events.get_checkpoint(ckpt["checkpoint_id"])
    assert restored is not None
    assert restored["state"] == {"a": 1}


def test_ledger_totals():
    ledger.record("t1", "observe", tokens_in=100, tokens_saved=40)
    ledger.record("t1", "observe", tokens_in=50, tokens_saved=10)
    totals = ledger.totals("t1")
    assert totals["tokens_in"] == 150
    assert totals["tokens_saved"] == 50
    assert totals["entries"] == 2


def test_runtime_creates_and_persists_a_task():
    state = runtime.create_task("objectif", ["a", "b"], ["c1"])
    assert state.task_id
    assert runtime.current_task_id() == state.task_id
    loaded = runtime.get_task(state.task_id)
    assert loaded is not None
    assert loaded.objective == "objectif"
    assert runtime.list_tasks()[0]["task_id"] == state.task_id
