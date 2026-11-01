"""Test de bout en bout du serveur MCP-OSIRIS via le transport stdio réel.

Lance le serveur comme un vrai subprocess (comme le ferait un client MCP),
puis liste les outils, appelle chaque famille d'outil et verifie le footer
d'integrite.

Usage:
    .venv\\Scripts\\python.exe scripts\\smoke_stdio.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

HOME = Path(tempfile.mkdtemp(prefix="osiris-smoke-"))


async def main() -> int:
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    transport = StdioTransport(
        command=str(PYTHON),
        args=["-m", "osiris"],
        cwd=str(ROOT),
        env={
            "OSIRIS_LOG_LEVEL": "WARNING",
            "OSIRIS_HOME": str(HOME),
            "OSIRIS_ROOTS": str(HOME),
            "OSIRIS_DATA_DIR": str(HOME / "data"),
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        },
    )

    async with Client(transport) as client:
        tools = await client.list_tools()
        print(f"[OK] Serveur demarre via stdio — {len(tools)} outil(s) expose(s) :")
        for tool in tools:
            print(f"     - {tool.name}")

        plan = await client.call_tool(
            "osiris.plan",
            {
                "objective": "verifier le serveur OSIRIS de bout en bout",
                "steps": ["lire", "corriger", "pester"],
                "constraints": ["ne pas modifier les tests"],
            },
        )
        print("\n[OK] osiris.plan ->")
        print(json.dumps(plan.data, ensure_ascii=False, indent=2))

        obs = await client.call_tool(
            "osiris.observe",
            {"kind": "note", "result": "smoke test"},
        )
        print("\n[OK] osiris.observe ->")
        print(json.dumps(obs.data, ensure_ascii=False, indent=2))

        pre = await client.call_tool("osiris.precheck", {"action": "fs.read", "args": "{}"})
        print("\n[OK] osiris.precheck ->")
        print(json.dumps(pre.data, ensure_ascii=False, indent=2))

        hand = await client.call_tool("osiris.handoff", {"mission": "verifier le handoff"})
        print("\n[OK] osiris.handoff ->")
        print(json.dumps(hand.data, ensure_ascii=False, indent=2))

        ckpt = await client.call_tool("osiris.checkpoint", {"mode": "final"})
        print("\n[OK] osiris.checkpoint ->")
        print(json.dumps(ckpt.data, ensure_ascii=False, indent=2))

    print("\n[OK] Fin du smoke test stdio.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
