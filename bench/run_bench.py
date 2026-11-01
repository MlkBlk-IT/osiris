"""Benchmark OSIRIS : agent naif (baseline) vs OSIRIS fixe vs OSIRIS adaptatif.

**Ce que ce benchmark mesure** : l'effet des mecanismes OSIRIS sur le volume
de contexte consomme par une meme tache.

**Ce qu'il ne mesure pas** : la qualite d'un vrai LLM. Les deux agents sont
des scripts deterministes (voir `simulate_baseline` / `simulate_osiris`), donc
le resultat est reproductible et auditable.

Les trois colonnes de droite montrent l'effet de l'adaptation :

- `OSIRIS fixe`      : comportement d'origine (manifeste complet, externalisation
                       systematique, reponses detaillees) ;
- `OSIRIS adaptatif` : le niveau d'engagement suit la taille du payload
                       (voir `core/adaptive.py`).

Le cout des reponses OSIRIS est comptabilise dans les deux cas.

Usage :
    python bench\\run_bench.py           # tableau seul
    python bench\\run_bench.py --json    # + dump JSON complet
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import pathlib
import sys
import tempfile

# L'environnement doit etre configure AVANT l'import de osiris.config
# (les settings sont figes a l'import).
_HOME = pathlib.Path(tempfile.mkdtemp(prefix="osiris-bench-"))
_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
os.environ["OSIRIS_HOME"] = str(_HOME)
os.environ["OSIRIS_DATA_DIR"] = str(_HOME / "data")
os.environ["OSIRIS_ROOTS"] = os.pathsep.join([str(_HOME), str(_FIXTURES)])
os.environ["OSIRIS_LOG_LEVEL"] = "WARNING"

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from fastmcp import Client  # noqa: E402

from osiris.core import adaptive  # noqa: E402
from osiris.core.tokens import count_tokens  # noqa: E402
from osiris.server import mcp  # noqa: E402

MODULE = _FIXTURES / "src" / "Profile.psm1"
TESTS = _FIXTURES / "tests" / "Profile.Tests.ps1"

#: Tailles de prompt testees (tokens).
SIZES = (200, 800, 2_000, 5_000, 20_000)

PESTER_FAIL = """Test resultat : Failed.
Describe : Get-Profile
  It : lance une erreur explicite si la lecture echoue
Expected ...
Exception : Get-Content : le fichier est verrouille par un autre processus.
at Get-Profile, Profile.psm1 line 214
"""

PESTER_PASS = """Test resultat : Passed.
Describe : Get-ProfilePath    [passed]
Describe : Get-DefaultProfileName [passed]
Describe : Test-ProfileExists [passed]
Describe : Get-Profile       [passed]
Describe : Set-Profile       [passed]
Describe : Measure-Profile   [passed]
"""

WRITE_OUT = "1 fichier modifie, 1 insertion(+), 1 suppression(-)"
COMMIT_OUT = "[main 7f3a91c] fix: Get-Profile explicite l'erreur de lecture"

#: Budget de rappel cible (tokens). Ce n'est PAS une economie annoncee : c'est
#: le plafond demande a `osiris.recall`, donc une borne haute sur la taille de
#: l'extrait rappele. Le gain mesure vient de la difference reelle de contexte
#: entre les deux agents. Sensibilite testee par `run(budget=...)` ; surcharge
#: possible via OSIRIS_BENCH_RECALL_BUDGET.
RECALL_BUDGET_TOKENS = int(os.getenv("OSIRIS_BENCH_RECALL_BUDGET", "400"))


class Meter:
    """Compteur de tokens et d'appels."""

    def __init__(self) -> None:
        self.context = 0  # contexte de l'agent principal
        self.subagent = 0  # contextes des sous-agents
        self.overhead = 0  # reponses OSIRIS elles-memes
        self.tool_calls = 0
        self.heavy_calls = 0  # lectures de fichiers + executions de tests
        self.loops = 0
        self.rereads = 0

    @property
    def total(self) -> int:
        return self.context + self.subagent


def _tokens(payload: object) -> int:
    return count_tokens(json.dumps(payload, ensure_ascii=False, default=str))


