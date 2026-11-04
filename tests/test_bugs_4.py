"""4 bugs mcp-osiris v0.1.1 — tests rouge->vert (mission 2026-11-04).

BUG1 : le loop guard ne bloque jamais (pas d'escalade warn/block).
BUG2 : les constraints du plan ne sont pas evaluees par precheck.
BUG3 : handoff fuit des refs sans rapport avec la mission.
BUG4 : checkpoint dit "lossless" sans rien avoir verifie.
"""

from __future__ import annotations

import asyncio

from osiris.core import loopguard


def test_bug1_six_identical_observes_escalate() -> None:
    verdicts = [
        loopguard.record("tb1", "fs.list", '{"p":"x"}', "contenu", "ok")["verdict"]
        for _ in range(6)
    ]
    assert verdicts == ["allow", "suggest_alternative", "warn", "warn", "block", "block"]


def test_bug2_structured_deny_constraint_is_enforced() -> None:
    from osiris import server

    asyncio.run(
        server.osiris_plan(
            objective="bug2",
            constraints=('{"deny": ["filesystem.write_file", "*.delete_*"]}',),
        )
    )
    denied = server.osiris_precheck(
        action="filesystem.write_file", args='{"path": "D:\\\\icy-loom\\\\x.tmp"}'
    )
    assert denied["verdict"] == "deny"
    assert denied["invariant"]
    assert denied["required_action"]
    allowed = server.osiris_precheck(
        action="filesystem.list_directory", args='{"path": "D:\\\\icy-loom"}'
    )
    assert allowed["verdict"] == "allow"


def test_bug3_handoff_without_refs_has_empty_refs() -> None:
    from osiris import server
    from osiris.core import handoff

    asyncio.run(server.osiris_plan(objective="bug3"))
    server.osiris_observe(
        kind="tool_result",
        tool="fs.list",
        args='{"p":"x"}',
        result="gros payload sans lien " * 600,
        status="ok",
    )
    created = server.osiris_handoff(
        mission="lire TESTING.md, rien d'autre", files=(), mode="create"
    )
    contract = handoff.get(created["handoff_id"])["contract"]
    assert contract["context_refs"] == []


def test_bug3_handoff_with_file_keeps_related_ref() -> None:
    from osiris import server
    from osiris.core import handoff

    asyncio.run(server.osiris_plan(objective="bug3b"))
    # gros fichier -> externalise, ref stockee dans state.files
    payload = "contenu de fichier lie a la mission " * 600
    server.osiris_observe(kind="payload", tool="t", result=payload, status="ok")
    # via kind=file sur un fichier reel sous OSIRIS_ROOTS (fixture conftest)
    import pathlib

    from osiris.config import settings

    fpath = settings.home / "mission.txt"
    fpath.write_text(payload, encoding="utf-8")
    server.osiris_observe(kind="file", path=str(fpath))
    created = server.osiris_handoff(
        mission="mission liee", files=(str(fpath),), mode="create"
    )
    contract = handoff.get(created["handoff_id"])["contract"]
    assert len(contract["context_refs"]) >= 1


def test_bug4_checkpoint_without_verified_items_is_unverified() -> None:
    from osiris import server

    asyncio.run(server.osiris_plan(objective="bug4"))
    server.osiris_observe(kind="decision", result="decision enregistree")
    res = server.osiris_checkpoint(label="snap", mode="snapshot")
    assert res["items_verified"] == 0
    assert res["integrity"] == "unverified"


def test_bug4_checkpoint_with_verified_items_is_lossless() -> None:
    from osiris import server

    asyncio.run(server.osiris_plan(objective="bug4b"))
    server.osiris_observe(kind="payload", tool="t", result="gros payload " * 600, status="ok")
    res = server.osiris_checkpoint(label="snap", mode="snapshot")
    assert res["items_verified"] >= 1
    assert res["integrity"] == "lossless"


def test_bug4_corrupted_item_is_not_lossless() -> None:
    from osiris import server
    from osiris.core import refs
    from osiris.core.db import get_conn

    asyncio.run(server.osiris_plan(objective="bug4c"))
    server.osiris_observe(kind="payload", tool="t", result="gros payload " * 600, status="ok")
    ref = refs.list_refs(limit=100)[0]["ref"]
    get_conn().execute("UPDATE refs SET content = 'corrompu' WHERE ref = ?", (ref,))
    res = server.osiris_checkpoint(label="snap", mode="snapshot")
    assert res["integrity"] != "lossless"
