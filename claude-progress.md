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

## Session: Claude Desktop MCP Post-Install Verification

- Added post-install verifier: `scripts/verify-claude-desktop-mcp.sh`.
- Added helper module: `adapters/claude_desktop_verify.py`.
- Added smoke test: `scripts/smoke-claude-desktop-mcp.sh`.
- Added test coverage: `tests/test_claude_desktop_verify.py` (18 tests).
- Verifier reads real Claude Desktop config, confirms SlimyOS entry exists, validates launcher path, runs live MCP checks (initialize, tools/list, safe call, blocked raw_shell, gated restart_service), checks broker health before/after, detects Claude Desktop process, generates redacted proof artifacts.
- Redacts env values that look secret-like (keys, tokens, passwords).
- Does not read or expose private Claude chat content.
- Does not automate Claude Desktop GUI interaction.
- Manual operator prompt generated: "Restart Claude Desktop, then ask it: Use the SlimyOS MCP tools to list the allowed repo directory and summarize the policy result."

## Proof

- Live verification proof directory: `/tmp/proof_slimyos_claude_desktop_live_20260515T170832Z`
- Verification result: `PASS`
- Config parses, existing servers preserved (google-drive, gmail), SlimyOS entry present.
- Launcher path valid and executable.
- MCP tool count: 43
- Safe call: success
- Blocked call disposition: blocked
- Gated call disposition: blocked
- Claude Desktop process: running
- All 60 unit tests pass (including 18 new verify tests).
- All smoke/verification scripts pass.

## Session: Fix MCP Bridge for Claude Desktop Compatibility

