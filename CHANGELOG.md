# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-11-01

### Fixed

- **P0 — Adaptive threshold recalibration** (`adaptive.py`): thresholds
  (`BYSTANDER_BELOW_TOKENS`, `EXTERNALIZE_MIN_TOKENS`, `MANIFEST_MIN_TOKENS`)
  now recalibrate from the last N ledger tasks via median + 75th percentile,
  bounded downward to floors. `reset_thresholds()` added for test isolation.
- **P1 — Conditional schema access** (`server.py`): `_record_schema_access`
  now imputes schema cost only when OSIRIS is engaged (bystander retracts);
  measurement is lazy and cached in `adaptive.SCHEMA_ACCESS_TOKENS`.
- **P2 — Token estimation calibration** (`tokens.py`): `update_calibration()`
  measures tiktoken/cl100k_base exact count vs `chars/4` heuristic, tracks a
  global ratio and sample count for confidence intervals.
- **P3 — Stale ref pruning + storage cost** (`refs.py`, `ledger.py`): `prune_expired()`
  removes only refs with expired TTL (optionally only never-relisted);
  `storage_cost()` and `tokens_moved_exact()` added; prune runs in the
  compaction checkpoint branch.
- **P4 — Loop credit at proven reuse** (`ledger.py`): `credit_loop_savings`
  credits duplicates only after provable reuse, respecting the
  "no credit without acknowledgement" invariant. Wired into the `final` branch.
- **P5 — Unified net-gain policy** (`decision.py`, new module): `net_gain(task_id)`
  returns `{proved_savings, loop_savings, overhead, storage} → net`; exposed
  in `plan(mode="status")`.
- **Dashboard auto-refresh** (`app.js`): default interval lowered to 2 s;
  2 s option added to the settings dropdown.
- **AGENTS.md / README.md**: test count updated (77 → 99); bench table
  refreshed from the latest `run_bench.py` output (access cost 1 038 tok,
  net gate +972 tok, +71.48 % at 20 000 tok).

### Added

- `src/osiris/core/decision.py` — net-gain computation module (P5).
- `tests/test_delta.py` — 18 validation tests covering P0–P5.
- `DASHBOARDS-GUIDE.md` — quickstart for the Osiris and IcyLoom dashboards.

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
