"""Tests d'integration des 6 outils MCP d'OSIRIS."""

from __future__ import annotations

import json
from pathlib import Path

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


async def test_plan_starts_a_task_and_issues_a_manifest(client):
    res = await client.call_tool(
        "osiris.plan",
        {"objective": "corriger le bug de profil", "steps": ["lire", "corriger", "pester"]},
    )
    data = _data(res)
    assert data["task_id"]
    assert "OSIRIS/1" in data["manifest"]
    assert data["seal"].startswith("sha256:")
    assert data["next_step"] == "lire"
    assert data["budget"]["ok"] is True
    assert "rec" in data["compass"]
    assert "avoid" in data["compass"]


async def test_plan_update_keeps_the_same_task(client):
    first = _data(await client.call_tool("osiris.plan", {"objective": "obj", "steps": ["a", "b"]}))
    second = _data(
        await client.call_tool("osiris.plan", {"mode": "update", "steps": ["a", "b", "c"]})
    )
    assert first["task_id"] == second["task_id"]
    assert second["next_step"] == "a"


async def test_decision_is_pinned_and_does_not_break_the_cache(client):
    plan = _data(await client.call_tool("osiris.plan", {"objective": "obj", "steps": ["a"]}))
    seal_before = plan["seal"]

    res = await client.call_tool(
        "osiris.observe", {"kind": "decision", "result": "corriger via -ErrorAction Stop"}
    )
    data = _data(res)
    assert data["ok"] is True
    # l'append d'une decision ne casse PAS le prefix cache
    assert data["drift"] == "append"

    recalled = _data(await client.call_tool("osiris.recall", {"kind": "decision"}))
    bodies = [i["body"] for i in recalled["items"]]
    assert "corriger via -ErrorAction Stop" in bodies
    assert recalled["state"]["decisions"] == ["corriger via -ErrorAction Stop"]
    assert seal_before == plan["seal"]


async def test_small_file_gets_a_hash_but_no_ref(client, sample_file: Path):
    """Sous le seuil d'externalisation : hash seul, la detection de doublon
    reste active, mais aucune ref n'est creee (elle couterait plus qu'elle
    ne rapporterait)."""
    await client.call_tool("osiris.plan", {"objective": "obj"})
    res = await client.call_tool(
        "osiris.observe", {"kind": "file", "path": str(sample_file), "tool": "fs.read"}
    )
    data = _data(res)
    assert data["ok"] is True
    assert data.get("ref", "") == ""
    assert data["dup"] is False

    # relecture du meme fichier -> detecte comme doublon
    again = _data(
        await client.call_tool(
            "osiris.observe", {"kind": "file", "path": str(sample_file), "tool": "fs.read"}
        )
    )
    assert again["dup"] is True
    assert "deja lu" in again["hint"]


async def test_large_file_is_externalized_into_a_verified_ref(client, tmp_root: Path):
    """Au-dela du seuil : le payload est externalise et devient rehydratable.

    Le contenu est lu **cote serveur** : il n'est donc pas une economie
    (il n'a jamais ete dans le contexte du modele), c'est un **deplacement**.
    L'economie n'est creditee que sur accuse de reception.
    """
    big = tmp_root / "Big.psm1"
    big.write_text(("function Big { param($x) return $x }\n" * 120), encoding="utf-8")

    await client.call_tool("osiris.plan", {"objective": "obj"})
    res = await client.call_tool(
        "osiris.observe", {"kind": "file", "path": str(big), "tool": "fs.read"}
    )
    data = _data(res)
    assert data["ok"] is True
    assert data["ref"].startswith("mem://sha256:")
    assert data["moved"] > 0
    assert data["saved"] == 0  # rien n'a encore quitte le contexte

    recalled = _data(
        await client.call_tool("osiris.recall", {"ref": data["ref"], "query": "function Big"})
    )
    assert recalled["found"] is True
    assert "function Big" in recalled["items"][0]["text"]


async def test_file_outside_allowed_roots_is_denied(client, tmp_path: Path):
    await client.call_tool("osiris.plan", {"objective": "obj"})
    outside = Path("C:/Windows/System32/drivers/etc/hosts")
    if not outside.exists():
        pytest.skip("fichier de test indisponible")
    res = await client.call_tool("osiris.observe", {"kind": "file", "path": str(outside)})
    data = _data(res)
    assert data["ok"] is False
    assert "acces refuse" in data["hint"]