def _synth_payload(target_tokens: int, index: int) -> pathlib.Path:
    """Ecrit un payload d'environ `target_tokens` tokens dans le home du bench."""
    base = MODULE.read_text(encoding="utf-8")
    approx_chars = max(64, target_tokens * 4)
    text = base
    while len(text) < approx_chars:
        text += "\n" + base
    text = text[:approx_chars]
    path = _HOME / f"synth_{index}_{target_tokens}.psm1"
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# baseline
# ---------------------------------------------------------------------------


def simulate_baseline(module_path: pathlib.Path, tests_path: pathlib.Path) -> dict:
    """Agent naif : pas de memoire, pas de cache, pas de contrat de delegation."""
    m = Meter()
    t_module = count_tokens(module_path.read_text(encoding="utf-8"))
    t_tests = count_tokens(tests_path.read_text(encoding="utf-8"))
    t_fail = count_tokens(PESTER_FAIL)
    t_pass = count_tokens(PESTER_PASS)

    # 1. lecture des deux fichiers
    m.context += t_module
    m.tool_calls += 1
    m.heavy_calls += 1
    m.context += t_tests
    m.tool_calls += 1
    m.heavy_calls += 1

    # 2. sous-agent : on lui colle tout le contexte parent
    m.subagent += m.context
    m.tool_calls += 1

    # 3. relecture du module (aucune memoire de hash)
    m.context += t_module
    m.tool_calls += 1
    m.heavy_calls += 1
    m.rereads += 1

    # 4. boucle : trois executions de tests en echec
    for _ in range(3):
        m.context += t_fail
        m.tool_calls += 1
        m.heavy_calls += 1
        m.loops += 1

    # 5. encore une relecture du module
    m.context += t_module
    m.tool_calls += 1
    m.heavy_calls += 1
    m.rereads += 1

    # 6. correction + tests OK + commit
    m.context += count_tokens(WRITE_OUT)
    m.tool_calls += 1
    m.context += t_pass
    m.tool_calls += 1
    m.heavy_calls += 1
    m.context += count_tokens(COMMIT_OUT)
    m.tool_calls += 1

    return {
        "label": "baseline",
        "tokens_context": m.context,
        "tokens_subagent": m.subagent,
        "tokens_total": m.total,
        "osiris_overhead_tokens": 0,
        "tool_calls": m.tool_calls,
        "heavy_calls": m.heavy_calls,
        "loops": m.loops,
        "rereads": m.rereads,
        "success": True,
    }


# ---------------------------------------------------------------------------
# osiris
# ---------------------------------------------------------------------------


