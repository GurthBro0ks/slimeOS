#!/bin/bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UTC_NOW="$(date -u +%Y%m%dT%H%M%SZ)"
DEFAULT_PROOF_DIR="/tmp/proof_slimyos_approval_flow_${UTC_NOW}"
PROOF_DIR="${1:-${SLIMYOS_APPROVAL_PROOF_DIR:-$DEFAULT_PROOF_DIR}}"
START_LOCAL_SERVICES="${SLIMYOS_APPROVAL_LOCAL_SERVICES:-1}"
BROKER_PORT="${SLIMYOS_APPROVAL_BROKER_PORT:-3303}"
DASHBOARD_PORT="${SLIMYOS_APPROVAL_DASHBOARD_PORT:-3302}"
BROKER_URL="${SLIMYOS_TOOLD_URL:-http://localhost:${BROKER_PORT}}"
DASHBOARD_URL="${SLIMYOS_DASHBOARD_URL:-http://localhost:${DASHBOARD_PORT}}"

mkdir -p "$PROOF_DIR"
exec > >(tee "$PROOF_DIR/smoke_output.txt") 2>&1

echo "SlimyOS approval flow smoke test"
echo "Project root: $PROJECT_ROOT"
echo "Proof dir: $PROOF_DIR"
echo "Broker URL: $BROKER_URL"
echo "Dashboard URL: $DASHBOARD_URL"

ERRORS=()

TOOLD_PID=""
DASHBOARD_PID=""

cleanup() {
  if [[ -n "$DASHBOARD_PID" ]]; then
    kill "$DASHBOARD_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "$TOOLD_PID" ]]; then
    kill "$TOOLD_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ "$START_LOCAL_SERVICES" == "1" ]]; then
  echo "Starting local broker + dashboard for approval smoke"
  SLIMYOS_TOOLD_PORT="$BROKER_PORT" python3 "$PROJECT_ROOT/serve.py" > "$PROOF_DIR/local_toold.log" 2>&1 &
  TOOLD_PID="$!"

  SLIMYOS_PORT="$DASHBOARD_PORT" SLIMYOS_TOOLD_URL="$BROKER_URL" \
    python3 "$PROJECT_ROOT/dashboard/mission_control.py" > "$PROOF_DIR/local_dashboard.log" 2>&1 &
  DASHBOARD_PID="$!"

  python3 - "$BROKER_URL" "$DASHBOARD_URL" <<'PY'
import json
import sys
import time
from urllib import request, error

broker_url, dashboard_url = sys.argv[1:3]

def wait(url, label):
    for _ in range(40):
        try:
            with request.urlopen(url, timeout=1.0) as resp:
                data = json.loads(resp.read())
            if data.get("status") == "ok":
                return
        except Exception:
            time.sleep(0.25)
    raise SystemExit(f"timeout waiting for {label}: {url}")

wait(f"{broker_url}/health", "broker")
wait(f"{dashboard_url}/health", "dashboard")
PY
  if [[ $? -ne 0 ]]; then
    ERRORS+=("local_service_start_failed")
  fi
fi

HEAD_BEFORE="$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || true)"
git -C "$PROJECT_ROOT" status --porcelain > "$PROOF_DIR/git_status_before.txt" 2>&1 || true

call_mcp_tool() {
  local tool_name="$1"
  local args_json="$2"
  local request_id="$3"
  python3 - "$PROJECT_ROOT" "$BROKER_URL" "$tool_name" "$args_json" "$request_id" <<'PY'
import json
import os
import subprocess
import sys

project_root, broker_url, tool_name, args_json, request_id = sys.argv[1:6]
arguments = json.loads(args_json)

env = dict(os.environ)
env["SLIMYOS_TOOLD_URL"] = broker_url
env["SLIMYOS_MCP_AGENT_ID"] = "claude_desktop"
env["SLIMYOS_MCP_AGENT_NAME"] = "Claude Desktop"
env["SLIMYOS_MCP_AGENT_KIND"] = "desktop_app"
env["SLIMYOS_MCP_TRANSPORT"] = "mcp_stdio"
env["SLIMYOS_MCP_REQUEST_ID"] = request_id

proc = subprocess.Popen(
    [f"{project_root}/scripts/run-mcp-server.sh"],
    cwd=project_root,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    env=env,
)

def rpc(payload):
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline().strip()
    if not line:
        return {}
    return json.loads(line)

try:
    rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    result = rpc({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    })
finally:
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()

content = result.get("result", {}).get("content", [])
structured = {}
if content:
    try:
        structured = json.loads(content[0].get("text", "{}"))
    except json.JSONDecodeError:
        structured = {"error": "invalid_json_content", "raw": content[0].get("text", "")[:200]}

print(json.dumps({"mcp_result": result, "tool_result": structured}, indent=2))
PY
}

echo ""
echo "=== Step 1: First gated MCP tool call (git_commit) ==="
CALL1_JSON="$(call_mcp_tool "slimyos_git_commit" "{\"repo_path\": \"$PROJECT_ROOT\", \"message\": \"approval flow dry run\", \"access_token\": \"super-secret-token-1234567890\", \"chat_text\": \"private chat text should never be stored\"}" "approval-flow-req-1")"
printf '%s\n' "$CALL1_JSON" > "$PROOF_DIR/mcp_gated_call_1.json"

python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path

proof_dir = Path(sys.argv[1])
payload = json.loads((proof_dir / "mcp_gated_call_1.json").read_text())
tool = payload.get("tool_result", {})
(proof_dir / "tool_result_1.json").write_text(json.dumps(tool, indent=2))

if tool.get("disposition") != "approval_required":
    raise SystemExit(f"git_commit should be approval_required, got {tool.get('disposition')}")
approval_id = tool.get("approval_id", "")
if not approval_id:
    raise SystemExit("approval_id missing from gated response")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("first_gated_call_failed")
fi

APPROVAL_ID_1="$(python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path
tool = json.loads((Path(sys.argv[1]) / "tool_result_1.json").read_text())
print(tool.get("approval_id", ""))
PY
)"

