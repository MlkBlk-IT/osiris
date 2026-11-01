"""Tests du LoopGuard : doublons, echecs repetes, oscillation, runaway."""

from __future__ import annotations

from osiris.core import loopguard


def test_first_call_is_allowed():
    verdict = loopguard.record("t1", "fs.read", '{"path":"a.ps1"}', "contenu", "ok")
    assert verdict["verdict"] == "allow"


def test_exact_duplicate_suggests_an_alternative():
    loopguard.record("t1", "fs.read", '{"path":"a.ps1"}', "contenu", "ok")
    verdict = loopguard.record("t1", "fs.read", '{"path":"a.ps1"}', "contenu", "ok")
    assert verdict["verdict"] == "suggest_alternative"
    assert verdict["reason"] == "exact_duplicate"


def test_canonical_args_neutralise_key_order():
    loopguard.record("t1", "fs.read", '{"path":"a.ps1","mode":"r"}', "x", "ok")
    verdict = loopguard.record("t1", "fs.read", '{"mode":"r","path":"a.ps1"}', "x", "ok")
    assert verdict["verdict"] == "suggest_alternative"


def test_repeated_failure_is_blocked_at_the_limit():
    for _ in range(2):
        verdict = loopguard.record(
            "t1", "shell.exec", '{"cmd":"pester"}', "Assert-MockCalled failed", "error"
        )
    assert verdict["verdict"] == "warn"
    verdict = loopguard.record(
        "t1", "shell.exec", '{"cmd":"pester"}', "Assert-MockCalled failed", "error"
    )
    assert verdict["verdict"] == "block"
    assert verdict["reason"] == "repeated_failure"
    assert verdict["required_action"] == "fix_then_retry"


def test_same_error_with_different_args_is_a_loop_pattern():
    loopguard.record("t1", "shell.exec", '{"cmd":"pester -Path A"}', "boom", "error")
    verdict = loopguard.record("t1", "shell.exec", '{"cmd":"pester -Path B"}', "boom", "error")
    assert verdict["verdict"] in ("warn", "block")
    assert verdict["reason"] in ("failure_repeating", "repeated_failure", "loop_pattern")


def test_error_signature_is_stable_across_noise():
    a = loopguard.error_signature("Error at line 42: Assert-MockCalled expected 1, got 0")
    b = loopguard.error_signature("Error at line 99: Assert-MockCalled expected 2, got 0")
    assert a == b


def test_different_errors_have_different_signatures():
    a = loopguard.error_signature("Assert-MockCalled failed")
    b = loopguard.error_signature("FileNotFoundException: x.ps1")
    assert a != b


def test_fingerprint_ignores_whitespace_and_none():
    a = loopguard.fingerprint("t", '{"a": 1, "b": null}', "sig")
    b = loopguard.fingerprint("t", '{"b":null,"a":1}', "sig")
    assert a == b