async def test_precheck_allows_a_safe_action(client):
    await client.call_tool("osiris.plan", {"objective": "obj"})
    res = await client.call_tool("osiris.precheck", {"action": "fs.read", "args": '{"path":"a"}'})
    data = _data(res)
    assert data["verdict"] in ("allow", "warn")
    assert data["budget_ok"] is True


async def test_precheck_blocks_a_repeated_identical_call(client):
    await client.call_tool("osiris.plan", {"objective": "obj"})
    args = '{"path":"x.ps1"}'
    await client.call_tool(
        "osiris.observe", {"kind": "tool_result", "tool": "fs.read", "args": args}
    )
    res = await client.call_tool("osiris.precheck", {"action": "fs.read", "args": args})
    data = _data(res)
    assert data["verdict"] in ("warn", "suggest_alternative")
    assert any("duplicate" in r for r in data["reasons"])


async def test_test_result_sets_the_flag(client):
    await client.call_tool("osiris.plan", {"objective": "obj"})
    await client.call_tool(
        "osiris.observe", {"kind": "test_result", "tool": "shell.exec", "status": "ok"}
    )
    recalled = _data(await client.call_tool("osiris.recall", {}))
    assert recalled["state"]["flags"]["tests_passed"] is True


async def test_checkpoint_final_writes_a_lossless_report(client):
    await client.call_tool("osiris.plan", {"objective": "rapport"})
    await client.call_tool(
        "osiris.observe", {"kind": "payload", "result": "un gros payload " * 400}
    )
    res = await client.call_tool("osiris.checkpoint", {"mode": "final", "label": "fin"})
    data = _data(res)
    assert data["integrity"] == "lossless"
    assert data["information_perdue"] == 0
    assert data["items_verified"] >= 1
    # Un seul chemin est renvoye (le markdown) : json et html partagent la
    # meme base, ils sont donc derivables sans aucun champ supplementaire.
    md = Path(data["report"])
    assert md.is_file()
    assert md.with_suffix(".json").is_file()
    assert md.with_suffix(".html").is_file()
    assert data["report_digest"]
    assert "OSIRIS" in md.read_text(encoding="utf-8")


async def test_handoff_create_returns_a_minimal_contract(client, sample_file: Path):
    await client.call_tool("osiris.plan", {"objective": "deleguer"})
    await client.call_tool("osiris.observe", {"kind": "file", "path": str(sample_file)})
    res = await client.call_tool(
        "osiris.handoff",
        {
            "mission": "analyser le module",
            "must_know": ["le bug est ligne 42"],
            "allowed_tools": ["fs.read"],
            "files": [str(sample_file)],
            "budget_tokens": 20000,
        },
    )
    data = _data(res)
    assert data["handoff_id"]
    assert "HANDOFF/1" in data["contract"]
    assert data["estimated_tokens"] < 2000


async def test_handoff_collect_returns_the_structured_result(client):
    await client.call_tool("osiris.plan", {"objective": "deleguer"})
    created = _data(await client.call_tool("osiris.handoff", {"mission": "m"}))
    handoff_id = created["handoff_id"]

    await client.call_tool(
        "osiris.handoff",
        {"mode": "complete", "handoff_id": handoff_id, "result": json.dumps({"ok": True})},
    )
    collected = _data(
        await client.call_tool("osiris.handoff", {"mode": "collect", "handoff_id": handoff_id})
    )
    assert collected["status"] == "completed"
    assert collected["result"]["ok"] is True


async def test_resume_reports_unknown_actions(client):
    await client.call_tool("osiris.plan", {"objective": "obj"})
    res = await client.call_tool("osiris.plan", {"mode": "resume"})
    data = _data(res)
    assert "resume" in data
    assert "unknown_actions" in data["resume"]
    assert data["resume"]["current"] == ""


async def test_tool_count_is_exactly_six(client):
    tools = await client.list_tools()
    names = sorted(t.name for t in tools)
    assert names == [
        "osiris.checkpoint",
        "osiris.handoff",
        "osiris.observe",
        "osiris.plan",
        "osiris.precheck",
        "osiris.recall",
    ]


