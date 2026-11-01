"""Tests de fumee : le serveur MCP demarre et expose exactement 6 outils."""

from __future__ import annotations

from fastmcp import Client

from osiris.server import mcp

EXPECTED_TOOLS = {
    "osiris.plan",
    "osiris.precheck",
    "osiris.observe",
    "osiris.recall",
    "osiris.checkpoint",
    "osiris.handoff",
}


async def test_server_exposes_exactly_six_tools() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
    assert {tool.name for tool in tools} == EXPECTED_TOOLS


async def test_plan_is_callable() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("osiris.plan", {"objective": "fumee"})
    data = result.data
    assert data["task_id"]
    assert "OSIRIS/1" in data["manifest"]
