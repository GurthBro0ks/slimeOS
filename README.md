# 🐌 SlimyOS Habitat

**A supervised autonomous Linux control plane where agents can research, code, browse, sandbox, assist, create proof packs, learn from failures, and be stopped or rolled back instantly.**

SlimyOS is not an AI desktop. It is not a chatbot shell. It is not a YOLO agent box.

SlimyOS is a **command center for trustworthy autonomy.**

## Core Principle

> The OS does not care which model is thinking.
> The OS only cares what the agent is allowed to do.

## What SlimyOS Is

A portable Linux overlay (runs on Mint, Ubuntu, Arch, NixOS) that provides:

| Component | Purpose |
|---|---|
| `slimy-policyd` | Deterministic policy engine — what is allowed, blocked, escalated, or sandboxed |
| `slimy-toold` | Tool broker — named, scoped, audited actions instead of raw shell |
| `slimy-auditd` | Append-only event logging with tamper detection |
| `slimy-proofd` | HTML proof pack generator — screenshots, diffs, timelines, pass/fail |
| `slimy-panicd` | Emergency stop — halt all agents, dump state, snapshot (future) |
| `slimy-snapshotd` | Btrfs/ZFS snapshot management before destructive ops (future) |
| `slimy-dashboard` | Mission Control web UI (future) |
| `slimy-phone` | Phone approval PWA (future) |

## What SlimyOS Is Not

- Not a new kernel or init system
- Not hardwired to any specific model or framework
- Not a self-modifying OS
- Not an unrestricted agent runtime

## Supported Agent Runtimes (all replaceable)

Hermes Agent, Claude Code, Codex CLI, OpenCode, Goose, Ollama, browser-use, trycua/cua, LangGraph, CrewAI, custom scripts.

None of these are the core. They are clients.

## Quick Start

```bash
# Clone
git clone https://github.com/slimyai/slimyos.git
cd slimyos

# Install (Python 3.10+)
pip install -e .

# Run smoke test
./scripts/smoke-test.sh

# See example proof pack
open examples/proof-pack/index.html
```

## Mission Control (Live Runtime)

Start the Tool Broker and Mission Control:

```bash
python3 serve.py
python3 dashboard/mission_control.py
```

Open Mission Control at `http://localhost:3002`.
The live runtime API is available at `http://localhost:3002/api/runtime`.

Mission Control now prioritizes real machine state and reports:
- `slimyos-toold` and `slimyos-dashboard` service status
- Broker health and loaded tool count
- Policy/manifest availability
- Audit/proof-pack paths and recent events
- Hermes installation and proxy connectivity
- Pending approvals with client identity, policy rule, risk, and redacted arg summary

Approval visibility is now first-class:
- Gated tools (for example `git_commit`) return `approval_required` with `approval_id`
- Tool Broker records a pending approval request (no tool execution yet)
- Mission Control shows a Pending Approvals card with approve/deny controls
- API endpoints:
  - `GET /state` (includes `pending_approvals`, `approvals_recent`)
  - `GET /approvals`
  - `POST /approve` with `approval_id`
  - `POST /deny` with `approval_id`
  - `POST /execute-approved` with `approval_id` + `confirm=execute-approved-test-lane`

Current checkpoint behavior is intentionally conservative:
- Approval decisions are recorded as `approved` or `denied`
- Approve alone does not execute any tool
- Approved execution is test-lane only (safe disposable repos under `/tmp/proof_slimyos_approved_execution_*`)
- Only `git_commit` is allowlisted for approved execution in this checkpoint
- `approval_id` is one-time-use for execution
- Non-test-lane approvals stay manual (`approved_pending_manual_execution` in Mission Control UI)
- Privacy rule remains enforced: no private chat text stored in approval/audit payloads
- Secret-like args are redacted before audit storage

If Hermes is installed but not authenticated or not running, status appears as
`auth_required_or_proxy_down` (WARN). This does not fail core runtime health.

Manual next step for Hermes (not automated by SlimyOS):

```bash
hermes login nous
# or login to your preferred provider
```

Re-run live runtime smoke verification:

```bash
./scripts/smoke-live-runtime.sh
```

Run client adapter preflight:

```bash
./scripts/preflight-agent-clients.sh
```

Run approval-flow smoke proof:

```bash
./scripts/smoke-approval-flow.sh
```

This validates end-to-end approval visibility (gated MCP call, pending approval state,
deny/approve recording, raw-shell block evidence, privacy redaction) without executing
destructive host actions.

Run approved execution smoke proof (safe test lane only):

```bash
./scripts/smoke-approved-execution.sh
```

This validates approve + execute flow in a disposable demo repo, verifies one-time-use
execution semantics, refusal paths (already used / denied / args mismatch / unsafe tool),
audit start/finish events, privacy redaction, and that the real SlimyOS repo is untouched.

Run MCP bridge smoke verification:

```bash
./scripts/smoke-mcp-bridge.sh
```

Run MCP doctor (dry-run by default):

```bash
./scripts/slimyos-mcp-doctor.sh
```

Run MCP healthline (compact operator status):

```bash
./scripts/slimyos-mcp-healthline.sh
```

Dry-run MCP client config detection (no mutation):

