# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-31

First public release.

### Added

- **6 MCP tools** (`plan`, `precheck`, `observe`, `recall`, `checkpoint`, `handoff`),
  stable table (invariant: the exposed tool array never changes, it is part of
  the cached prefix).
- **Server-side payload filtering** (`recall(op=…)`): `grep`, `range`, `head`,
  `tail`, `outline`, `aggregate`, `jsonl` — the agent only pays for the slice
  it selects, not for the whole payload.
- **Honest ledger**: `tokens_moved` (payload relocated to a ref) is tracked
  separately from `tokens_saved` (proved by the agent's withdrawal
  acknowledgement or by a measured filtered access). Enforced invariant:
  `tokens_saved ≤ tokens_in + tokens_moved`.
- **Cache-aware pruning**: the prune moves, never deletes; `cache_mort_probability`
  is a threshold (0 before TTL, 1 after), and the elapsed time is measured from
  the event journal.
- **Append-only decision/constraint queue** with rewrite detection
  (`verdict: critical`, `cause: pinned_rewrite`, `semantic_break: true`).
- **LoopGuard** (duplicate and loop protection), **precheck** (invariants,
  budget, duplicate refusal with `suggest_alternative`).
- **Context pressure** (`plan(mode="status")`), **reversible compaction**
  (`checkpoint(mode="compact"|"trim"|"clear")`).
- **MCP resources** (`osiris://task/{task_id}/manifest`, `osiris://task/{task_id}/status`,
  `osiris://ref/{ref}`) and the `osiris/task-resume` prompt.
- **Control Plane dashboard** (`osiris-dashboard`): live KPIs, ledger, integrity.
- **Verified benchmarks** (`bench/run_bench.py`): the README §10 table is
  regenerated from the real bench output, never hand-written.

### Notes

- Measured on the reference machine: +15 % (800 tok prompt) to +71 % (20 000 tok
  prompt) net context reduction; access cost 1 019 tokens of tool schemas.
- A server-side filter cannot replace an LLM, and an MCP server cannot shrink
  the host's context window retroactively: OSIRIS provides the artefacts, the
  host decides.