async def test_tool_schemas_stay_small(client):
    """OSIRIS ne doit pas devenir lui-meme un consommateur de contexte."""
    tools = await client.list_tools()
    total = 0
    for tool in tools:
        schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", {})
        total += len(json.dumps(schema))
    assert total < 6000, f"schemas trop gros: {total} caracteres"


async def test_tool_responses_stay_small(client):
    """Les reponses OSIRIS doivent rester courtes.

    C'est la garde-fou la plus importante du produit : OSIRIS ne peut pas
    coûter plus de contexte que ce qu'il en fait gagner.
    """
    from osiris.core.tokens import count_tokens

    def size(result) -> int:
        return count_tokens(json.dumps(_data(result), ensure_ascii=False, default=str))

    plan = await client.call_tool("osiris.plan", {"objective": "budget", "steps": ["a"]})
    assert size(plan) < 260, f"reponse de plan trop grosse: {size(plan)}"

    obs = await client.call_tool(
        "osiris.observe", {"kind": "tool_result", "tool": "fs.read", "args": "{}"}
    )
    assert size(obs) < 110, f"reponse d'observe trop grosse: {size(obs)}"

    ckpt = await client.call_tool("osiris.checkpoint", {"mode": "snapshot"})
    assert size(ckpt) < 110, f"reponse de checkpoint trop grosse: {size(ckpt)}"


async def test_osiris_overhead_is_measured(client):
    """Le surcout propre d'OSIRIS est trace dans le ledger."""
    from osiris.core import ledger, runtime

    # Un volume declare au-dessus du seuil engage OSIRIS : il ecrit alors son surcout.
    await client.call_tool("osiris.plan", {"objective": "overhead", "context_tokens": 5000})
    state = runtime.get_task()
    assert state is not None
    assert ledger.overhead(state.task_id) > 0
    assert ledger.net_saving(state.task_id) <= 0  # au depart, rien de gagne


async def test_plan_warns_when_osiris_costs_more_than_it_saves(client):
    """Si le surcout depasse le gain, OSIRIS le dit a l'agent."""
    await client.call_tool(
        "osiris.plan", {"objective": "warn", "steps": ["a"], "context_tokens": 5000}
    )
    await client.call_tool("osiris.observe", {"kind": "note", "result": "petit"})
    res = await client.call_tool("osiris.plan", {"mode": "update"})
    data = _data(res)
    assert "hint" in data
    assert "surcout OSIRIS" in data["hint"]


async def test_adaptive_level_follows_the_declared_context_size(client):
    """OSIRIS ajuste son niveau d'engagement a la taille annoncee."""
    # Sous le seuil de rentabilite, OSIRIS se retire : aucune ecriture, aucun surcout.
    small = _data(
        await client.call_tool("osiris.plan", {"objective": "petit", "context_tokens": 100})
    )
    assert small["mode"] == "bystander"

    light = _data(
        await client.call_tool("osiris.plan", {"objective": "moyen", "context_tokens": 700})
    )
    assert light["mode"] == "light"
    assert "budget" not in light  # reponse compacte
    assert "compass" not in light

    standard = _data(
        await client.call_tool("osiris.plan", {"objective": "gros", "context_tokens": 5000})
    )
    assert standard["mode"] == "standard"
    assert "budget" in standard
    assert "compass" in standard

    full = _data(
        await client.call_tool("osiris.plan", {"objective": "enorme", "context_tokens": 20000})
    )
    assert full["mode"] == "full"


async def test_adaptive_thresholds():
    from osiris.core import adaptive

    # Le seuil de rentabilite mesure par le bench : sous 600 tok OSIRIS se retire.
    assert adaptive.BYSTANDER_BELOW_TOKENS == 600
    assert adaptive.level_for(100) == "bystander"
    assert adaptive.should_engage(100) is False
    assert adaptive.should_engage(5000) is True
    # Le seuil d'externalisation est aligne sur le regime reel mesure
    # (mediane ~87 tok, max ~215) : un payload de 200 tok merite une ref, un
    # payload sous le seuil non (la ref couterait plus qu'elle ne rapporte).
    assert adaptive.EXTERNALIZE_MIN_TOKENS == 120
    assert adaptive.should_externalize(50) is False
    assert adaptive.should_externalize(200) is True
    assert adaptive.wants_full_manifest(100) is False
    assert adaptive.wants_full_manifest(5000) is True
    assert adaptive.wants_compact_response(100) is True
    assert adaptive.wants_compact_response(5000) is False