- Claude Desktop showed `invalid_union / invalid input` errors when loading SlimyOS MCP.
- Root cause: MCP server responses had non-standard fields rejected by Claude Desktop's Zod schema.
- Fixed `adapters/mcp_server.py`:
  - Removed `timestamp` and `hostname` from error objects (only `code`, `message`, `data` allowed).
  - Removed `x_slimyos` extra key from tool definitions.
  - Removed `structuredContent` from tools/call responses (Claude Desktop doesn't expect it).
  - Added notification detection: messages without `id` produce no response.
  - Added `notifications/initialized` handling (silent).
  - Added `ping` method support.
  - Added exception handling in stdio loop (errors go to stderr, not stdout).
  - All logs/diagnostics go to stderr only. stdout is protocol-only.
- Updated all downstream code to parse broker results from `content[0].text` instead of `structuredContent`:
  - `adapters/mcp_doctor.py`
  - `adapters/claude_desktop_verify.py`
  - `scripts/smoke-mcp-bridge.sh`
  - `tests/test_mcp_bridge.py`
  - `tests/test_mcp_doctor.py`
- Added Claude-style protocol smoke test: `scripts/smoke-claude-mcp-protocol.sh`.
- Added 7 new unit tests for strict MCP compliance (string id, numeric id, notification, ping, unknown method, content shape, no extra keys).
- 67 unit tests all pass.

## Proof

- Claude MCP protocol smoke: `/tmp/proof_slimyos_claude_mcp_protocol_20260515T172447Z`
- Result: PASS
- String id preservation: PASS
- Numeric id preservation: PASS
- Notification produces no response: PASS
- Stdout purity (all lines valid JSON-RPC): PASS
- No raw error leakage: PASS
- No extra keys in tool definitions: PASS
- No structuredContent in responses: PASS

## Session: Real-Client Verification Proof Pack

- Added real-client proof generator: `adapters/prove_claude_desktop_client.py`.
- Added proof script: `scripts/prove-claude-desktop-client.sh`.
- Added test coverage: `tests/test_prove_claude_desktop_client.py` (20 tests, all pass).
- Script inspects SlimyOS audit logs for evidence of Claude Desktop GUI tool calls.
- Found explicit `claude-desktop` agent_id/agent_runtime in audit:
  - Event: `list_directory` with disposition `allowed`
  - Policy rule: `tool_overrides.list_directory.disposition`
  - Files changed: none
  - Safety: no raw_shell, no file mutations, no privileged restarts
- Supports `--recent` mode (inspect existing audit) and `--watch N` mode (wait for fresh event).
- Does not read Claude chats, scrape Claude Desktop content, or automate GUI.
- Does not invent client identity; explicitly classifies as `explicit_claude_desktop` or `inferred`.
- All 87 unit tests pass.
- All verification scripts pass: smoke-live-runtime, preflight-agent-clients, smoke-mcp-bridge, slimyos-mcp-doctor, slimyos-mcp-healthline, smoke-mcp-configure, smoke-claude-desktop-mcp, verify-claude-desktop-mcp, smoke-claude-mcp-protocol, prove-claude-desktop-client.

## Proof

- Real-client proof directory: `/tmp/proof_slimyos_claude_desktop_real_client_20260516T145939Z`
- Result: PASS
- Matching audit event found: yes
- Client identity: explicit_claude_desktop (high confidence)
- Policy rule: tool_overrides.list_directory.disposition
- Operation disposition: allowed
- Files modified: no
- Unsafe actions: none

## Session: Client Identity / Session Visibility

- Added client identity model: `adapters/client_identity.py`.
  - Stable identity envelope: client_id, client_name, client_kind, transport, session_id, request_id, user_visible_source, started_at, repo_path.
  - Predefined identities for Claude Desktop, Claude Code, OpenCode, Codex.
  - Reads from environment variables for MCP bridge context.
  - Privacy rule: never includes private chat text.
- Updated MCP bridge: `adapters/mcp_server.py`.
  - Every `tools/call` now attaches `client_identity` metadata to the Tool Broker payload.
  - Identity built from `SLIMYOS_MCP_AGENT_ID`, `SLIMYOS_MCP_AGENT_NAME`, `SLIMYOS_MCP_AGENT_KIND`, `SLIMYOS_MCP_TRANSPORT` env vars.
- Updated Tool Broker: `services/slimy-toold/broker.py`.
  - `call()` method now accepts optional `client_identity` dict.
  - Passes client_identity through to all audit log calls (request, blocked, allowed, executed, failed, approval_required).
  - Fully backward compatible: old callers omitting client_identity still work.
- Updated Audit Logger: `services/slimy-auditd/logger.py`.
  - `log()` method now accepts optional `client_identity` dict.
  - Writes `client_identity` field into every audit event.
  - Empty/default when not provided (backward compatible).
- Updated API server: `serve.py`.
  - POST `/tools/<name>` extracts `client_identity` from request body and passes to broker.
- Updated Dashboard / Mission Control: `dashboard/mission_control.py` and `dashboard/runtime_status.py`.
  - Runtime status collector now extracts `recent_client_activity`, `clients_seen`, and `last_claude_desktop_event` from audit events.
  - Client activity includes: timestamp, client name, transport, tool name, disposition badge, policy rule, files modified flag, unsafe action flag, short result summary.
  - Dashboard HTML now includes a "Recent Client Activity" panel with dark/neon styling.
  - API endpoints `/api/runtime` and `/api/state` include the new fields.
- Updated proof script: `adapters/prove_claude_desktop_client.py`.
  - `infer_client_identity()` now prefers explicit `client_identity` metadata in audit events.
  - Falls back to legacy `agent_id`/`agent_runtime` inference when metadata absent.
  - Does not invent identity; clearly labels source as `audit_event.client_identity` or `inferred`.
- Added smoke test: `scripts/smoke-client-identity.sh`.
  - Makes safe MCP tool call through bridge.
  - Verifies audit event includes client_id, client_name, transport.
  - Verifies runtime API includes recent_client_activity and clients_seen.
  - Verifies raw_shell remains blocked.
  - Verifies no secrets or chat text are stored in audit.
- Added test coverage: `tests/test_client_identity.py` (15 tests, all pass).
  - Tests client identity model (default, roundtrip, predefined, from_env).
  - Tests inference logic (prefers metadata, falls back, inferred, does not invent).
  - Tests audit log inclusion and backward compatibility.
  - Tests privacy (no chat text in identity or audit).
  - Tests runtime status extraction (activity, clients_seen, last_claude_desktop_event).
- All 102 unit tests pass.
- All verification scripts pass.

## Proof

- Client identity smoke proof directory: `/tmp/proof_slimyos_client_identity_20260516T153438Z`
- Result: PASS
- Audit event includes client_identity: yes
- Client identity fields: client_id=claude_desktop, client_name=Claude Desktop, transport=mcp_stdio
- Runtime API includes recent_client_activity: yes
- Runtime API includes clients_seen: yes
- raw_shell blocked: yes
- Privacy clean: yes (no chat text, no secrets)

## Session: Mission Control Approval Request Visibility

- Added approval request model and in-memory approval queue in `services/slimy-toold/broker.py`.
  - Fields now include: `approval_id`, `request_id`, `client_identity`, `tool_name`, `requested_args_summary`, `requested_args_redacted`, `disposition`, `policy_rule`, `risk_level`, timestamps, decision metadata, `audit_event_id`, `proof_ref`.
  - Secret-like values are redacted before audit storage.
  - Private chat-like fields are omitted from stored args (`private_fields_omitted` count recorded).
- Integrated Tool Broker approval flow:
  - On `approval_required`, broker now creates a pending approval request, audits it, returns `approval_id` to caller, and does not execute the gated tool.
  - Approval decision recording added: `approved_pending_manual_execution` or `denied`.
- Updated API server (`serve.py`):
  - `GET /state` now includes `pending_approvals`, `approvals_recent`, and approval counts.
  - Added `GET /approvals`.
  - Added `POST /deny` and updated `POST /approve` to use `approval_id`.
  - Unknown `approval_id` returns safe error (`unknown_approval_id`).
- Updated Mission Control UI (`dashboard/mission_control.py`):
  - Pending Approvals panel now shows client identity, transport, tool, policy rule, risk badge, args summary, created timestamp, and audit reference.
  - Added approve/deny controls wired to `/api/approve` and `/api/deny`.
  - Added recent approval decision note area.
- Updated runtime status collector (`dashboard/runtime_status.py`) to include approval events in recent client activity extraction.
- Added proof script `scripts/smoke-approval-flow.sh`:
  - Runs isolated local broker/dashboard on ports `3303/3302` by default.
  - Verifies gated MCP call returns `approval_required` + `approval_id`.
  - Verifies pending approval appears in Mission Control state.
  - Verifies deny and approve decisions update status safely.
  - Verifies no `git_commit` execution occurs and git HEAD does not change.
  - Verifies audit includes client identity + policy rule and keeps chat text/secrets out.
  - Verifies `raw_shell` remains blocked.
- Added tests `tests/test_approval_flow.py` (8 tests):
  - approval creation on policy gate
  - approval id returned
  - pending approval appears in state
  - deny never executes tool
  - approve records decision
  - unknown approval id safe failure
  - client identity preserved + secret redaction
  - no chat text/secret leakage + raw_shell blocked

## Proof

- Approval flow smoke proof directory: `/tmp/proof_slimyos_approval_flow_20260516T161153Z`
- Result: PASS
- Full unit suite: `python3 -m unittest discover -s tests` -> `110 tests PASS`
- Full verification/smoke suite rerun PASS (Hermes remains WARN `auth_required_or_proxy_down`)

## Session: Approved Execution (Safe Test-Lane Only)

- Added approved execution state model fields to approval requests in `services/slimy-toold/broker.py`:
  - `execution_status`, `execution_started_at`, `execution_finished_at`, `execution_result_summary`, `execution_audit_event_id`, `execution_proof_ref`, `execution_error`, `one_time_use`, `used`.
- Added strict approved-execution endpoint support:
  - Broker method: `execute_approved(...)`
  - API route: `POST /execute-approved` in `serve.py`
  - Dashboard proxy route: `POST /api/execute-approved` in `dashboard/mission_control.py`
- Safety gates for approved execution:
  - Requires `approval_id`, approved status, explicit confirm token (`execute-approved-test-lane`), one-time-use, and args snapshot match.
  - Only allowlisted tool: `git_commit`.
  - Only allowlisted path lane prefixes: `/tmp/proof_slimyos_approved_execution_*` and `/tmp/slimyos_approved_execution_demo_*`.
  - Refuses denied/expired/non-approved/unknown/missing/already-used/args-mismatch/outside-lane/unsafe-tool calls.
  - Refusals are audited with `approval_execution_refused`.
- Added audited execution lifecycle:
  - `approval_execution_start`
  - `approval_execution_finish`
  - runtime proof artifact writer for executed requests.
- Updated Mission Control approval panel:
  - Shows execution status and result/refusal info.
  - Shows `Execute Approved Test-Lane Action` button only for safe eligible approvals.
  - Keeps non-eligible approvals manual (`approved_pending_manual_execution` display).
- Added smoke script `scripts/smoke-approved-execution.sh`:
  - Builds disposable demo repo under proof dir.
  - Verifies end-to-end approved execution for gated `git_commit` only in test lane.
  - Verifies no mutation of real SlimyOS repo.
  - Verifies one-time-use, denied refusal, args mismatch refusal, raw_shell blocked, and privacy redaction.
  - Writes required proof bundle artifacts.
- Added tests `tests/test_approved_execution.py` and updated `tests/test_approval_flow.py`:
  - Missing/unknown/denied/already-used refusal paths.
  - Unsafe tool refusal.
  - Outside-lane refusal.
  - Args mismatch refusal.
  - Successful test-lane `git_commit` execution.
  - Execution audit start/finish presence.
  - No chat text persistence and raw_shell block evidence.

## Proof

- Approved execution smoke proof directory: `/tmp/proof_slimyos_approved_execution_20260516T162811Z`
- Result: PASS
- Full unit suite after changes: `python3 -m unittest discover -s tests` -> `120 tests PASS`
- Full verification suite PASS:
  - smoke-live-runtime
  - preflight-agent-clients
  - smoke-mcp-bridge
  - slimyos-mcp-doctor
  - slimyos-mcp-healthline
  - smoke-mcp-configure
  - smoke-claude-desktop-mcp
  - verify-claude-desktop-mcp
  - smoke-claude-mcp-protocol
  - prove-claude-desktop-client --recent
  - smoke-client-identity
  - smoke-approval-flow
  - smoke-approved-execution

## Session: Real Claude Desktop Gated Approval Pending-Card Proof Workflow

- Added helper module: `adapters/prove_claude_gated_approval.py`.
  - `prepare` mode performs broker/dashboard/config/policy checks, captures approval+audit baselines, writes manual prompt, emits proof artifacts, and returns `PENDING_MANUAL` when ready for operator action.
  - `watch` mode polls for new `approval_required` gated requests and verifies all required evidence before PASS:
    - `client_identity.client_id == claude_desktop`
    - `tool_name == git_commit` (or configured gated tool)
    - `approval_id` exists
    - approval status remains `pending`
    - Mission Control/API exposes matching pending approval card
    - no `execution_status == executed`
    - real SlimyOS repo unchanged
  - Includes privacy/safety checks: no chat-text storage and secret-like value redaction checks.
- Added proof script: `scripts/prove-claude-gated-approval.sh`.
  - Modes: `--prepare`, `--watch`, `--watch-seconds`, URL overrides, proof-dir override.
  - Writes required proof pack artifacts under `/tmp/proof_slimyos_claude_gated_approval_<UTC>/`.
- Added smoke script: `scripts/smoke-claude-gated-approval.sh`.
  - Validates PASS path with fake Claude pending approval, PENDING_MANUAL path, missing identity FAIL, executed-status FAIL, and unredacted-secret FAIL.
  - Confirms no real Claude Desktop config mutation.
- Added tests: `tests/test_prove_claude_gated_approval.py` (9 tests).
  - covers detection, approval_id/pending requirements, pending-card visibility checks, execution guard, repo mutation guard, PENDING_MANUAL behavior, redaction and chat-text checks.
- Updated `README.md` and `feature_list.json` with runbook, prompt, result semantics, privacy guarantees, rollback command, and intentional no-execution boundary for Claude-originated requests.

## Proof

- New smoke proof directory: `/tmp/proof_slimyos_claude_gated_approval_smoke_20260516T171919Z`
- Smoke result: `PASS`
- Prepare proof directory (local services): `/tmp/proof_slimyos_claude_gated_approval_20260516T171939Z`
- Prepare result: `PENDING_MANUAL`
- Watch proof directory (no manual Claude request issued): `/tmp/proof_slimyos_claude_gated_approval_20260516T171951Z`
- Watch result: `PENDING_MANUAL`
- Full unit suite after change: `python3 -m unittest discover -s tests` -> `129 tests PASS`

## Session: Claude Gated Approval Identity Propagation Fix

- Investigated live pending approval and audit for `approval_id=bfedb844-72f5-4457-b692-501434260da1`.
  - Found legacy identity fields in pending approval:
    - `client_id=claude-desktop`
    - `client_name=claude-desktop`
    - `transport=claude-desktop`
  - Watcher was correctly strict (`client_identity_not_claude_desktop`) and rejected this legacy identity shape.
- Root cause:
  - MCP bridge accepted legacy aliases without canonical normalization.
  - Generated Claude Desktop MCP config snippets used legacy env values (`claude-desktop`) that propagated into approval records.
- Fixes implemented:
  - `adapters/mcp_server.py`:
    - Added known-client identity normalization for Claude Desktop aliases.
    - Canonical output now uses:
      - `client_id=claude_desktop`
      - `client_name=Claude Desktop`
      - `transport=mcp_stdio`
    - Payload `agent_id` and `agent_runtime` now follow normalized identity values.
    - Runtime default now prefers `SLIMYOS_MCP_TRANSPORT`.
  - `adapters/mcp_configure.py` + `adapters/mcp_doctor.py`:
    - Updated generated Claude Desktop MCP env to canonical values:
      - `SLIMYOS_MCP_AGENT_ID=claude_desktop`
      - `SLIMYOS_MCP_AGENT_NAME=Claude Desktop`
      - `SLIMYOS_MCP_AGENT_KIND=desktop_app`
      - `SLIMYOS_MCP_TRANSPORT=mcp_stdio`
      - `SLIMYOS_MCP_AGENT_RUNTIME=mcp_stdio`
  - `adapters/prove_claude_gated_approval.py` + `scripts/prove-claude-gated-approval.sh`:
    - Watch mode now inspects only *new* events/approvals (avoids stale pre-fix false FAIL on old pending approvals).
    - Added richer diagnostic output: approval_id, client_identity, tool_name, original_tool_name, policy_rule, approval_status, failure reasons.
    - Preserves normalized `tool_name` while exposing `original_tool_name`.
  - Expanded tests/smoke coverage for missing/unknown identity, executed status, and repo-change fail path.

## Proof

- Legacy (pre-fix) live pending approval still present and unchanged:
  - `bfedb844-72f5-4457-b692-501434260da1` (legacy identity fields)
- New fixture/live check approval after fix:
  - `3eff8d90-9a4a-4f5a-bbf7-f07c286896f2`
  - `client_identity.client_id=claude_desktop`
  - `client_identity.client_name=Claude Desktop`
  - `client_identity.transport=mcp_stdio`
  - `disposition=approval_required`, `policy_rule=require_approval`, `status=pending`
- Identity-fix proof bundle:
  - `/tmp/proof_slimyos_claude_gated_identity_fix_20260516T175535Z`
  - `RESULT=PASS`
- Watcher sanity after fix without fresh manual request:
  - `/tmp/proof_slimyos_claude_gated_approval_20260516T175628Z`
  - `RESULT=PENDING_MANUAL` (expected; no new manual Claude request issued)
- Full unit suite after fix:
  - `python3 -m unittest discover -s tests` -> `132 tests PASS`
