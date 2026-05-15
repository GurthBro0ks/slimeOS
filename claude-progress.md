# SlimyOS Progress

## Session: Live Runtime Mission Control

- Added a live runtime status collector and wired Mission Control to display real runtime state by default.
- Added dashboard API endpoint `GET /api/runtime` and included runtime payload in `GET /api/state`.
- Added service, broker, audit, proof-pack, panic, approval, and Hermes status checks.
- Added Hermes fallback behavior: unreachable `/v1/models` reports `auth_required_or_proxy_down` as WARN, not FAIL.
- Added runtime collector unit tests and a live smoke script with proof artifact capture.

## Proof

- Latest proof directory: `/tmp/proof_slimyos_live_runtime_20260515T153726Z`
- Smoke result: `PASS`

## Notes

- `/home/slimy/*` paths are not writable on this machine; updates were recorded in this repository instead.

## Session: Client Adapter Preflight + Sync Proof

- Synced runtime wiring commit `13dfe214affbd772d3b710a035af352c971af7a3` to `origin/main` and verified remote contains the commit.
- Added client adapter preflight module and script:
  - `adapters/client_preflight.py`
  - `scripts/preflight-agent-clients.sh`
- Preflight validates broker/dashboard reachability, health/tool count, safe tool call success, blocked raw shell, blocked restart_service(sshd), and gated git_commit behavior.
- Hermes proxy/auth remains WARN-only (`auth_required_or_proxy_down`) and does not fail preflight.
- Added unit tests for preflight behavior in `tests/test_client_preflight.py`.

## Proof

- Client preflight proof directory: `/tmp/proof_slimyos_client_preflight_20260515T154235Z`
- Client preflight result: `PASS`
- Live runtime smoke result during this checkpoint: `PASS`
- Checkpoint commit: `838a5220b351f912b2f2f0c4d74507bed88ba161`

## Session: MCP Bridge (Local Stdio)

- Added local MCP bridge adapter: `adapters/mcp_server.py`.
- Added MCP launcher script: `scripts/run-mcp-server.sh`.
- Added MCP smoke script: `scripts/smoke-mcp-bridge.sh`.
- Added MCP bridge tests: `tests/test_mcp_bridge.py`.
- Added MCP client docs/examples under `docs/mcp/` for Claude Desktop, Claude Code, OpenCode, and Codex.
- Verified MCP bridge keeps policy path intact by preserving blocked and approval-gated responses from Tool Broker.

## Proof

- MCP bridge proof directory: `/tmp/proof_slimyos_mcp_bridge_20260515T155114Z`
- MCP bridge smoke result: `PASS`
- MCP tool count observed: `43`

## Session: MCP Doctor + Healthline

- Added operator-facing dry-run doctor script: `scripts/slimyos-mcp-doctor.sh`.
- Added reusable helper module: `adapters/mcp_doctor.py`.
- Added compact status command: `scripts/slimyos-mcp-healthline.sh`.
- Added test coverage for doctor logic: `tests/test_mcp_doctor.py`.
- Doctor now generates proof artifacts and client config snippets without mutating live configs by default.

## Proof

- MCP doctor proof directory: `/tmp/proof_slimyos_mcp_doctor_20260515T161044Z`
- MCP doctor result: `PASS`
- MCP healthline output: `SlimyOS MCP: PASS | broker=ok tools=43 dashboard=ok claude=found codex=found opencode=found hermes=warn/auth_required_or_proxy_down policy=blocked_raw_shell`

## Session: MCP Client Config Apply + Rollback

- Added safe MCP client config installer: `scripts/slimyos-mcp-configure.sh`.
- Added helper module: `adapters/mcp_configure.py`.
- Added smoke test: `scripts/smoke-mcp-configure.sh`.
- Added test coverage: `tests/test_mcp_configure.py` (25 tests).
- Modes: dry-run (default), --write-snippets, --apply, --rollback, --status.
- Claude Desktop: safe merge of mcpServers with backup, validation, and rollback.
- Claude Code, OpenCode, Codex: classified as MANUAL_REQUIRED (not FAIL).
- Safety: default is dry-run (no mutation), --apply requires explicit flag, every apply creates timestamped backup, every changed config is JSON validated, --rollback restores latest backup.
- No secrets, no provider login, no raw shell, no privileged changes.

## Proof

- MCP configure smoke proof directory: generated per run in `/tmp/proof_slimyos_mcp_configure_smoke_<UTC>/`
- All 42 unit tests pass (including 25 new configure tests).

## Client Support Matrix

| Client | Status | Notes |
|---|---|---|
| Claude Desktop | Supported | Merge mcpServers, backup, validate, rollback |
| Claude Code | MANUAL_REQUIRED | No safe file-based config path detected |
| OpenCode | MANUAL_REQUIRED | No safe file-based config path detected |
| Codex | MANUAL_REQUIRED | No safe file-based config path detected |

## Session: Real Claude Desktop MCP Config Apply

- Performed first real SlimyOS MCP config install into Claude Desktop.
- Config path: `~/.config/Claude/claude_desktop_config.json`
- Existing mcpServers (`google-drive`, `gmail`) preserved.
- SlimyOS MCP entry merged in successfully.
- Backup created at `~/.config/slimyos/backups/mcp-config/20260515T165757Z`.
- JSON validation passed after write.
- No Claude Code, OpenCode, or Codex configs modified.
- All verification scripts pass: doctor, healthline, bridge smoke.
- Rollback available via `./scripts/slimyos-mcp-configure.sh --rollback`.

## Proof

- Real apply proof directory: `/tmp/proof_slimyos_real_claude_desktop_apply_20260515T165623Z`
- Apply result: `PASS`
- All 9 verification checks passed.
- mcpServers before: `google-drive, gmail`
- mcpServers after: `google-drive, gmail, slimyos`