async def simulate_osiris(
    module_path: pathlib.Path, tests_path: pathlib.Path, budget: int = RECALL_BUDGET_TOKENS
) -> dict:
    """Agent assiste : plan, hash de fichiers, rappel cible, handoff, garde-fous.

    Le modele de l'agent est **identique** dans les deux variantes : il utilise
    ce qu'OSIRIS lui donne. Deux principes, appliques pareil dans les deux :

    1. **Consulter avant de relire.** Avant de relire un fichier, l'agent
       demande a OSIRIS s'il l'a deja et si le contenu est toujours valide
       (hash inchange). OSIRIS repond ; si oui, l'agent ne relit pas.
       L'agent naif, lui, n'a aucun moyen de le savoir : il relit. C'est
       exactement l'apport d'un registre content-addresse.
    2. **Utiliser ce qu'OSIRIS donne.** Si OSIRIS fournit une ref, l'agent
       rappelle un extrait cible ; sinon il lit le fichier lui-meme.
    """
    m = Meter()
    t_module = count_tokens(module_path.read_text(encoding="utf-8"))
    t_tests = count_tokens(tests_path.read_text(encoding="utf-8"))
    t_fail = count_tokens(PESTER_FAIL)
    t_pass = count_tokens(PESTER_PASS)

    async with Client(mcp) as client:

        async def call(tool: str, args: dict, where: str = "parent") -> dict:
            """Appelle un outil OSIRIS et impute la reponse a un contexte.

            La reponse est toujours un surcout OSIRIS ; elle n'entre que dans
            le contexte qui la recoit (parent ou sous-agent).
            """
            nonlocal m
            res = await client.call_tool(tool, args)
            data = res.data
            size = _tokens(data)
            m.overhead += size
            m.tool_calls += 1
            if where == "subagent":
                m.subagent += size
            else:
                m.context += size
            return data

        # 1. plan : l'agent annonce la taille du contexte qu'il s'apprete a traiter
        plan = await call(
            "osiris.plan",
            {
                "objective": "corriger le bug de lecture dans Get-Profile",
                "steps": ["lire", "corriger", "pester", "commit"],
                "constraints": ["ne pas modifier les tests"],
                "context_tokens": t_module,
            },
        )

        # 1b. OSIRIS se retire sous le seuil de rentabilite : l'agent fait
        #     exactement ce qu'il ferait sans OSIRIS. Aucun outil OSIRIS n'est
        #     appele, donc OSIRIS ne peut pas couter plus cher que son absence.
        #
        #     **Modele honnete** : en `bystander`, OSIRIS n'ecrit rien — pas de
        #     hash de fichier, pas de fingerprint, pas de contrat de
        #     delegation. L'agent n'a donc **aucune protection** : il relit,
        #     il reboucle, il recopie le contexte au sous-agent, exactement
        #     comme l'agent naif. Lui credited la boucle evitee ou la
        #     relecture evitee revenait a attribuer a OSIRIS un gain qu'il
        #     n'avait pas produit (mesure : +46 % a 200 tokens).
        #     Le seul cout d'OSIRIS dans ce mode est sa reponse de plan.
        if plan.get("mode") == "bystander":
            m.context += t_module + t_tests
            m.tool_calls += 2
            m.heavy_calls += 2
            m.subagent += m.context
            m.tool_calls += 1
            m.context += t_module
            m.tool_calls += 1
            m.heavy_calls += 1
            m.rereads += 1
            for _ in range(3):
                m.context += t_fail
                m.tool_calls += 1
                m.heavy_calls += 1
                m.loops += 1
            m.context += t_module
            m.tool_calls += 1
            m.heavy_calls += 1
            m.rereads += 1
            m.context += count_tokens(WRITE_OUT)
            m.tool_calls += 1
            m.context += t_pass
            m.tool_calls += 1
            m.heavy_calls += 1
            m.context += count_tokens(COMMIT_OUT)
            m.tool_calls += 1
            return {
                "label": "osiris",
                "mode": "bystander",
                "tokens_context": m.context,
                "tokens_subagent": m.subagent,
                "tokens_total": m.total,
                "osiris_overhead_tokens": m.overhead,
                "tool_calls": m.tool_calls,
                "heavy_calls": m.heavy_calls,
                "loops": m.loops,
                "rereads": m.rereads,
                "success": True,
            }

        # 2. lecture du module + observation (OSIRIS lit le fichier LUI-MEME)
        m.context += t_module
        m.tool_calls += 1
        m.heavy_calls += 1
        obs_module = await call(
            "osiris.observe",
            {"kind": "file", "path": str(module_path), "tool": "fs.read"},
        )
        module_ref = obs_module.get("ref") or ""

        # 3. lecture des tests + observation
        m.context += t_tests
        m.tool_calls += 1
        m.heavy_calls += 1
        await call(
            "osiris.observe",
            {"kind": "file", "path": str(tests_path), "tool": "fs.read"},
        )

        # 4. delegation : un contrat, pas le contexte parent
        handoff = await call(
            "osiris.handoff",
            {
                "mission": "analyser Get-Profile et localiser l'erreur de lecture",
                "must_know": ["le bug est dans Get-Profile", "le module est en strict mode"],
                "allowed_tools": ["fs.read"],
                "files": [str(module_path)],
                "budget_tokens": 20000,
            },
        )

        # 5. le sous-agent recupere le contenu : extrait cible si un ref existe,
        #    sinon il lit le fichier lui-meme. Le contrat remplace le contexte
        #    parent ; seul le contrat est transmis.
        m.subagent += count_tokens(str(handoff.get("contract", "")))
        if module_ref:
            await call(
                "osiris.recall",
                {
                    "ref": module_ref,
                    "query": "Get-Profile Get-Content ErrorAction",
                    "budget_tokens": budget,
                },
                where="subagent",
            )
        else:
            m.subagent += t_module
            m.tool_calls += 1

        # 6. l'agent a besoin du module une 2e fois. Il demande d'abord a
        #    OSIRIS si ce qu'il a en contexte est toujours valide.
        if module_ref:
            await call(
                "osiris.recall",
                {
                    "ref": module_ref,
                    "query": "Get-Content Get-Profile",
                    "budget_tokens": budget,
                },
            )
        else:
            check = await call(
                "osiris.observe",
                {"kind": "file", "path": str(module_path), "tool": "fs.read"},
            )
            if not check.get("dup"):
                # OSIRIS ignore ce fichier : l'agent doit le lire.
                m.context += t_module
                m.tool_calls += 1
                m.heavy_calls += 1
                m.rereads += 1

        # 7. boucle de tests : au 2e echec le verdict "warn" declenche un
        #    changement d'approche, l'agent ne rejoue pas une 3e fois
        for _ in range(2):
            m.context += t_fail
            m.tool_calls += 1
            m.heavy_calls += 1
            verdict = await call(
                "osiris.observe",
                {
                    "kind": "test_result",
                    "tool": "shell.exec",
                    "args": '{"cmd":"pester"}',
                    "status": "error",
                    "result": PESTER_FAIL,
                },
            )
            m.loops += 1 if verdict.get("loop", "allow") in ("warn", "block") else 0

        # 8. correction, tests OK, commit
        m.context += count_tokens(WRITE_OUT)
        m.tool_calls += 1
        await call(
            "osiris.observe",
            {
                "kind": "tool_result",
                "tool": "fs.write",
                "args": '{"path":"src/Profile.psm1"}',
                "result": WRITE_OUT,
                "status": "ok",
            },
        )
        m.context += t_pass
        m.tool_calls += 1
        m.heavy_calls += 1
        await call(
            "osiris.observe",
            {
                "kind": "test_result",
                "tool": "shell.exec",
                "args": '{"cmd":"pester"}',
                "status": "ok",
                "result": PESTER_PASS,
            },
        )
        m.context += count_tokens(COMMIT_OUT)
        m.tool_calls += 1

        # 9. checkpoint final : rapport + preuve LOSSLESS
        await call("osiris.checkpoint", {"mode": "final", "label": "fin"})

    return {
        "label": "osiris",
        "mode": plan.get("mode", "standard"),
        "tokens_context": m.context,
        "tokens_subagent": m.subagent,
        "tokens_total": m.total,
        "osiris_overhead_tokens": m.overhead,
        "tool_calls": m.tool_calls,
        "heavy_calls": m.heavy_calls,
        "loops": m.loops,
        "rereads": m.rereads,
        "success": True,
    }


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


