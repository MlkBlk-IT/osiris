"""Tests de `recall op=count` : compteur seul, ~3 tokens."""

from __future__ import annotations

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


async def _observe(client):
    payload = "\n".join(
        [f"2026-10-31T22:00:00Z INFO ligne {i} sans importance" for i in range(60)]
        + [f"2026-10-31T22:00:0{i} ERROR un vrai probleme {i}" for i in range(8)]
    )
    await client.call_tool("osiris.plan", {"objective": "count", "context_tokens": 5000})
    obs = _data(await client.call_tool("osiris.observe", {"kind": "payload", "result": payload}))
    return obs["ref"]


async def _count(client, ref, query):
    return _data(
        await client.call_tool("osiris.recall", {"ref": ref, "op": "count", "query": query})
    )


async def test_count_returns_number_of_matching_lines(client):
    ref = await _observe(client)
    rec = await _count(client, ref, "ERROR")
    assert rec["found"] is True
    assert rec["op"] == "count"
    assert rec["matches"] == 8
    item = rec["items"][0]
    assert item["text"] == "8"
    assert item["total_lines"] == 68
    assert item["truncated"] is False
    assert item["tokens"] <= 5


async def test_count_supports_regex_and_ignores_case(client):
    ref = await _observe(client)
    assert (await _count(client, ref, "error"))["matches"] == 8
    assert (await _count(client, ref, r"^2026-10-31T22:00:0\d ERROR"))["matches"] == 8
    assert (await _count(client, ref, "^2026"))["matches"] == 68


async def test_count_falls_back_to_literal_on_invalid_regex(client):
    ref = await _observe(client)
    rec = await _count(client, ref, "(")
    assert rec["found"] is True
    assert rec["matches"] == 0


async def test_count_with_empty_query_is_a_noop(client):
    ref = await _observe(client)
    rec = await _count(client, ref, "")
    assert rec["found"] is True
    assert rec["items"][0]["text"] == ""
    assert "matches" not in rec or rec["matches"] == 0