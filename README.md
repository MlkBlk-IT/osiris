<p align="center">
  <img src="https://raw.githubusercontent.com/MlkBlk-IT/osiris/main/docs/mlkblk-banner-v2.svg" width="100%" alt="OSIRIS — Cache-aware context engine & state governor for AI agents" />
</p>

# OSIRIS

[![PyPI](https://img.shields.io/pypi/v/mcp-osiris?style=flat-square)](https://pypi.org/project/mcp-osiris/)
[![npm](https://img.shields.io/npm/v/osiris-mcp?style=flat-square)](https://www.npmjs.com/package/osiris-mcp)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

**Cache-aware context engine & state governor for AI agents.** Standard MCP server, local-first, independent of any model provider.

> OSIRIS makes AI agents cheaper, faster, and more reliable: fewer tokens, fewer loops, zero unnecessary tools, and zero loss of context.
## What's new — 2026-11-03

| Change | What it means |
|---|---|
| **P0–P5 landed** | Adaptive thresholds, conditional schema, token calibration, reference pruning, loop credit and the net-gain module. |
| **Dashboard rebuilt** | Liquid UI, live updates, plus concurrency and ledger tests. |
| **Stale task pointer cleared** | `get_task` now drops the current-task pointer when the task no longer exists. |
| **v0.1.1 is still WIP** | The release stays blocked until validation (deadline 2026-11-08). |

OSIRIS does not replace your other MCP servers (filesystem, Git, GitHub, shell, browser…). It **coexists** alongside them and drastically cuts what they cost in prompt context.

---

## 1. The Core Architectural Constraint

An MCP server **never sees** the final prompt assembled by the client host. It only sees what the agent sends to it. Therefore, OSIRIS cannot:

| What we would want | What a standard MCP server can actually do |
|---|---|
| Write directly into the prompt | Produce canonical state and **have the agent carry it** |
| Erase past conversation turns | Decide what to externalize **for future turns** |
| Hide another MCP server's tools | **Recommend** via Tool Compass |
| Hard-cap prompt tokens | Block an **action** (invariants, budget enforcement) |

The promise is honest: OSIRIS provides **stable state and an enforceable safety contract**, not a client prompt builder.

---

## 2. Sealed Manifest — The Core Design

`osiris.plan` returns a deterministic block (~120 tokens) that the agent carries at a fixed position in its context window:

```text
OSIRIS/1 task=7c3f obj="fix PowerShell profile bug" plan=3/7
inv=4 files=6 refs=9 dec=2 budget=ok
SEAL=sha256:3f9a1c…c21b
```

The `SEAL` is a SHA256 digest of stable zones. The agent passes it on every turn to `osiris.observe`: OSIRIS recomputes and detects any state drift immediately.

**This is OSIRIS's passive transport**: even if the agent stops calling tools, it carries the essential state cleanly.

### Three Hashes Because Prompt Cache is Prefix-Based

```
head_hash   = sha256(system_head ‖ rules)                       immutable
zoneB_hash  = sha256(objective ‖ global_plan ‖ tool_contract)   quasi-stable
tail_hash   = sha256(constraints ‖ pinned_decisions)           append-only
prefix_hash = sha256(head_hash ‖ zoneB_hash)                   ← cached prefix
zoneA_hash  = sha256(head_hash ‖ tail_hash)                    ← full ZONE A
```

| Change | Verdict | Cache Cost |
|---|---|---|
| `head_hash` | **CRITICAL DRIFT** | Full re-prefill |
| `zoneB_hash` | Minor drift | Re-prefill delta only |
| `tail_hash` (append) | **Normal growth** | Re-prefill delta only |
| Pinned item **rewritten** | **CRITICAL DRIFT (semantic)** | Cache intact, task state corrupted |

> **Appending** a constraint or decision changes `tail_hash` but **not** `prefix_hash`: the prompt cache holds, only the new tokens are prefilled.
>
> **Rewriting** a pinned decision is explicitly caught: OSIRIS checks collection identity, flagging a semantic break (`semantic_break: true`, `cause: pinned_rewrite`).

---

## 3. The 6 MCP Tools

Access footprint: **1,019 tokens** of schemas and descriptions in model context (measured via `bench/run_bench.py`). Paid on task start, amortized across the session — pays off on the very first turn with ≥800 token payloads.

| Tool | Role | Typical Response |
|---|---|---|
| `osiris.plan` | Start / update / resume / status of a task; produces sealed manifest | ~160 tok |
| `osiris.precheck` | Authorize or deny an action (invariants, budget, deduplication) | ~70 tok |
| `osiris.observe` | Log actions, loop detection, offload large data, update memory | ~50 tok |
| `osiris.recall` | Rehydrate refs (**server-side filtered**: grep, range, outline) | variable |
| `osiris.checkpoint` | Snapshot, resume, completion report, reversible compaction | ~80 tok |
| `osiris.handoff` | Executable delegation contracts and structured results | ~200 tok |

`osiris.observe` combines logging, loop protection, payload externalization, memory registry, and automated pruning in a single call so the agent always reports back seamlessly.

### Extended Operations

| Call | Behavior |
|---|---|
| `osiris.observe(kind="dropped", result=<ref>)` | **Drop receipt**: agent confirms payload was evicted from prompt → token savings are **proven** and credited |
| `osiris.observe(kind="head"\|"contract", result=…)` | Records system prompt head / client contract and detects cache-busting volatile tokens (timestamps, UUIDs) |
| `osiris.recall(op="grep"\|"range"\|"head"\|"tail"\|"outline"\|"aggregate"\|"jsonl")` | **Server-side filtering**: only requested matches enter the context window |
| `osiris.plan(mode="status")` | Context pressure breakdown (measured vs declared vs unknown) |
| `osiris.checkpoint(mode="compact"\|"trim"\|"clear")` | Reversible session compaction preparation |
| `osiris.precheck` → `suggest_alternative` | Active collision resolution for duplicate operations |

### Resources & Prompts

- `osiris://task/{task_id}/manifest` — Active zones, drift status, objective
- `osiris://task/{task_id}/status` — Real-time context pressure
- `osiris://ref/{ref}` — Raw byte content of any referenced payload
- Prompt `osiris/task-resume` — Clean agent recovery template after crashes

---

## 4. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Agent (Claude Code, Cursor, MiniMax Code, Codex, Cline…)   │
│  Context: system │ tools │ OSIRIS MANIFEST │ history         │
└───────────────────────────┬──────────────────────────────────┘
                            │  MCP stdio — 6 tools, ~1,019 tok schema
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  osiris-mcp  (server.py)                                     │
│  plan · precheck · observe · recall · checkpoint · handoff   │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  core/                                                        │
│   task_state  Typed TaskState (objective, plan, decisions)    │
│   memory     Typed memory registry by kind and scope         │
│   refs       Content-addressed store (verified on read)      │
│   prefix     Zones, 3-hash system, drift, PrefillPlan        │
│   prune      Reversible externalization, 4 modes             │
│   query      Server-side payload filtering (grep, range...)  │
│   compaction trim / compact / clear (lossless)               │
│   pressure   Context pressure metrics & tracking             │
│   loopguard  Fingerprinting, 5 loop patterns detection       │
│   invariants TOML rule engine (guard rails)                  │
│   compass    Tool Compass (dynamic relevance scoring)        │
│   handoff    Executable agent delegation contracts           │
│   events     Append-only event journal + checkpoints         │
│   ledger     Tokens / cost / savings / OSIRIS overhead       │
│   fileops    Sandboxed file inspection (roots, size limits)  │
│   redact     Secret scrubbing before any hashing             │
│   policy     Budget policies & token enforcement             │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
        ~/.osiris/osiris.db  +  ~/.osiris/reports/
```

---

## 5. Memory Model

Deterministic, typed, content-addressable memory — **not** an opaque vector database.

```
TaskState
├── objective      immutable
├── constraints[]  append-only
├── decisions[]    append-only, pinned verbatim
├── plan           completed / active / remaining steps
├── files{}        path, SHA-256 hash, mtime, last access, ref
├── tool_results{} cache_key, ref, size, token cost, TTL
├── failures{}     error signature, tool, args hash, attempts, lesson
├── lessons[]      general behavioral rules learned
├── handoffs{}     cross-agent delegation contracts
└── budget         estimated vs consumed tokens and cost
```

Scopes: `task` → `project` → `agent` → `global`.

---

## 6. Cache-Aware Pruning

**Security Invariant: Pruning moves payload data to content-addressed refs (`mem://sha256:…`). It NEVER deletes.**

```
ZONE_A_pruning_cost = pruned_tokens
ZONE_C_or_D_pruning_cost = 0                      ← always zero cost
net_savings = pruned_tokens − (prefix_tokens × P(cache_dead) × prefix_pruned)
```

| Mode | Trigger | Evicts | Cache Impact | Use Case |
|---|---|---|---|---|
| `cache_ttl` (default) | `Δt > TTL` | C/D, and A/B only if cache expired | Neutral | **Recommended default** |
| `conservative` | Very high threshold | Working zone (C/D) only | Zero | High-cost API models |
| `balanced` | Moderate threshold | C/D + cold historical turns | Zero | Standard agent workflows |
| `aggressive` | Low threshold | Everything rehydratable | Minor prefill risk | Fast local LLMs |

---

## 7. LoopGuard Protection

```
fingerprint = sha256(tool ‖ canonical_args ‖ result_signature)
```

| Detection | Trigger Signal | Verdict |
|---|---|---|
| Exact duplicate | Identical fingerprint | `suggest_alternative` |
| Repeated failure | Same error signature (≥3 times) | `block` + `required_action` |
| Loop pattern | Same error across varying args | `warn` |
| Oscillation | Alternating A/B/A/B pattern | `warn` |
| Runaway | N calls with zero state progress | `warn` / `block` |

---

## 8. Invariants (Guard Rails)

Define project safety rules in `.osiris/invariants.toml`:

```toml
[[invariant]]
id = "tests-before-commit"
when = { tool = "git.commit" }
require = { state = "tests_passed" }
message = "Cannot commit while tests are failing"

[[invariant]]
id = "no-test-edit"
when = { path_glob = "tests/**" }
verdict = "block"
message = "Modifying test suites requires explicit approval"
```

---

## 9. Lossless Verification & Non-Loss Proof

OSIRIS guarantees full auditability for offloaded data:

1. **Self-verifying refs**: `mem://sha256:<hash>`. Reads re-verify data integrity against the hash before returning.
2. **Zero deletion paths**: data is relocated to the local store, never pruned permanently.
3. **Reproducible audit**:
   ```bash
   python -m osiris audit --task <task_id>
   ```
   Outputs cryptographic proof of non-loss:
   ```json
   {"lossless": true, "items_externalized": 14, "items_verified": 14, "items_missing": 0, "integrity_violations": []}
   ```

---

## 10. Verified Benchmarks

Real measurements from `python bench\run_bench.py` running an automated coding workflow:

| Payload Size | Baseline Context | Fixed OSIRIS | Adaptive OSIRIS | Net Improvement | OSIRIS Mode | Overhead |
|---|---|---|---|---|---|---|
| **200 tok** | 1,583 | 2,669 | **1,649** | **−4.17%** | bystander | 33 tok |
| **800 tok** | 3,851 | 3,751 | **3,255** | **+15.48%** | light | 1,808 tok |
| **2,000 tok** | 9,015 | 5,215 | **5,230** | **+41.99%** | standard | 2,494 tok |
| **5,000 tok** | 20,979 | 8,164 | **8,162** | **+61.09%** | standard | 2,434 tok |
| **20,000 tok** | 82,135 | 23,423 | **23,423** | **+71.48%** | full | 2,412 tok |

- **Access Cost**: 1,038 tokens of schemas, amortized across session tasks.
- **Session Net Gate**: PASS (Worst-case net across full suite: **+972 tokens**).
- **At 20,000 tokens**: **+71.48% net savings** on context usage.

---

## 11. Quick Start

```powershell
cd D:\MCP-Osiris
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
```

### CLI Verification

```powershell
.venv\Scripts\python.exe -m pytest tests -q        # Run test suite (117 passed)
.venv\Scripts\python.exe -m ruff check src tests    # Code linting
.venv\Scripts\python.exe -m osiris health           # Server health check
.venv\Scripts\python.exe -m osiris audit --task t_1 # Cryptographic non-loss proof
.venv\Scripts\python.exe bench\run_bench.py         # Reproduce benchmarks
```

### Registration as MCP Server

Add to your client configuration (`mcp.json`):

```json
{
  "mcpServers": {
    "osiris": {
      "command": "D:\\mcp-osiris\\.venv\\Scripts\\python.exe",
      "args": ["-m", "osiris"],
      "env": {
        "OSIRIS_HOME": "C:\\Users\\Tech\\.osiris",
        "OSIRIS_ROOTS": "D:\\mcp-osiris"
      }
    }
  }
}
```

---

## 12. Installation

### From PyPI (recommended)

```bash
pip install mcp-osiris          # or: uv pip install mcp-osiris
mcp-osiris                      # runs the MCP server on stdio
osiris health                   # CLI verification
osiris-dashboard --port 8770    # Control Plane (dashboard)
```

### From npm (no Python setup)

```bash
npx -y osiris-mcp
```

The npm package is a stdio launcher. It resolves the Python runtime in this
order — `OSIRIS_PYTHON` → `uvx` → `python3` → `python` — and runs the PyPI
package `mcp-osiris`.

### From source

```powershell
git clone https://github.com/MlkBlk-IT/osiris.git
cd osiris
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
```

### MCP client configuration

```json
{
  "mcpServers": {
    "osiris": {
      "command": "npx",
      "args": ["-y", "osiris-mcp"],
      "env": {
        "OSIRIS_HOME": "~/.osiris",
        "OSIRIS_ROOTS": "/path/to/project"
      }
    }
  }
}
```

| Variable | Default | Role |
|---|---|---|
| `OSIRIS_HOME` | `~/.osiris` | SQLite database, reports, caches |
| `OSIRIS_ROOTS` | *(empty)* | Roots allowed for file reading (`;` separated) |
| `OSIRIS_CACHE_TTL_S` | `300` | Cache TTL (seconds) |
| `OSIRIS_PRUNE_THRESHOLD_TOKENS` | `40000` | Prune threshold |
| `OSIRIS_DISPATCH_ONLY` | `0` | `1` → exposes only `osiris.call` |

---

## License

MIT © 2026 Malik Belkacemi (MLKBLK-IT)