# --------------------------------------------------------------------------
# economie honnete : ne crediter que ce qui est prouve
# --------------------------------------------------------------------------


async def test_savings_are_only_credited_after_an_acknowledgement(client, tmp_root: Path):
    """Le ledger ne credite une economie que sur accuse de reception.

    C'est le correctif du biais le plus grave : avant, chaque payload
    externalise etait compte comme "gagne" alors que rien n'avait quitté la
    fenetre du modele (mesure : 11 534 tokens "gagnes" pour 2 494 observes).
    """
    from osiris.core import ledger, runtime

    big = tmp_root / "Ack.psm1"
    big.write_text(("function Ack { param($x) return $x }\n" * 200), encoding="utf-8")

    await client.call_tool("osiris.plan", {"objective": "ack"})
    data = _data(
        await client.call_tool(
            "osiris.observe", {"kind": "file", "path": str(big), "tool": "fs.read"}
        )
    )
    ref = data["ref"]
    assert ref
    state = runtime.get_task()
    assert ledger.tokens_saved_exact(state.task_id) == 0

    # l'agent confirme avoir retire le payload de son contexte
    ack = _data(
        await client.call_tool(
            "osiris.observe", {"kind": "dropped", "result": ref}
        )
    )
    assert ack["saved"] > 0
    assert ledger.tokens_saved_exact(state.task_id) == ack["saved"]
    fresh = runtime.get_task()
    assert fresh.budget.tokens_saved == ack["saved"]


async def test_savings_never_exceed_the_content_that_was_handled(client):
    """Invariant structurel : on ne peut pas "gagner" plus qu'on a manipule.

    Ce test echouait sur l'ancien code (11534 > 2494) et sert de garde-fou
    contre la regression. La reference est `tokens_in + tokens_moved` : les
    tokens observes (payes par l'agent) plus ceux deplaces vers un ref (que
    l'agent aurait payes en les relisant).
    """
    from osiris.core import ledger, runtime

    await client.call_tool("osiris.plan", {"objective": "invariant", "context_tokens": 5000})
    await client.call_tool(
        "osiris.observe", {"kind": "payload", "result": "x" * 4000}
    )
    state = runtime.get_task()
    totals = ledger.totals(state.task_id)
    handled = totals["tokens_in"] + totals["tokens_moved"]
    assert totals["tokens_saved"] <= handled, (
        f"economie fantaisiste: saved={totals['tokens_saved']} "
        f"in={totals['tokens_in']} moved={totals['tokens_moved']}"
    )


async def test_filtered_recall_credits_the_avoided_full_read(client):
    """Le gain d'un acces filtre est **mesure** et credite.

    Scenario reel (test de bout en bout dans Claude) : un payload de ~2000
    tokens est observe, puis relu avec `op="grep"` : seules 5 lignes rentrent
    dans le contexte. L'economie = contenu_complet - lu, et elle est portee
    par le ledger — sans que l'agent ait a declarer le retrait du payload.
    """
    from osiris.core import ledger, runtime

    payload = "\n".join(
        [f"2026-10-31T22:00:00Z INFO ligne {i} sans importance" for i in range(60)]
        + [f"2026-10-31T22:00:0{i} ERROR un vrai probleme {i}" for i in range(8)]
    )
    await client.call_tool("osiris.plan", {"objective": "grep", "context_tokens": 5000})
    obs = _data(
        await client.call_tool("osiris.observe", {"kind": "payload", "result": payload})
    )
    ref = obs["ref"]
    assert ref

    rec = _data(
        await client.call_tool(
            "osiris.recall", {"ref": ref, "op": "grep", "query": "ERROR"}
        )
    )
    assert rec["found"] is True
    assert rec["matches"] == 8
    assert rec["saved"] > 0

    state = runtime.get_task()
    assert ledger.tokens_saved_exact(state.task_id) == rec["saved"]

    # un second acces filtre au meme ref ne recredite pas : l'agent relit un
    # extrait qu'il connait deja, ce n'est plus une relecture complete evitee.
    again = _data(
        await client.call_tool(
            "osiris.recall", {"ref": ref, "op": "grep", "query": "ERROR"}
        )
    )
    assert "saved" not in again
    assert ledger.tokens_saved_exact(state.task_id) == rec["saved"]


