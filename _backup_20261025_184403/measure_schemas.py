"""Mesure le footprint des schemas MCP d'OSIRIS.

OSIRIS ne doit pas devenir lui-meme un consommateur massif de contexte :
cette commande verifie que les 6 schemas restent acceptables et affiche leur
cout en tokens (estimation cl100k_base).
"""

from __future__ import annotations

import asyncio
import json

from fastmcp import Client

from osiris.server import mcp


async def measure() -> dict:
    async with Client(mcp) as client:
        tools = await client.list_tools()

    from osiris.core.tokens import count_tokens

    rows = []
    total_chars = 0
    total_desc = 0
    for tool in tools:
        schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", {})
        dumped = json.dumps(schema, separators=(",", ":"))
        desc = tool.description or ""
        rows.append(
            {
                "name": tool.name,
                "schema_chars": len(dumped),
                "schema_tokens": count_tokens(dumped),
                "description_chars": len(desc),
                "params": sorted(schema.get("properties", {}).keys()),
            }
        )
        total_chars += len(dumped)
        total_desc += len(desc)

    payload = {
        "tools": rows,
        "total_schema_chars": total_chars,
        "total_schema_tokens": count_tokens(json.dumps([r["schema_chars"] for r in rows])),
        "total_description_chars": total_desc,
        "estimated_footprint_tokens": count_tokens("".join(json.dumps(r["params"]) for r in rows)),
    }
    return payload


def main() -> int:
    result = asyncio.run(measure())
    for row in result["tools"]:
        print(
            f"{row['name']:22} schema={row['schema_chars']:5} car "
            f"({row['schema_tokens']:4} tok)  desc={row['description_chars']:4} car  "
            f"params={','.join(row['params'])}"
        )
    print("-" * 72)
    print(
        f"TOTAL schemas = {result['total_schema_chars']} car  "
        f"| descriptions = {result['total_description_chars']} car  "
        f"| params = {result['estimated_footprint_tokens']} tok"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
