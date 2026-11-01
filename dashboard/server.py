#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OSIRIS Control Plane — dashboard local + API de lecture.

Delta additif : ce module ne modifie pas le noyau d'OSIRIS. Il lit la base
SQLite et les modules `osiris.core.*` en lecture, et expose une API JSON
consommee par `web/app.js`.

    python dashboard/server.py --home D:\\MCP-Osiris\\data\\home --port 8767

Routes :
    GET /                    -> web/index.html
    GET /assets/*            -> web/*
    GET /api/health          -> etat du serveur, de la base, des compteurs
    GET /api/overview        -> KPI globaux (taches, tokens, integrite)
    GET /api/tasks           -> liste des taches
    GET /api/task/<id>       -> etat complet d'une tache (+ prefix/manifeste)
    GET /api/memory          -> memoire typee (scope, kind)
    GET /api/refs            -> store content-addressed
    GET /api/ledger          -> economie de tokens (entrees/sorties/saves)
    GET /api/loopguard       -> empreintes + echecs (anti-boucle)
    GET /api/events          -> journal append-only
    GET /api/handoffs        -> contrats de delegation
    GET /api/invariants      -> invariants anti-casse + verdicts
    GET /api/audit?task=     -> preuve de non-perte
    GET /api/tools           -> les 6 outils MCP + footprint des schemas
    GET /api/bench           -> benchmark baseline vs osiris (isole, cache)
    GET /api/diagnostics     -> bugs detectes + correctifs appliques
    GET /api/config          -> configuration effective
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
WEB = ROOT / "web"

sys.path.insert(0, str(PROJECT / "src"))

#: Benchmark mis en cache (le bench ecrit dans une base, on l'isole).
_BENCH: dict[str, Any] = {"at": 0.0, "data": None, "running": False}
_BENCH_LOCK = threading.Lock()

#: Bugs detectes pendant l'audit, et correctifs appliques.
#: Sert de source unique pour le panneau « Diagnostics » du dashboard.
DIAGNOSTICS: list[dict[str, Any]] = [
    {
        "id": "CLI-TASKS-CRASH",
        "severity": "critical",
        "component": "src/osiris/cli.py",
        "title": "`python -m osiris tasks` raises an AttributeError",
        "symptom": "AttributeError: 'Namespace' object has no attribute 'limit'",
        "cause": (
            "The `tasks` argparse sub-parser did not declare the `--limit` option, "
            "while `_cmd_tasks` read `args.limit`."
        ),
        "fix": "Added the `--limit` option (default 50) to the `tasks` sub-parser.",
        "status": "fixed",
    },
    {
        "id": "ADAPTIVE-COMPACTION-GAP",
        "severity": "high",
        "component": "src/osiris/server.py",
        "title": "`osiris.checkpoint` completely ignored `light` mode",
        "symptom": (
            "On a 172-token payload, the `osiris.checkpoint` response in final "
            "mode cost 120 tokens (report path + digest + counters): 30% of "
            "OSIRIS overhead, for a tiny task."
        ),
        "cause": (
            "`adaptive.py` documents that full responses are a luxury on a small "
            "task, but the `compact` branch only existed in `osiris.observe`. "
            "`osiris.checkpoint` always returned the full payload, whatever the "
            "adaptive level."
        ),
        "fix": (
            "In `light` mode, `checkpoint` now returns only `checkpoint_id`, "
            "`integrity` and `information_perdue`. The report is still written "
            "to disk and counters stay in the database: nothing is lost, only "
            "the redundancy in the context is gone."
        ),
        "status": "fixed",
    },
    {
        "id": "HANDOFF-CONTRACT-KEPT",
        "severity": "info",
        "component": "src/osiris/server.py",
        "title": "Refusing uneconomic delegation: deliberately discarded",
        "symptom": (
            "A first fix refused `osiris.handoff` below the externalization "
            "threshold (800 tokens). It turned the gate green but broke "
            "`test_handoff_create_returns_a_minimal_contract`: the public API "
            "promised a contract."
        ),
        "cause": "A delegation contract is not a context externalization: it stays useful on a small task.",
        "fix": (
            "Fix discarded. `osiris.handoff` always creates a contract; "
            "the savings come from `checkpoint`, not from refusing delegation."
        ),
        "status": "fixed",
    },
    {
        "id": "BENCH-GATE-RED",
        "severity": "high",
        "component": "bench/run_bench.py",
        "title": "The benchmark gate was failing (exit 1)",
        "symptom": (
            "`no_loss: false`, worst delta -3.6% at 200 tokens: OSIRIS cost "
            "more than it saved on small tasks."
        ),
        "cause": "Direct consequence of the `checkpoint` compaction gap (see above).",
        "fix": (
            "The gate is green again (exit 0): 200 tokens went from -3.6% to "
            "+0.32%. The README table was regenerated from the real output."
        ),
        "status": "fixed",
    },
    {
        "id": "README-CJK-CORRUPTION",
        "severity": "low",
        "component": "README.md",
        "title": "Stray CJK characters in the README",
        "symptom": "Section 11: a price-table sentence ended with 4 stray Chinese characters.",
        "cause": "Copy-paste from a mixed-language source.",
        "fix": "Line fixed to read \"price table provided by the user\".",
        "status": "fixed",
    },
    {
        "id": "DOC-TEST-COUNT-DRIFT",
        "severity": "low",
        "component": "AGENTS.md",
        "title": "Test count differs between README and AGENTS.md",
        "symptom": "README announces 65 tests, AGENTS.md announces 62 tests (2 occurrences).",
        "cause": "The counter was not updated when tests were added.",
        "fix": "AGENTS.md aligned on the real count (65).",
        "status": "fixed",
    },
    {
        "id": "README-BENCH-STALE",
        "severity": "medium",
        "component": "README.md",
        "title": "The README benchmark table no longer reproduced",
        "symptom": (
            "The `baseline` columns matched, but the `adaptive` column "
            "claimed +15.3% at 200 tokens where the code produced -3.6%."
        ),
        "cause": "The table was written against another engine version and never regenerated.",
        "fix": "Table regenerated from the real output of `python -m osiris bench`.",
        "status": "fixed",
    },
]


def _home() -> Path:
    return Path(os.environ.get("OSIRIS_HOME", Path.home() / ".osiris"))


def _db_path() -> Path:
    override = os.environ.get("OSIRIS_DASHBOARD_DB")
    if override:
        return Path(override)
    return _home() / "osiris.db"


def _connect() -> sqlite3.Connection | None:
    """Connexion READ-ONLY : le dashboard ne doit jamais ecrire dans la base."""
    db = _db_path()
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def _rows(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    conn = _connect()
    if conn is None:
        return []
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _count(table: str) -> int:
    conn = _connect()
    if conn is None:
        return 0
    try:
        return int(conn.execute(f"SELECT COUNT(*) AS n FROM [{table}]").fetchone()["n"])
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def api_health() -> dict[str, Any]:
    db = _db_path()
    tables = (
        "tasks",
        "memory",
        "refs",
        "events",
        "checkpoints",
        "handoffs",
        "ledger",
        "files",
        "tool_results",
        "tool_usage",
        "fingerprints",
        "failures",
    )
    counts = {t: _count(t) for t in tables}
    connected = db.exists()
    total = sum(counts.values())
    return {
        "ok": connected,
        "db": str(db),
        "home": str(_home()),
        "db_exists": connected,
        "counts": counts,
        "total_rows": total,
        "empty": total == 0,
        "python": sys.version.split()[0],
        "server_time": time.time(),
    }


def api_overview() -> dict[str, Any]:
    ledger = _rows(
        "SELECT kind, COUNT(*) AS n, SUM(tokens_in) AS tin, SUM(tokens_out) AS tout,"
        " SUM(tokens_cached) AS cached, SUM(tokens_saved) AS saved, SUM(tokens_moved) AS moved"
        " FROM ledger GROUP BY kind ORDER BY n DESC"
    )
    totals = {
        "tokens_in": sum(int(r["tin"] or 0) for r in ledger),
        "tokens_out": sum(int(r["tout"] or 0) for r in ledger),
        "tokens_cached": sum(int(r["cached"] or 0) for r in ledger),
        # Economies **prouvees** (l'agent a accuse reception du retrait).
        "tokens_saved": sum(int(r["saved"] or 0) for r in ledger),
        # Tokens **deplaces** vers un ref : stockes, mais pas forcement sortis
        # de la fenetre du modele. Les confondre rendait le gain net fictif.
        "tokens_moved": sum(int(r["moved"] or 0) for r in ledger),
    }
    #: Le surcout d'OSIRIS est la somme de ses reponses (kind `overhead`) ET du
    #: cout des schemas d'outils, paye une fois par tache cote client
    #: (kind `schema_access`). Omettre ce dernier rendait le dashboard
    #: optimiste : il affichait un gain net positif sur des taches ou
    #: OSIRIS coutait en realite plus cher qu'il ne rapportait.
    overhead = sum(
        int(r["tin"] or 0) for r in ledger if r["kind"] in ("overhead", "schema_access")
    )
    schema_access = sum(
        int(r["tin"] or 0) for r in ledger if r["kind"] == "schema_access"
    )
    totals["overhead"] = overhead
    totals["schema_access"] = schema_access
    totals["net_gain"] = totals["tokens_saved"] - overhead
    totals["net_positive"] = totals["net_gain"] > 0

    tasks = _rows("SELECT task_id, updated_at FROM tasks ORDER BY updated_at DESC")
    last = tasks[0]["updated_at"] if tasks else 0

    return {
        "counts": {t: _count(t) for t in ("tasks", "memory", "refs", "events", "checkpoints", "handoffs", "ledger")},
        "ledger": ledger,
        "totals": totals,
        "task_count": len(tasks),
        "last_activity": last,
        "fingerprints": _count("fingerprints"),
        "failures": _count("failures"),
        "tool_results": _count("tool_results"),
    }


_INTEG: dict[str, Any] = {"at": 0.0, "v": "—"}


def _integrity() -> str:
    """Verdict LOSSLESS/VIOLATION de la tache courante, mis en cache 60 s."""
    if time.time() - float(_INTEG["at"]) < 60:
        return str(_INTEG["v"])
    a = api_audit()
    v = "—" if a.get("error") else ("LOSSLESS" if a.get("lossless") else "VIOLATION")
    _INTEG["at"] = time.time()
    _INTEG["v"] = v
    return v


def _plan_counts(state: dict[str, Any]) -> tuple[int, int]:
    """(etapes faites, etapes totales). `plan` = {current, done, steps} (ou liste legacy)."""
    plan = state.get("plan")
    if isinstance(plan, dict):
        return len(plan.get("done") or []), len(plan.get("steps") or [])
    return len(state.get("plan_done") or []), len(plan or [])


def api_tasks() -> dict[str, Any]:
    out = []
    for row in _rows("SELECT task_id, created_at, updated_at, state_json FROM tasks ORDER BY updated_at DESC"):
        try:
            state = json.loads(row["state_json"] or "{}")
        except ValueError:
            state = {}
        out.append(
            {
                "task_id": row["task_id"],
                "objective": state.get("objective", ""),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "level": (state.get("flags") or {}).get("osiris_level", ""),
                "volume": (state.get("flags") or {}).get("osiris_volume", 0),
                "plan_done": _plan_counts(state)[0],
                "plan_total": _plan_counts(state)[1],
                "steps": len(state.get("constraints") or []),
                "files": len(state.get("files") or {}),
                "decisions": len(state.get("decisions") or []),
            }
        )
    return {"tasks": out, "count": len(out)}


def api_task(task_id: str) -> dict[str, Any]:
    rows = _rows("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
    if not rows:
        return {"error": "task not found", "task_id": task_id}
    row = rows[0]
    try:
        state = json.loads(row["state_json"] or "{}")
    except ValueError:
        state = {}
    flags = state.get("flags") or {}
    return {
        "task_id": row["task_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "state": _json_safe(state),
        "objective": state.get("objective", ""),
        "level": flags.get("osiris_level", ""),
        "volume": flags.get("osiris_volume", 0),
        "budget": _json_safe(state.get("budget") or {}),
        "prefix": _json_safe(state.get("prefix") or flags.get("prefix") or state.get("hashes") or {}),
        "plan_done": _plan_counts(state)[0],
        "plan_total": _plan_counts(state)[1],
        "events": _rows("SELECT seq, ts, kind, action_state, run_key FROM events WHERE task_id = ? ORDER BY seq DESC LIMIT 200", (task_id,)),
        "refs": _rows("SELECT ref, size_bytes, content_hash, redactions, created_at FROM refs WHERE task_id = ? OR task_id IS NULL", (task_id,)),
        "ledger": _rows("SELECT seq, ts, kind, tokens_in, tokens_out, tokens_cached, tokens_saved, tokens_moved, note FROM ledger WHERE task_id = ? ORDER BY seq DESC LIMIT 200", (task_id,)),
        "fingerprints": _rows("SELECT fingerprint, tool, count, first_at, last_at FROM fingerprints WHERE task_id = ? ORDER BY count DESC", (task_id,)),
        "failures": _rows("SELECT signature, tool, count, first_at, last_at FROM failures WHERE task_id = ? ORDER BY count DESC", (task_id,)),
        "handoffs": _rows("SELECT handoff_id, status, created_at, expires_at, contract_json FROM handoffs WHERE parent_task_id = ? OR task_id = ?", (task_id, task_id)),
        "checkpoints": _rows("SELECT checkpoint_id, journal_offset, label, created_at FROM checkpoints WHERE task_id = ? ORDER BY created_at DESC", (task_id,)),
    }


def api_memory() -> dict[str, Any]:
    rows = _rows(
        "SELECT mem_id, task_id, scope, kind, body, pinned, meta_json, created_at, seq"
        " FROM memory ORDER BY seq DESC LIMIT 500"
    )
    by_scope: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for r in rows:
        by_scope[r["scope"]] = by_scope.get(r["scope"], 0) + 1
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    return {
        "items": [
            {**r, "body": (r["body"] or "")[:1200], "pinned": bool(r["pinned"])} for r in rows
        ],
        "count": len(rows),
        "by_scope": by_scope,
        "by_kind": by_kind,
    }


def api_refs() -> dict[str, Any]:
    rows = _rows(
        "SELECT ref, task_id, content_hash, size_bytes, redactions, created_at, expires_at, meta_json"
        " FROM refs ORDER BY created_at DESC LIMIT 300"
    )
    return {
        "items": rows,
        "count": len(rows),
        "total_bytes": sum(int(r["size_bytes"] or 0) for r in rows),
        "redactions": sum(int(r["redactions"] or 0) for r in rows),
    }


def api_ledger() -> dict[str, Any]:
    rows = _rows(
        "SELECT task_id, seq, ts, kind, tokens_in, tokens_out, tokens_cached, tokens_fresh,"
        " tokens_saved, tokens_moved, cost, note FROM ledger ORDER BY ts DESC LIMIT 400"
    )
    per_task: dict[str, dict[str, int]] = {}
    for r in rows:
        agg = per_task.setdefault(
            r["task_id"],
            {
                "tokens_in": 0,
                "tokens_out": 0,
                "tokens_cached": 0,
                "tokens_saved": 0,
                "tokens_moved": 0,
                "overhead": 0,
                "entries": 0,
            },
        )
        agg["entries"] += 1
        agg["tokens_in"] += int(r["tokens_in"] or 0)
        agg["tokens_out"] += int(r["tokens_out"] or 0)
        agg["tokens_cached"] += int(r["tokens_cached"] or 0)
        agg["tokens_saved"] += int(r["tokens_saved"] or 0)
        agg["tokens_moved"] += int(r["tokens_moved"] or 0)
        if r["kind"] in ("overhead", "schema_access"):
            agg["overhead"] += int(r["tokens_in"] or 0)
    for agg in per_task.values():
        agg["net_gain"] = agg["tokens_saved"] - agg["overhead"]
    return {"items": rows, "per_task": per_task, "count": len(rows)}


def api_loopguard() -> dict[str, Any]:
    return {
        "fingerprints": _rows(
            "SELECT task_id, fingerprint, tool, args_hash, result_sig, count, first_at, last_at"
            " FROM fingerprints ORDER BY count DESC, last_at DESC LIMIT 200"
        ),
        "failures": _rows(
            "SELECT task_id, signature, tool, args_hash, count, first_at, last_at"
            " FROM failures ORDER BY count DESC, last_at DESC LIMIT 200"
        ),
        "tool_usage": _rows("SELECT task_id, tool, calls, last_at FROM tool_usage ORDER BY calls DESC LIMIT 200"),
        "blocked": _rows("SELECT task_id, fingerprint, tool, count FROM fingerprints WHERE count >= 3 ORDER BY count DESC"),
    }


def api_events() -> dict[str, Any]:
    rows = _rows(
        "SELECT seq, task_id, ts, kind, action_state, run_key, payload_json FROM events"
        " ORDER BY seq DESC LIMIT 300"
    )
    for r in rows:
        try:
            r["payload"] = json.loads(r.pop("payload_json") or "{}")
        except ValueError:
            r["payload"] = {}
    return {"items": rows, "count": len(rows)}


def api_handoffs() -> dict[str, Any]:
    rows = _rows("SELECT * FROM handoffs ORDER BY created_at DESC LIMIT 200")
    for r in rows:
        for field in ("contract_json", "result_json"):
            try:
                r[field.replace("_json", "")] = json.loads(r.pop(field) or "{}")
            except ValueError:
                r[field.replace("_json", "")] = {}
    return {"items": rows, "count": len(rows)}


def api_invariants() -> dict[str, Any]:
    """Invariants TOML + etat du moteur. Lecture seule, jamais d'ecriture."""
    found: list[dict[str, Any]] = []
    sources = []
    env_home = os.environ.get("OSIRIS_HOME")
    candidates = [Path.cwd() / ".osiris" / "invariants.toml", _home() / "invariants.toml"]
    for path in candidates:
        if path.exists():
            sources.append(str(path))
            try:
                import tomllib

                data = tomllib.loads(path.read_text(encoding="utf-8"))
                for inv in data.get("invariant", []) or []:
                    found.append({"source": str(path), **inv})
            except Exception as exc:  # pragma: no cover - lecture seule
                found.append({"source": str(path), "error": str(exc)})
    return {
        "invariants": found,
        "count": len(found),
        "sources": sources,
        "engine": "src/osiris/core/invariants.py",
        "note": (
            "Invariants are read on demand. An invariant is only as good as "
            "the agent's reporting through osiris.observe."
        ),
    }


def api_audit(task_id: str = "") -> dict[str, Any]:
    if not task_id:
        pointer = _home() / "current_task"
        task_id = pointer.read_text(encoding="utf-8").strip() if pointer.exists() else ""
    if not task_id:
        return {"error": "no current task", "lossless": False}
    try:
        from osiris import audit as audit_mod

        result = audit_mod.audit_task(task_id)
        return _json_safe(result)
    except Exception as exc:
        return {"error": str(exc), "task_id": task_id, "lossless": False}


def api_tools() -> dict[str, Any]:
    """Les 6 outils exposes + le cout d'acces mesure."""
    try:
        from osiris.server import mcp
        from osiris.core.tokens import count_tokens

        tools = asyncio_run_tools(mcp)

        def _schema(t) -> dict[str, Any]:
            # FastMCP >= 4 expose `parameters` ; les versions precedentes
            # `input_schema` / `inputSchema`.
            for attr in ("parameters", "input_schema", "inputSchema"):
                v = getattr(t, attr, None)
                if v:
                    return v
            return {}

        blob = json.dumps([_schema(t) for t in tools], ensure_ascii=False, default=str)
        blob += "".join(t.description or "" for t in tools)
        return {
            "tools": [
                {
                    "name": t.name,
                    "description": (t.description or "")[:600],
                    "schema": _json_safe(_schema(t)),
                }
                for t in tools
            ],
            "count": len(tools),
            "access_tokens": count_tokens(blob),
            "schema_chars": len(blob),
        }
    except Exception as exc:
        return {"error": str(exc), "tools": [], "count": 0, "access_tokens": 0}


def asyncio_run_tools(mcp) -> list:
    """Liste les outils d'un serveur FastMCP sans dependre d'un event loop actif.

    L'API a change selon les versions : FastMCP >= 4 expose `list_tools()`,
    les versions precedentes `get_tools()`. On tente les deux.
    """
    import asyncio

    async def _go():
        for name in ("list_tools", "get_tools"):
            fn = getattr(mcp, name, None)
            if fn is None:
                continue
            try:
                return await fn()
            except Exception:
                continue
        return []

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_go())
    return []


def _run_bench_isolated() -> dict[str, Any]:
    """Lance le benchmark dans un process neuf.

    `bench/run_bench.py` s'auto-isole (il cree son propre OSIRIS_HOME a
    l'import), mais dans le process du dashboard `osiris.config` est deja
    charge : l'import reutiliserait les settings du projet et le benchmark
    ecrirait dans la base de l'utilisateur. Un sous-processus garantit un
    import frais, donc une base jetable.
    """
    import subprocess

    code = (
        "import json,sys;"
        f"sys.path.insert(0, {str(PROJECT)!r});"
        "from bench.run_bench import run;"
        "print('###OSIRIS_BENCH_JSON###'+json.dumps(run(), default=str))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(PROJECT),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    marker = "###OSIRIS_BENCH_JSON###"
    for line in proc.stdout.splitlines():
        if marker in line:
            return json.loads(line.split(marker, 1)[1])
    raise RuntimeError(
        "the benchmark returned no JSON (exit %s): %s"
        % (proc.returncode, (proc.stderr or proc.stdout)[-400:])
    )


def api_bench(force: bool = False) -> dict[str, Any]:
    with _BENCH_LOCK:
        fresh = time.time() - float(_BENCH["at"]) < 300 and _BENCH["data"] is not None
        if fresh and not force:
            return {"cached": True, **(_BENCH["data"] or {})}
        if _BENCH["running"]:
            return {"cached": False, "running": True, "note": "benchmark already running"}
        _BENCH["running"] = True

    try:
        data = _run_bench_isolated()
        with _BENCH_LOCK:
            _BENCH["data"] = _json_safe(data)
            _BENCH["at"] = time.time()
            _BENCH["running"] = False
        return {"cached": False, **(_BENCH["data"] or {})}
    except Exception as exc:
        with _BENCH_LOCK:
            _BENCH["running"] = False
        return {"error": str(exc), "rows": [], "gate": {"passed": False}}


def api_diagnostics() -> dict[str, Any]:
    return {
        "items": DIAGNOSTICS,
        "count": len(DIAGNOSTICS),
        "by_status": {
            "fixed": len([d for d in DIAGNOSTICS if d["status"] == "fixed"]),
            "open": len([d for d in DIAGNOSTICS if d["status"] != "fixed"]),
        },
        "source": "audit du code + execution de l'outillage du projet (pytest, ruff, cli, bench)",
    }


def api_config() -> dict[str, Any]:
    env_keys = [
        "OSIRIS_HOME",
        "OSIRIS_ROOTS",
        "OSIRIS_MAX_FILE_BYTES",
        "OSIRIS_CACHE_TTL_S",
        "OSIRIS_PRUNE_THRESHOLD_TOKENS",
        "OSIRIS_POLICY",
        "OSIRIS_PRICING",
        "OSIRIS_EXTERNALIZE_MIN_TOKENS",
        "OSIRIS_MANIFEST_MIN_TOKENS",
        "OSIRIS_COMPACT_BELOW_TOKENS",
        "OSIRIS_FULL_PAYLOAD_TOKENS",
        "OSIRIS_ADAPTIVE",
    ]
    env = {k: os.environ.get(k) for k in env_keys}
    try:
        from osiris.config import settings

        cfg = {
            "version": settings.version,
            "home": str(settings.home),
            "db_path": str(settings.db_path),
            "allowed_roots": [str(r) for r in settings.allowed_roots],
            "tokenizer": settings.tokenizer if hasattr(settings, "tokenizer") else "",
        }
    except Exception as exc:
        cfg = {"error": str(exc)}
    return {
        "env": env,
        "effective": cfg,
        "dashboard_home": str(_home()),
        "dashboard_db": str(_db_path()),
        "project": str(PROJECT),
    }


# ---------------------------------------------------------------------------
# serveur HTTP
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "OsirisControlPlane/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # silence
        pass

    # -- helpers ----------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: Any, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _file(self, rel: str, ctype: str) -> None:
        path = (WEB / rel).resolve()
        try:
            path.relative_to(WEB.resolve())
        except ValueError:
            self._json({"error": "chemin refuse"}, 403)
            return
        if not path.exists() or not path.is_file():
            self._json({"error": "not found", "path": rel}, 404)
            return
        self._send(200, path.read_bytes(), ctype)

    # -- routing ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self._file("index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/assets/"):
            rel = path[len("/assets/") :]
            ctype = (
                "text/css; charset=utf-8" if rel.endswith(".css")
                else "image/svg+xml" if rel.endswith(".svg")
                else "application/javascript; charset=utf-8"
            )
            self._file(rel, ctype)
            return
        if path == "/favicon.ico":
            self._file("logo.svg", "image/svg+xml")
            return

        try:
            if path == "/api/health":
                self._json(api_health())
            elif path == "/api/overview":
                self._json({**api_overview(), "integrity": _integrity()})
            elif path == "/api/tasks":
                self._json(api_tasks())
            elif path.startswith("/api/task/"):
                self._json(api_task(path[len("/api/task/") :]))
            elif path == "/api/memory":
                self._json(api_memory())
            elif path == "/api/refs":
                self._json(api_refs())
            elif path == "/api/ledger":
                self._json(api_ledger())
            elif path == "/api/loopguard":
                self._json(api_loopguard())
            elif path == "/api/events":
                self._json(api_events())
            elif path == "/api/handoffs":
                self._json(api_handoffs())
            elif path == "/api/invariants":
                self._json(api_invariants())
            elif path == "/api/audit":
                self._json(api_audit((query.get("task") or [""])[0]))
            elif path == "/api/tools":
                self._json(api_tools())
            elif path == "/api/bench":
                self._json(api_bench(force=(query.get("force") or ["0"])[0] == "1"))
            elif path == "/api/diagnostics":
                self._json(api_diagnostics())
            elif path == "/api/config":
                self._json(api_config())
            else:
                self._json({"error": "route inconnue", "path": path}, 404)
        except Exception as exc:  # pragma: no cover
            self._json({"error": str(exc), "type": type(exc).__name__}, 500)


def main() -> None:
    ap = argparse.ArgumentParser(description="OSIRIS Control Plane — dashboard")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--home", default="", help="OSIRIS_HOME a lire (defaut: env ou ~/.osiris)")
    args = ap.parse_args()

    if args.home:
        os.environ["OSIRIS_HOME"] = args.home

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print("OSIRIS Control Plane -> http://%s:%d/" % (args.host, args.port))
    print("  db    : %s" % _db_path())
    print("  home  : %s" % _home())
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