```bash
./scripts/slimyos-mcp-configure.sh
```

Write generated config snippets to `docs/generated/` (no user config mutation):

```bash
./scripts/slimyos-mcp-configure.sh --write-snippets
```

Safely apply MCP config for supported clients (Claude Desktop) with backup:

```bash
./scripts/slimyos-mcp-configure.sh --apply
```

Rollback to latest backup:

```bash
./scripts/slimyos-mcp-configure.sh --rollback
```

Show current config status (no mutation):

```bash
./scripts/slimyos-mcp-configure.sh --status
```

Verify real Claude Desktop MCP install (read-only, no mutation):

```bash
./scripts/verify-claude-desktop-mcp.sh
```

Client preflight is non-privileged, read-only, and does not require secrets,
provider login, or API keys. It validates that external clients can discover
and call SlimyOS through the broker and that dangerous/raw-shell paths remain
blocked or approval-gated.

`WARN` indicates optional dependencies are not fully connected. Example:
Hermes `auth_required_or_proxy_down` means Hermes is installed but local proxy
auth/connectivity is not ready yet. Core SlimyOS control plane can still pass.

Manual operator step when needed:

```bash
hermes login nous
# or your preferred provider login
```

## MCP Bridge (Local Stdio)

Start local MCP bridge server:

```bash
./scripts/run-mcp-server.sh
```

This MCP bridge is intentionally minimal and safe:
- Supports `initialize`, `ping`, `notifications/initialized`, `tools/list`, and `tools/call`
- Strict JSON-RPC 2.0 over stdio; stdout is protocol-only, logs go to stderr
- Proxies every call to `http://localhost:3003` Tool Broker
- Preserves policy outcomes (`allowed`, `blocked`, `approval_required`)
- Fails closed if Tool Broker is unreachable
- Compatible with Claude Desktop's MCP client parser

What is intentionally not automated yet:
- Provider logins (including Hermes auth)
- Secret management and API key injection
- Privileged host changes
- Browser account login automation

MCP doctor and healthline do not require secrets or provider login. They only
validate local broker-backed MCP wiring and preserve policy enforcement through
Tool Broker.

MCP configure provides safe client config apply and rollback:

```bash
# Dry-run: detect config paths, generate snippets (no mutation)
./scripts/slimyos-mcp-configure.sh

# Write generated snippets to docs/generated/ only
./scripts/slimyos-mcp-configure.sh --write-snippets

# Apply config for supported clients (Claude Desktop) with backup
./scripts/slimyos-mcp-configure.sh --apply

# Rollback to latest backup
./scripts/slimyos-mcp-configure.sh --rollback

# Show current config status (no mutation)
./scripts/slimyos-mcp-configure.sh --status
```

Default mode is always dry-run. `--apply` requires explicit flag, creates a
timestamped backup, and validates JSON after write. `--rollback` restores the
latest backup. Unsupported/uncertain clients stay `MANUAL_REQUIRED`, not FAIL.

After applying Claude Desktop config, verify the live install:

```bash
./scripts/verify-claude-desktop-mcp.sh
```

This verifies: config parses, existing servers preserved, SlimyOS entry present,
launcher path valid, MCP initialize/tools-list/safe-call/blocked-call/gated-call
all work, Tool Broker healthy, policy evidence intact. Read-only; no mutation.

If Claude Desktop fails to load MCP after apply, rollback:

```bash
./scripts/slimyos-mcp-configure.sh --rollback
```

Hermes auth is unrelated to Claude Desktop MCP bridge — the MCP server connects
to Tool Broker directly over localhost.

Test Claude Desktop MCP protocol compatibility:

```bash
./scripts/smoke-claude-mcp-protocol.sh
```

This verifies string/numeric id preservation, notification handling, stdout purity,
no extra keys in responses, and proper JSON-RPC error shape.

Portability note: some harnesses use `/home/slimy/*` paths, but many developer
machines run as different users (for example, Mint user `mint`). Project
scripts are written to stay portable and should prefer repository-local
artifacts when `/home/slimy` paths are unavailable or unwritable.

## Project Structure

```
slimyos/
├── docs/              # Architecture, threat model, roadmap
├── schemas/           # JSON schemas for all data types
├── services/          # Core services (policyd, toold, auditd, proofd)
├── policies/          # Policy files (default, dev-machine, nuc-agent)
├── tools/manifests/   # Tool definitions
├── gates/             # CI/CD safety gates
├── scripts/           # Install, smoke test, utilities
├── examples/          # Example proof packs
└── tests/             # Integration tests
```

## Phased Roadmap

| Phase | What | Status |
|---|---|---|
| 0 | Planning + threat model + schemas | ✅ |
| 1 | Portable overlay skeleton | ✅ |
| 2 | Policy engine + tool broker | ✅ |
| 3 | Coding Room | 🔲 |
| 4 | Browser Room | 🔲 |
| 5 | Sandbox Room | 🔲 |
| 6 | Mission Control Dashboard | 🔲 |
| 7 | Phone Supervisor | 🔲 |
| 8 | Host Desktop Room | 🔲 |
| 9 | Arch/Hyprland SlimyOS Edition | 🔲 |

## License

MIT