# --------------------------------------------------------------------------
# nouvelles primitives : pression, filtrage serveur, compaction
# --------------------------------------------------------------------------


async def test_plan_status_reports_the_context_pressure(client):
    await client.call_tool("osiris.plan", {"objective": "pression", "context_tokens": 5000})
    data = _data(await client.call_tool("osiris.plan", {"mode": "status"}))
    status = data["status"]
    assert status["declared_context_tokens"] == 5000
    assert status["confidence"] == "declared"
    assert "client_history" in status["unknown"]
    assert status["pressure_pct"] > 0
    assert status["recommendation"]


async def test_recall_filters_server_side_before_returning(client, tmp_root: Path):
    """Le filtrage se fait dans OSIRIS : seul le resultat entre dans le contexte."""
    big = tmp_root / "Grep.psm1"
    big.write_text(
        "\n".join(f"line {i} " + ("target " if i % 20 == 0 else "filler ") for i in range(200)),
        encoding="utf-8",
    )
    await client.call_tool("osiris.plan", {"objective": "grep"})
    ref = _data(
        await client.call_tool("osiris.observe", {"kind": "file", "path": str(big)})
    )["ref"]

    data = _data(
        await client.call_tool(
            "osiris.recall", {"ref": ref, "op": "grep", "query": "target"}
        )
    )
    assert data["found"] is True
    assert data["matches"] == 10
    # le resultat est bien plus petit que la source
    assert data["items"][0]["tokens"] < 200


async def test_checkpoint_compact_summarises_the_pinned_state(client):
    await client.call_tool("osiris.plan", {"objective": "compacter", "steps": ["a", "b"]})
    await client.call_tool(
        "osiris.observe", {"kind": "decision", "result": "utiliser -ErrorAction Stop"}
    )
    data = _data(await client.call_tool("osiris.checkpoint", {"mode": "compact"}))
    assert data["mode"] == "compact"
    assert "utiliser -ErrorAction Stop" in data["text"]
    assert data["tokens"] > 0


async def test_checkpoint_trim_alleges_the_working_set(client):
    """`trim` sort les resultats anciens de la zone de travail.

    Rien n'est detruit : les refs restent en base, seul l'index actif est
    allegé — l'audit de non-perte continue de passer.
    """
    await client.call_tool("osiris.plan", {"objective": "trim"})
    for i in range(7):
        await client.call_tool(
            "osiris.observe",
            {
                "kind": "tool_result",
                "tool": "fs.read",
                "args": json.dumps({"path": f"file{i}.ps1"}),
                "result": "contenu volumineux " * 80,
            },
        )
    data = _data(await client.call_tool("osiris.checkpoint", {"mode": "trim"}))
    assert data["op"] == "trim"
    assert data["removed_entries"] >= 1
    assert data["reclaimed_tokens"] > 0


# --------------------------------------------------------------------------
# tableau d'outils : stable par construction
# --------------------------------------------------------------------------


async def test_the_default_tool_array_is_exactly_six_tools(client):
    """Le tableau `tools` fait partie du prefixe mis en cache : il doit rester
    stable. Le mode dispatch-only (un seul schema) est opt-in."""
    tools = await client.list_tools()
    assert len(tools) == 6


def test_dispatch_only_mode_exposes_a_single_tool(tmp_path):
    """En mode dispatch-only, seul `osiris.call` est expose.

    Le but : un tableau `tools` minimal et stable, donc un prefixe cache qui
    ne bouge pas d'une requete a l'autre.
    """
    import os
    import subprocess
    import sys

    code = (
        "import asyncio, json\n"
        "from osiris.server import mcp\n"
        "async def main():\n"
        "    tools = await mcp.list_tools()\n"
        "    print(json.dumps(sorted(t.name for t in tools)))\n"
        "asyncio.run(main())\n"
    )
    env = {**os.environ, "OSIRIS_DISPATCH_ONLY": "1", "OSIRIS_HOME": str(tmp_path)}
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout.strip().splitlines()[-1]) == ["osiris.call"]