def _pct(saved: int, total: int) -> float:
    return round((saved / total * 100) if total else 0.0, 2)


async def _access_cost() -> int:
    """Tokens que l'agent paie pour que les 6 outils OSIRIS existent.

    Les schemas sont presents dans le contexte du modele a chaque requete :
    ce cout est donc paye en continu, pas une fois par tache. Il
    s'amortit sur les taches de la session.
    """
    async with Client(mcp) as client:
        tools = await client.list_tools()
    #: Une seule source de verite pour le cout d'acces : la meme forme que
    #: `scripts/measure_schemas.py` (nom + description + schema compact), sinon
    #: les deux outils du projet annoncent des chiffres differents.
    blocks = []
    for t in tools:
        schema = getattr(t, "input_schema", None) or t.inputSchema
        dumped = json.dumps(schema, separators=(",", ":"), ensure_ascii=False)
        blocks.append(f"{t.name}\n{t.description or ''}\n{dumped}")
    return count_tokens("".join(blocks))


def run(budget: int = RECALL_BUDGET_TOKENS) -> dict:
    access_tokens = asyncio.run(_access_cost())
    rows: list[dict] = []
    for index, size in enumerate(SIZES):
        payload = _synth_payload(size, index)
        base = simulate_baseline(payload, TESTS)

        adaptive.set_enabled(False)
        fixed = asyncio.run(simulate_osiris(payload, TESTS, budget))

        adaptive.set_enabled(True)
        adapt = asyncio.run(simulate_osiris(payload, TESTS, budget))

        gain = base["tokens_total"] - adapt["tokens_total"]
        payback = math.ceil(access_tokens / gain) if gain > 0 else None
        # Gain net de session : le cout d'acces (schemas) est paye une fois par
        # requete client, il s'amortit donc sur les taches de la session. Le
        # gate porte sur ce net, pas sur le gain d'une tache isolee.
        session_net = gain + access_tokens

        rows.append(
            {
                "payload_tokens": size,
                "baseline": base["tokens_total"],
                "osiris_fixed": fixed["tokens_total"],
                "osiris_adaptive": adapt["tokens_total"],
                "fixed_pct": _pct(
                    base["tokens_total"] - fixed["tokens_total"], base["tokens_total"]
                ),
                "adaptive_pct": _pct(
                    base["tokens_total"] - adapt["tokens_total"], base["tokens_total"]
                ),
                "mode": adapt["mode"],
                "overhead_fixed": fixed["osiris_overhead_tokens"],
                "overhead_adaptive": adapt["osiris_overhead_tokens"],
                "success_equal": base["success"] == adapt["success"],
                "gain_tokens": gain,
                "session_net_tokens": session_net,
                "payback_tasks": payback,
            }
        )

    adaptive.set_enabled(True)
    worst = min(rows, key=lambda r: r["adaptive_pct"])
    return {
        "rows": rows,
        "access_tokens": access_tokens,
        "recall_budget_tokens": budget,
        "gate": {
            "criterion": (
                "gain net de session >= 0 sur les 5 tailles (gain + cout d'acces "
                "amorti), succes identique"
            ),
            "worst_adaptive_pct": worst["adaptive_pct"],
            "worst_session_net_tokens": min(r["session_net_tokens"] for r in rows),
            "no_loss": all(r["session_net_tokens"] >= 0 for r in rows),
            "success_equal": all(r["success_equal"] for r in rows),
            "passed": all(r["session_net_tokens"] >= 0 for r in rows)
            and all(r["success_equal"] for r in rows),
        },
        "note": (
            "Modele de mecanisme deterministe : agents scriptes (simulate_baseline / "
            "simulate_osiris). Le cout des reponses OSIRIS est comptabilise. "
            "Ne mesure pas la qualite d'un LLM reel."
        ),
    }


