"""Point d'entree : `python -m osiris` (serveur MCP) ou `python -m osiris <cmd>` (CLI)."""

from __future__ import annotations

import sys


def main() -> int:
    # Sans argument : serveur MCP en stdio.
    # Avec un argument : CLI locale (health, tasks, audit, report, bench).
    if len(sys.argv) > 1 and sys.argv[1] in {
        "health",
        "tasks",
        "audit",
        "report",
        "bench",
    }:
        from osiris.cli import main as cli_main

        return cli_main(sys.argv[1:])
    from osiris.server import main as server_main

    server_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
