# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.2] - 2026-11-06

### Fixed

- **npm publication (E404)** (`.github/workflows/publish.yml`): the `npm` job
  used `actions/setup-node` with `registry-url`, which writes
  `//registry.npmjs.org/:_authToken=${NODE_AUTH_TOKEN}` into `.npmrc`. With no
  `NPM_TOKEN` secret that line expands to an **empty** token: npm assumed
  credentials were configured, **skipped the OIDC token exchange**, and sent an
  anonymous `PUT` -> `404 Not Found` (root cause of the failed `v0.1.1`
  release). `registry-url` is removed, npm is pinned to `npm@11` (trusted
  publishing needs >= 11.5.1; npm 12 introduced a "staged version" mode where a
  published version stays invisible), and the OIDC exchange is now verified
  **before** the publish, so a missing Trusted Publisher fails with the exact
  remedy instead of a misleading 404. The published version is also verified
  against the registry afterwards.
- **Dashboard network exposure** (`dashboard/server.py`): the dashboard listened
  on any `--host` without authentication, while `/api/memory`, `/api/events`,
  `/api/refs` and `/api/config` disclose local data. A non-loopback bind is now
  refused unless `--allow-remote` is passed, and `--allow-remote` requires a
  token (`--token` or `OSIRIS_DASHBOARD_TOKEN`). API routes return `401` without
  a valid token (accepted via `Authorization: Bearer` or `?token=`).
- **Wheel resources** (`pyproject.toml`): `dashboard/web/liquid.css` and
  `dashboard/web/live.js` were referenced by `index.html` but missing from the
  wheel's `force-include`, so an installed dashboard had broken CSS and no live
  layer.
- **Version drift** (`config.py`): `settings.version` reported `0.1.0` while
  `pyproject.toml` was at `0.1.1`.
- **LoopGuard escalation** (`loopguard.py`, `policy.py`, `server.py`):
  exact duplicates now escalate `suggest_alternative -> warn (3) -> block (5)`
  instead of suggesting forever; `precheck` returns `deny` past the block
  threshold.
- **Structured plan constraints** (`invariants.py`, `server.py`):
  `{"deny": [...], "allow": [...]}` JSON constraints are now evaluated by
  `precheck` (`verdict="deny"`, invariant + required_action); free text is
  kept as an unapplied note.
- **Handoff ref leak** (`server.py`): the contract no longer auto-collects
  every observed payload; refs are explicit or tied to the mission's files
  (default empty).
- **Honest lossless** (`audit.py`, `server.py`): checkpoint returns
  `integrity="unverified"` when `items_verified == 0` instead of claiming
  `lossless`; `lossless` now requires a real hash re-read.
- **Dashboard honesty** (`dashboard/server.py`): integrity shows `UNVERIFIED`
  (not `VIOLATION`) when nothing was verified; the loopguard "blocked" list
  uses the policy block threshold instead of a hardcoded 3.

### Changed

- **Versioned migrations** (`core/db.py`): the schema is now versioned by
  `PRAGMA user_version`. Each migration is numbered, transactional and replayed
  only once. The blanket `except sqlite3.OperationalError: pass` was replaced
  by an explicit column-existence check, so a genuine schema error propagates
  instead of being swallowed -- a database can no longer start with a
  half-applied migration.
- **CI matrix** (`.github/workflows/ci.yml`): tests now run on
  `ubuntu-latest` **and** `windows-latest`, on Python **3.12 and 3.13**
  (the project supports `>=3.12` and documents Windows usage).
- **Wheel smoke test** (`.github/workflows/ci.yml`): a dedicated job builds the
  wheel, installs it in a clean environment, and checks the `osiris` /
  `osiris-dashboard` commands, the packaged resources and the benchmark gate --
  the artefacts users actually install, not only the source tree.

### Added

- `tests/test_db_migrations.py` -- 8 migration tests (legacy upgrade, idempotence,
  rollback, non-swallowed errors).
- `tests/test_dashboard_exposure.py` -- 14 exposure tests (loopback policy,
  token verification, real HTTP `401`/`200`).
- `tests/test_bugs_4.py` -- 7 red->green regression tests (124 total).

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