echo ""
echo "=== Step 2: Verify runtime and mission-control state exposes pending approval ==="
curl -sS "$DASHBOARD_URL/api/state" > "$PROOF_DIR/dashboard_state_pending.json" || ERRORS+=("dashboard_state_fetch_failed")

python3 - "$PROOF_DIR" "$APPROVAL_ID_1" <<'PY'
import json
import sys
from pathlib import Path

proof_dir = Path(sys.argv[1])
approval_id = sys.argv[2]
state = json.loads((proof_dir / "dashboard_state_pending.json").read_text())
pending = state.get("pending_approvals", [])
if not any(item.get("approval_id") == approval_id for item in pending):
    raise SystemExit("pending approval not present in mission control state")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("pending_approval_missing_from_state")
fi

echo ""
echo "=== Step 3: Deny approval and verify denied state ==="
curl -sS -X POST "$DASHBOARD_URL/api/deny" \
  -H "Content-Type: application/json" \
  -d "{\"approval_id\": \"$APPROVAL_ID_1\"}" > "$PROOF_DIR/deny_response_1.json" || ERRORS+=("deny_endpoint_failed")

python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path

proof_dir = Path(sys.argv[1])
resp = json.loads((proof_dir / "deny_response_1.json").read_text())
if not resp.get("ok"):
    raise SystemExit(f"deny did not succeed: {resp}")
approval = resp.get("approval", resp.get("request", {}))
if approval.get("status") != "denied":
    raise SystemExit(f"approval should be denied, got {approval.get('status')}")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("deny_verification_failed")
fi

echo ""
echo "=== Step 4: Second gated request + approve decision ==="
CALL2_JSON="$(call_mcp_tool "slimyos_git_commit" "{\"repo_path\": \"$PROJECT_ROOT\", \"message\": \"approval flow dry run second\", \"api_key\": \"abc1234567890supersecret\"}" "approval-flow-req-2")"
printf '%s\n' "$CALL2_JSON" > "$PROOF_DIR/mcp_gated_call_2.json"

python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path

proof_dir = Path(sys.argv[1])
payload = json.loads((proof_dir / "mcp_gated_call_2.json").read_text())
tool = payload.get("tool_result", {})
(proof_dir / "tool_result_2.json").write_text(json.dumps(tool, indent=2))
if tool.get("disposition") != "approval_required":
    raise SystemExit(f"second git_commit should be approval_required, got {tool.get('disposition')}")
if not tool.get("approval_id"):
    raise SystemExit("second approval_id missing")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("second_gated_call_failed")
fi

APPROVAL_ID_2="$(python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path
tool = json.loads((Path(sys.argv[1]) / "tool_result_2.json").read_text())
print(tool.get("approval_id", ""))
PY
)"

curl -sS -X POST "$DASHBOARD_URL/api/approve" \
  -H "Content-Type: application/json" \
  -d "{\"approval_id\": \"$APPROVAL_ID_2\"}" > "$PROOF_DIR/approve_response_2.json" || ERRORS+=("approve_endpoint_failed")

python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path

proof_dir = Path(sys.argv[1])
resp = json.loads((proof_dir / "approve_response_2.json").read_text())
if not resp.get("ok"):
    raise SystemExit(f"approve did not succeed: {resp}")
