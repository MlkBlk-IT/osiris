"""Tests du store de refs : integrite, roundtrip, extrait cible, redaction."""

from __future__ import annotations

from osiris.core import refs
from osiris.core.ids import sha256_hex


def test_put_get_roundtrip_is_verified():
    entry = refs.put("t1", "contenu de test", meta={"k": "v"})
    assert entry["ref"].startswith("mem://sha256:")
    assert len(entry["ref"]) == len("mem://sha256:") + 64

    got = refs.get(entry["ref"])
    assert got is not None
    assert got["content"] == "contenu de test"
    assert got["verified"] is True


def test_ref_embeds_the_hash_of_the_stored_content():
    entry = refs.put("t1", "abc")
    stored = refs.get(entry["ref"])["content"]
    assert entry["ref"] == f"mem://sha256:{sha256_hex(stored)}"


def test_tampered_content_is_detected():
    entry = refs.put("t1", "original")
    from osiris.core.db import get_conn

    get_conn().execute("UPDATE refs SET content = ? WHERE ref = ?", ("modifie", entry["ref"]))
    got = refs.get(entry["ref"])
    assert got is not None
    assert got["verified"] is False


def test_unknown_ref_returns_none():
    assert refs.get("mem://sha256:" + "0" * 64) is None
    assert refs.get("pas-une-ref") is None


def test_redaction_happens_before_hashing():
    secret = "api_key = sk-abcdefghijklmnopqrstuvwxyz012345"
    entry = refs.put("t1", secret)
    stored = refs.get(entry["ref"])["content"]
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in stored
    assert "REDACTED" in stored
    # le hash porte sur la version stockee
    assert entry["ref"] == f"mem://sha256:{sha256_hex(stored)}"


def test_excerpt_without_query_returns_everything():
    entry = refs.put("t1", "ligne1\nligne2\nligne3")
    out = refs.excerpt(entry["ref"])
    assert out["found"] is True
    assert out["complete"] is True
    assert "ligne3" in out["excerpt"]


def test_excerpt_with_query_zooms_on_the_relevant_region():
    body = ("remplissage\n" * 200) + "FUNCION CLE Get-Profile ici\n" + ("remplissage\n" * 200)
    entry = refs.put("t1", body)
    out = refs.excerpt(entry["ref"], query="Get-Profile", budget_tokens=120)
    assert out["found"] is True
    assert "Get-Profile" in out["excerpt"]
    assert out["total_chars"] > len(out["excerpt"])
    assert out["matches"] >= 1


def test_excerpt_respects_the_token_budget():
    entry = refs.put("t1", "x" * 20000)
    out = refs.excerpt(entry["ref"], budget_tokens=100)
    assert out["tokens"] <= 120
    assert out["complete"] is False
