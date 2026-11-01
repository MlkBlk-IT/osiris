"""CLI locale OSIRIS — hors du budget de contexte du modele.

python -m osiris health
python -m osiris tasks
python -m osiris audit --task <id>
python -m osiris report --task <id>
python -m osiris bench
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def _cmd_health(args: argparse.Namespace) -> int:
    from osiris.config import settings
    from osiris.core.db import get_conn
    from osiris.core.tokens import estimator_name

    conn = get_conn()
    counts = {}
    for table in ("tasks", "memory", "refs", "events", "checkpoints", "handoffs", "ledger"):
        try:
            counts[table] = int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
        except Exception:  # pragma: no cover - table absente
            counts[table] = -1
    print(
        json.dumps(
            {
                "status": "ok",
                "version": settings.version,
                "home": str(settings.home),
                "db": str(settings.db_path),
                "tokenizer": estimator_name(),
                "allowed_roots": [str(r) for r in settings.allowed_roots],
                "counts": counts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_tasks(args: argparse.Namespace) -> int:
    from osiris.core import runtime

    print(json.dumps(runtime.list_tasks(limit=args.limit), ensure_ascii=False, indent=2))
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    from osiris import audit as audit_mod

    task_id = args.task or runtime_current()
    if not task_id:
        print("aucune tache courante ; precise --task", file=sys.stderr)
        return 2
    result = audit_mod.audit_task(task_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["lossless"] else 1


def _cmd_report(args: argparse.Namespace) -> int:
    from osiris import audit as audit_mod

    task_id = args.task or runtime_current()
    if not task_id:
        print("aucune tache courante ; precise --task", file=sys.stderr)
        return 2
    result = audit_mod.write_report(task_id)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    """Lance le benchmark dans un sous-processus.

    `bench/run_bench.py` s'auto-isole : il fixe `OSIRIS_HOME` sur un
    repertoire temporaire AVANT d'importer `osiris.config`, dont les settings
    sont figes a l'import. Mais `osiris/__init__.py` importe `osiris.config`
    des l'import du paquet : dans le process du CLI, l'isolation du bench est
    donc deja rompue. Le benchmark mesurait alors dans la base de
    l'utilisateur, heredait de l'etat des taches precedentes, et echouait sa
    gate (200 tokens : -0.25 % au lieu de +21 %).

    Un sous-processus garantit un import frais, donc une base jetable.
    """
    import pathlib
    import subprocess

    project = pathlib.Path(__file__).resolve().parents[2]
    marker = "###OSIRIS_BENCH_JSON###"
    code = (
        "import json,sys;"
        f"sys.path.insert(0, {str(project)!r});"
        "from bench.run_bench import run;"
        f"print({marker!r}+json.dumps(run(), default=str))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(project / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(project),
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    payload = None
    for line in proc.stdout.splitlines():
        if marker in line:
            payload = line.split(marker, 1)[1]
            break
    if payload is None:
        print(
            f"le benchmark n'a pas rendu de JSON (exit {proc.returncode}) :\n"
            f"{(proc.stderr or proc.stdout)[-2000:]}",
            file=sys.stderr,
        )
        return 2
    result = json.loads(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["gate"]["passed"] else 1


def runtime_current() -> str | None:
    from osiris.core import runtime

    return runtime.current_task_id()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="osiris", description="OSIRIS — context engine cache-aware"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health", help="etat du serveur et du stockage")

    p_tasks = sub.add_parser("tasks", help="liste des taches")
    p_tasks.add_argument("--limit", type=int, default=50, help="nombre max de taches listees")

    p_audit = sub.add_parser("audit", help="verifie qu'aucune information n'a ete perdue")
    p_audit.add_argument("--task", default="")

    p_report = sub.add_parser("report", help="ecrit le rapport md/json/html")
    p_report.add_argument("--task", default="")

    p_bench = sub.add_parser("bench", help="benchmark baseline vs osiris")
    p_bench.add_argument("--out", default="")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers: dict[str, Any] = {
        "health": _cmd_health,
        "tasks": _cmd_tasks,
        "audit": _cmd_audit,
        "report": _cmd_report,
        "bench": _cmd_bench,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