approval = resp.get("approval", resp.get("request", {}))
if approval.get("status") not in {"approved", "approved_pending_manual_execution", "approved_but_execution_not_implemented"}:
    raise SystemExit(f"unexpected approve status: {approval.get('status')}")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("approve_verification_failed")
fi

echo ""
echo "=== Step 5: Verify no tool execution and no host mutation ==="
HEAD_AFTER="$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || true)"
git -C "$PROJECT_ROOT" status --porcelain > "$PROOF_DIR/git_status_after.txt" 2>&1 || true

if [[ "$HEAD_BEFORE" != "$HEAD_AFTER" ]]; then
  ERRORS+=("git_head_changed_unexpectedly")
fi

curl -sS "$BROKER_URL/audit/recent" > "$PROOF_DIR/audit_recent.json" || ERRORS+=("audit_recent_fetch_failed")

python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path

proof_dir = Path(sys.argv[1])
events = json.loads((proof_dir / "audit_recent.json").read_text()).get("events", [])

executed_git_commit = [
    e for e in events
    if e.get("event_type") == "tool_executed" and e.get("tool_name") == "git_commit"
]
if executed_git_commit:
    raise SystemExit("git_commit should not execute during approval visibility smoke")

approval_events = [e for e in events if e.get("event_type") == "approval_requested"]
if not approval_events:
    raise SystemExit("missing approval_requested audit event")

latest = approval_events[-1]
ci = latest.get("client_identity", {}) or {}
if not ci.get("client_id"):
    raise SystemExit("approval audit event missing client_identity.client_id")
if not latest.get("policy_rule"):
    raise SystemExit("approval audit event missing policy_rule")

all_text = json.dumps(events).lower()
if "private chat text should never be stored" in all_text:
    raise SystemExit("chat text leaked into audit events")
if "super-secret-token-1234567890" in all_text:
    raise SystemExit("secret token leaked into audit events")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("audit_verification_failed")
fi

echo ""
echo "=== Step 6: Verify raw_shell remains blocked ==="
RAW_BLOCK_JSON="$(call_mcp_tool "slimyos_raw_shell" "{\"command\": \"rm -rf /\"}" "approval-flow-raw-shell")"
printf '%s\n' "$RAW_BLOCK_JSON" > "$PROOF_DIR/mcp_raw_shell_check.json"

python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path

proof_dir = Path(sys.argv[1])
payload = json.loads((proof_dir / "mcp_raw_shell_check.json").read_text())
tool = payload.get("tool_result", {})
if tool.get("disposition") != "blocked":
    raise SystemExit(f"raw_shell should be blocked, got {tool.get('disposition')}")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("raw_shell_not_blocked")
fi

echo ""
echo "=== Step 7: Unknown approval id safe error ==="
curl -sS -X POST "$DASHBOARD_URL/api/deny" \
  -H "Content-Type: application/json" \
  -d '{"approval_id":"does-not-exist"}' > "$PROOF_DIR/deny_unknown.json" || ERRORS+=("deny_unknown_call_failed")

python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path

proof_dir = Path(sys.argv[1])
resp = json.loads((proof_dir / "deny_unknown.json").read_text())
if resp.get("ok") is True:
    raise SystemExit("unknown approval id should not succeed")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("deny_unknown_not_safe")
fi

python3 - "$PROOF_DIR" "$PROJECT_ROOT" "$BROKER_URL" "$DASHBOARD_URL" <<'PY' > "$PROOF_DIR/meta.json"
import json
import sys
from datetime import datetime, timezone

proof_dir, project_root, broker_url, dashboard_url = sys.argv[1:5]
meta = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "proof_dir": proof_dir,
    "project_root": project_root,
    "broker_url": broker_url,
    "dashboard_url": dashboard_url,
    "checks": [
        "gated_call_returns_approval_required",
        "approval_id_present",
        "pending_approval_visible_in_state",
        "deny_records_denied",
        "approve_records_pending_manual_execution",
        "no_git_commit_execution",
        "audit_has_client_identity_and_policy_rule",
        "chat_and_secret_redaction",
        "raw_shell_blocked",
        "unknown_approval_id_safe_error",
    ],
}
print(json.dumps(meta, indent=2))
PY

if [[ ${#ERRORS[@]} -eq 0 ]]; then
  echo "RESULT=PASS" > "$PROOF_DIR/RESULT.txt"
  echo "Approval flow smoke PASSED"
else
  echo "RESULT=FAIL" > "$PROOF_DIR/RESULT.txt"
  echo "Approval flow smoke FAILED"
  for err in "${ERRORS[@]}"; do
    echo "- $err"
  done
fi

cat "$PROOF_DIR/RESULT.txt"
echo "Approval flow proof directory: $PROOF_DIR"

if [[ ${#ERRORS[@]} -eq 0 ]]; then
  exit 0
fi
exit 1
