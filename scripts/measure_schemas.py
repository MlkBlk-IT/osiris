"""Mesure le footprint des schemas MCP d'OSIRIS.

OSIRIS ne doit pas devenir lui-meme un consommateur massif de contexte :
cette commande verifie que les 6 schemas restent acceptables et affiche leur
cout reel en tokens.

**Ce que le client paye reellement** : chaque outil est rendu comme un couple
(nom, description, schema JSON) dans le contexte du modele. Le cout d'acces
est donc le token-count de la concatenation de ces trois champs pour les 6
outils — c'est ce que `bench/run_bench.py::_access_cost()` mesure et ce que
l'audit impute (`kind='schema_access'`).

Historique : avant correction, ce script comptait `count_tokens` sur une
liste de nombres (`[1250, 890, ...]`) et sur les seuls **noms** de parametres,
soit 111 tokens. Ce chiffre ne correspondait a rien de ce que le modele lit
et n'etait comparable a aucune autre mesure du projet.
"""

from __future__ import annotations

import asyncio
import json

from fastmcp import Client

from osiris.server import mcp


def _schema(tool) -> dict:
    for attr in ("input_schema", "inputSchema", "parameters"):
        value = getattr(tool, attr, None)
        if value:
            return value
    return {}


async def measure() -> dict:
    async with Client(mcp) as client:
        tools = await client.list_tools()

    from osiris.core.tokens import count_tokens

    rows = []
    rendered: list[str] = []
    for tool in tools:
        schema = _schema(tool)
        dumped = json.dumps(schema, separators=(",", ":"), ensure_ascii=False)
        desc = tool.description or ""
        #: Ce que le modele voit pour cet outil : nom + description + schema.
        block = f"{tool.name}\n{desc}\n{dumped}"
        rendered.append(block)
        rows.append(
            {
                "name": tool.name,
                "schema_chars": len(dumped),
                "schema_tokens": count_tokens(dumped),
                "description_chars": len(desc),
                "description_tokens": count_tokens(desc),
                "block_tokens": count_tokens(block),
                "params": sorted(schema.get("properties", {}).keys()),
            }
        )

    blob = "".join(rendered)
    return {
        "tools": rows,
        "total_schema_chars": sum(r["schema_chars"] for r in rows),
        #: Cout reel : token-count de TOUT ce que le client charge, pas des
        #: noms de parametres ni d'une liste de tailles.
        "access_tokens": count_tokens(blob),
        "access_chars": len(blob),
        "total_description_tokens": sum(r["description_tokens"] for r in rows),
    }


def main() -> int:
    result = asyncio.run(measure())
    for row in result["tools"]:
        print(
            f"{row['name']:22} schema={row['schema_chars']:5} car "
            f"({row['schema_tokens']:4} tok)  desc={row['description_chars']:4} car "
            f"({row['description_tokens']:4} tok)  params={','.join(row['params'])}"
        )
    print("-" * 72)
    print(
        f"TOTAL schemas = {result['total_schema_chars']} car  "
        f"| descriptions = {result['total_description_tokens']} tok  "
        f"| COUT D ACCES REEL = {result['access_tokens']} tok ({result['access_chars']} car)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
