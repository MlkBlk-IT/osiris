"""Tests du CachePlanner : hashes de zones, drift, scan de motifs volatils.

Modele (corrige le 2026-10-31) :
  head_hash   = system head + regles projet      (immuable)
  zoneB_hash  = objectif + plan + contract client (quasi-stable)
  tail_hash   = contraintes + decisions            (append-only)
  prefix_hash = head + zoneB                      (ce qui est reellement cache)

Donc : ajouter une contrainte ou une decision ne casse PAS le cache, et
reecrire un element epingle est une rupture **semantique** detectee.
"""

from __future__ import annotations

from osiris.core import prefix


def _analyze(**kwargs):
    base = {
        "objective": "corriger le bug",
        "constraints": ["ne pas modifier les tests"],
        "decisions": [],
        "plan_global": ["lire", "corriger"],
        "project_rules_digest": "rules1",
    }
    base.update(kwargs)
    return prefix.analyze_prefix(**base)


def _pinned(constraints=(), decisions=()):
    return {"constraints": list(constraints), "decisions": list(decisions)}


def test_prefix_hash_is_stable_when_nothing_changes():
    a = _analyze()
    b = _analyze()
    assert a["zones"]["prefix_hash"] == b["zones"]["prefix_hash"]


def test_appending_a_decision_does_not_break_the_prefix_cache():
    """C'est LA propriete cle : append = delta, pas re-prefill total."""
    first = _analyze(decisions=[])
    second = _analyze(decisions=["corriger via -ErrorAction Stop"])
    drift = prefix.detect_drift(first["zones"], second["zones"])

    assert drift["verdict"] == prefix.DRIFT_APPEND
    assert drift["cache_broken"] is False
    assert second["zones"]["prefix_hash"] == first["zones"]["prefix_hash"]
    assert second["zones"]["tail_hash"] != first["zones"]["tail_hash"]
    assert second["zones"]["zoneA_hash"] != first["zones"]["zoneA_hash"]


def test_appending_a_constraint_does_not_break_the_prefix_cache():
    """Les contraintes sont append-only : les ajouter ne doit PAS crier au loup.

    Avant correction, elles etaient hachees dans `head_hash` : chaque
    contrainte declaree declenchait un DRIFT CRITIQUE alors que le prefixe
    cache etait intact.
    """
    first = _analyze(constraints=["ne pas modifier les tests"])
    second = _analyze(
        constraints=["ne pas modifier les tests", "ne pas toucher au CI"],
    )
    drift = prefix.detect_drift(
        first["zones"],
        second["zones"],
        _pinned(constraints=["ne pas modifier les tests"]),
        _pinned(constraints=["ne pas modifier les tests", "ne pas toucher au CI"]),
    )

    assert drift["verdict"] == prefix.DRIFT_APPEND
    assert drift["cache_broken"] is False
    assert second["zones"]["prefix_hash"] == first["zones"]["prefix_hash"]
    assert second["zones"]["tail_hash"] != first["zones"]["tail_hash"]


def test_rewriting_a_constraint_is_a_critical_drift():
    """Reecrire une contrainte = rupture semantique (invariant n°2).

    Le prefixe cache reste intact (la contrainte vit dans la queue), mais
    l'etat de la tache a change de sens : c'est `semantic_break` qui le dit.
    """
    first = _analyze(constraints=["ne pas modifier les tests"])
    second = _analyze(constraints=["autre contrainte"])
    drift = prefix.detect_drift(
        first["zones"],
        second["zones"],
        _pinned(constraints=["ne pas modifier les tests"]),
        _pinned(constraints=["autre contrainte"]),
    )

    assert drift["verdict"] == prefix.DRIFT_CRITICAL
    assert drift["cause"] == prefix.CAUSE_PINNED
    assert drift["semantic_break"] is True
    # le prefixe cache n'est pas invalide : les contraintes sont dans la queue
    assert drift["cache_broken"] is False
    assert drift["action"] == "alert_pinned_rewrite"
    assert drift["rewritten"]


def test_rewriting_a_decision_is_a_critical_drift():
    """L'invariant n°2 d'AGENTS.md, enfinimplemente en place."""
    first = _analyze(decisions=["decision A"])
    second = _analyze(decisions=["decision B"])
    drift = prefix.detect_drift(
        first["zones"],
        second["zones"],
        _pinned(decisions=["decision A"]),
        _pinned(decisions=["decision B"]),
    )

    assert drift["verdict"] == prefix.DRIFT_CRITICAL
    assert drift["semantic_break"] is True
    assert drift["rewritten"]


def test_changing_the_objective_is_a_minor_drift():
    first = _analyze(objective="corriger le bug")
    second = _analyze(objective="corriger l'autre bug")
    drift = prefix.detect_drift(first["zones"], second["zones"])

    assert drift["verdict"] == prefix.DRIFT_MINOR
    assert drift["cache_broken"] is False
    assert "zoneB" in drift["changed"]


def test_first_observation_is_not_a_drift():
    drift = prefix.detect_drift({}, _analyze()["zones"])
    assert drift["verdict"] == prefix.DRIFT_NONE


def test_volatile_scan_detects_dynamic_content():
    found = prefix.scan_volatile("timestamp=2026-10-25T02:16:00Z session_id=abc123")
    assert "timestamp_iso" in found
    assert "dynamic_field" in found

    found = prefix.scan_volatile("id=550e8400-e29b-41d4-a716-446655440000")
    assert "uuid" in found

    assert prefix.scan_volatile("rien de dynamique ici") == []


def test_cache_mortality_probability_is_a_threshold_not_a_ramp():
    """Le TTL est deterministe : P(mort) = 0 avant, 1 apres.

    La rampe lineaire (`elapsed/ttl`) inventait une mortalite de 50 % a
    mi-TTL et autorisait `mode_allows_prefix` a 0,9*TTL, donc la destruction
    d'un prefixe encore chaud.
    """
    assert prefix.cache_mort_probability(0, 300) == 0.0
    assert prefix.cache_mort_probability(150, 300) == 0.0
    assert prefix.cache_mort_probability(299, 300) == 0.0
    assert prefix.cache_mort_probability(300, 300) == 1.0
    assert prefix.cache_mort_probability(400, 300) == 1.0
    assert prefix.cache_mort_probability(10, 0) == 1.0


def test_prefill_plan_has_the_spec_shape():
    plan = _analyze()["prefill_plan"]
    for key in (
        "prefix_hash",
        "stable_blocks",
        "cache_breakpoints",
        "volatile_tail",
        "estimated_cached_tokens",
        "estimated_fresh_tokens",
        "risk",
        "warnings",
    ):
        assert key in plan
    assert plan["risk"] == "low"


def test_pinned_snapshot_round_trip():
    raw = prefix.pinned_snapshot(["c1"], ["d1"])
    loaded = prefix.load_pinned(raw)
    assert loaded == {"constraints": ["c1"], "decisions": ["d1"]}
    assert prefix.load_pinned("") == {}
    assert prefix.load_pinned("pas du json") == {}