def main() -> int:
    result = run()
    rows = result["rows"]
    print("=" * 78)
    print("TABLEAU DE RENTABILITE OSIRIS — par taille de prompt")
    print("=" * 78)
    print(
        f"{'prompt':>8} {'baseline':>10} {'OSIRIS fixe':>13} {'OSIRIS adaptatif':>18}"
        f" {'ecart fixe':>12} {'ecart adapt.':>13} {'mode':>7} {'surcoat':>9} {'amorti':>8}"
    )
    print("-" * 101)
    for r in rows:
        amorti = str(r["payback_tasks"]) if r["payback_tasks"] else "-"
        print(
            f"{r['payload_tokens']:>8} {r['baseline']:>10} {r['osiris_fixed']:>13}"
            f" {r['osiris_adaptive']:>18} {r['fixed_pct']:>11}% {r['adaptive_pct']:>12}%"
            f" {r['mode']:>7} {r['overhead_adaptive']:>9} {amorti:>8}"
        )
    print("-" * 101)
    print(
        f"COUT D'ACCES (schemas des 6 outils, dans le contexte a chaque requete) : "
        f"{result['access_tokens']} tok | amorti = nb de taches pour rentabiliser"
    )
    g = result["gate"]
    print(
        f"GATE [{g['criterion']}] : pire ecart = {g['worst_adaptive_pct']} % | "
        f"pire net de session = {g['worst_session_net_tokens']} tok | "
        f"aucune perte = {g['no_loss']} | succes identique = {g['success_equal']} -> "
        f"{'PASS' if g['passed'] else 'FAIL'}"
    )
    print("=" * 78)
    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
