#!/bin/bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UTC_NOW="$(date -u +%Y%m%dT%H%M%SZ)"
PROOF_DIR="${1:-/tmp/proof_slimyos_approved_execution_${UTC_NOW}}"
BROKER_PORT="${SLIMYOS_APPROVED_EXEC_BROKER_PORT:-3403}"
DASHBOARD_PORT="${SLIMYOS_APPROVED_EXEC_DASHBOARD_PORT:-3402}"
BROKER_URL="http://localhost:${BROKER_PORT}"
DASHBOARD_URL="http://localhost:${DASHBOARD_PORT}"
SLIMY_HOME="$PROOF_DIR/slimy_home"

mkdir -p "$PROOF_DIR"
mkdir -p "$SLIMY_HOME"
exec > >(tee "$PROOF_DIR/smoke_output.txt") 2>&1

echo "SlimyOS approved execution smoke test"
echo "Project root: $PROJECT_ROOT"
echo "Proof dir: $PROOF_DIR"
echo "Broker URL: $BROKER_URL"
echo "Dashboard URL: $DASHBOARD_URL"

ERRORS=()
WARNINGS=()
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
    return json.loads(line) if line else {}

try:
    rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    result = rpc({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    })
finally:
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()

content = result.get("result", {}).get("content", [])
tool_result = {}
if content:
    try:
        tool_result = json.loads(content[0].get("text", "{}"))
    except json.JSONDecodeError:
        tool_result = {"error": "invalid_json_content", "raw": content[0].get("text", "")[:200]}

print(json.dumps({"mcp_result": result, "tool_result": tool_result}, indent=2))
PY
}

echo "Starting local broker + dashboard"
SLIMYOS_HOME="$SLIMY_HOME" SLIMYOS_TOOLD_PORT="$BROKER_PORT" \
  python3 "$PROJECT_ROOT/serve.py" > "$PROOF_DIR/local_toold.log" 2>&1 &
TOOLD_PID="$!"

SLIMYOS_HOME="$SLIMY_HOME" SLIMYOS_PORT="$DASHBOARD_PORT" SLIMYOS_TOOLD_URL="$BROKER_URL" \
  python3 "$PROJECT_ROOT/dashboard/mission_control.py" > "$PROOF_DIR/local_dashboard.log" 2>&1 &
DASHBOARD_PID="$!"

python3 - "$BROKER_URL" "$DASHBOARD_URL" <<'PY'
import json
import sys
import time
from urllib import request

broker_url, dashboard_url = sys.argv[1:3]

def wait(url):
    for _ in range(60):
        try:
            with request.urlopen(url, timeout=1.0) as resp:
                payload = json.loads(resp.read())
            if payload.get("status") == "ok":
                return True
        except Exception:
            time.sleep(0.25)
    return False

if not wait(f"{broker_url}/health"):
    raise SystemExit("broker_health_timeout")
if not wait(f"{dashboard_url}/health"):
    raise SystemExit("dashboard_health_timeout")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("local_service_start_failed")
fi

REAL_HEAD_BEFORE="$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || true)"
git -C "$PROJECT_ROOT" status --porcelain > "$PROOF_DIR/real_repo_status_before.txt" 2>&1 || true

DEMO_REPO="$PROOF_DIR/demo_repo"
echo "$DEMO_REPO" > "$PROOF_DIR/demo_repo_path.txt"

mkdir -p "$DEMO_REPO"
git -C "$DEMO_REPO" init >/dev/null 2>&1 || ERRORS+=("demo_git_init_failed")
git -C "$DEMO_REPO" config user.email "slimyos-demo@example.local" >/dev/null 2>&1 || ERRORS+=("demo_git_config_email_failed")
git -C "$DEMO_REPO" config user.name "SlimyOS Demo" >/dev/null 2>&1 || ERRORS+=("demo_git_config_name_failed")

printf 'base\n' > "$DEMO_REPO/demo.txt"
git -C "$DEMO_REPO" add demo.txt >/dev/null 2>&1 || ERRORS+=("demo_git_add_initial_failed")
git -C "$DEMO_REPO" commit -m "initial demo commit" >/dev/null 2>&1 || ERRORS+=("demo_git_commit_initial_failed")
git -C "$DEMO_REPO" log --oneline -5 > "$PROOF_DIR/demo_git_log_before.txt" 2>&1 || true

printf 'approved lane change\n' >> "$DEMO_REPO/demo.txt"
git -C "$DEMO_REPO" add demo.txt >/dev/null 2>&1 || ERRORS+=("demo_git_add_change_failed")
git -C "$DEMO_REPO" status --porcelain > "$PROOF_DIR/git_status_before.txt" 2>&1 || true

echo "=== Request gated git_commit via MCP ==="
APPROVAL_PAYLOAD="$(call_mcp_tool "slimyos_git_commit" "{\"repo_path\": \"$DEMO_REPO\", \"message\": \"approved test lane commit\", \"api_key\": \"demo_secret_key_12345\", \"chat_text\": \"private chat should never persist\"}" "approved-exec-req-1")"
printf '%s\n' "$APPROVAL_PAYLOAD" > "$PROOF_DIR/approval_request.json"

python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path

proof = Path(sys.argv[1])
payload = json.loads((proof / "approval_request.json").read_text())
tool = payload.get("tool_result", {})
if tool.get("disposition") != "approval_required":
    raise SystemExit(f"expected approval_required, got {tool.get('disposition')}")
if not tool.get("approval_id"):
    raise SystemExit("approval_id missing")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("approval_request_not_gated")
fi

APPROVAL_ID="$(python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads((Path(sys.argv[1]) / "approval_request.json").read_text())
print(payload.get("tool_result", {}).get("approval_id", ""))
PY
)"

curl -sS "$BROKER_URL/approvals?status=pending" > "$PROOF_DIR/pending_approvals.json" || ERRORS+=("pending_approvals_fetch_failed")
python3 - "$PROOF_DIR" "$APPROVAL_ID" <<'PY'
import json
import sys
from pathlib import Path

proof = Path(sys.argv[1])
approval_id = sys.argv[2]
pending = json.loads((proof / "pending_approvals.json").read_text()).get("approvals", [])
if not any(a.get("approval_id") == approval_id for a in pending):
    raise SystemExit("pending approval missing in API")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("pending_approval_not_visible")
fi

echo "=== Approve request ==="
curl -sS -X POST "$BROKER_URL/approve" \
  -H "Content-Type: application/json" \
  -d "{\"approval_id\": \"$APPROVAL_ID\", \"decided_by\": \"smoke-approved-execution\"}" > "$PROOF_DIR/approval_decision.json" || ERRORS+=("approve_call_failed")

python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path

proof = Path(sys.argv[1])
resp = json.loads((proof / "approval_decision.json").read_text())
if not resp.get("ok"):
    raise SystemExit(f"approval failed: {resp}")
if (resp.get("approval") or {}).get("status") != "approved":
    raise SystemExit("approval status not approved")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("approval_status_invalid")
fi

python3 - "$PROOF_DIR" "$APPROVAL_ID" <<'PY'
import json
import sys
from pathlib import Path

proof = Path(sys.argv[1])
approval_id = sys.argv[2]
payload = {
    "approval_id": approval_id,
    "confirm": "execute-approved-test-lane",
}
(proof / "execute_approved_request.json").write_text(json.dumps(payload, indent=2))
PY
echo "=== Execute approved request ==="
curl -sS -X POST "$BROKER_URL/execute-approved" \
  -H "Content-Type: application/json" \
  -d "{\"approval_id\": \"$APPROVAL_ID\", \"confirm\": \"execute-approved-test-lane\"}" > "$PROOF_DIR/execute_approved_result.json" || ERRORS+=("execute_approved_call_failed")

python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path

proof = Path(sys.argv[1])
resp = json.loads((proof / "execute_approved_result.json").read_text())
if not resp.get("ok"):
    raise SystemExit(f"execute-approved failed: {resp}")
approval = resp.get("approval", {})
if approval.get("execution_status") != "executed":
    raise SystemExit(f"unexpected execution_status: {approval.get('execution_status')}")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("execute_approved_not_executed")
fi

git -C "$DEMO_REPO" status --porcelain > "$PROOF_DIR/git_status_after.txt" 2>&1 || true
git -C "$DEMO_REPO" log --oneline -5 > "$PROOF_DIR/demo_git_log_after.txt" 2>&1 || true

DEMO_HEAD_BEFORE="$(awk 'NR==1{print $1}' "$PROOF_DIR/demo_git_log_before.txt" 2>/dev/null || true)"
DEMO_HEAD_AFTER="$(awk 'NR==1{print $1}' "$PROOF_DIR/demo_git_log_after.txt" 2>/dev/null || true)"
if [[ -z "$DEMO_HEAD_AFTER" || "$DEMO_HEAD_AFTER" == "$DEMO_HEAD_BEFORE" ]]; then
  ERRORS+=("demo_repo_commit_not_advanced")
fi

REAL_HEAD_AFTER="$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || true)"
git -C "$PROJECT_ROOT" status --porcelain > "$PROOF_DIR/real_repo_status_after.txt" 2>&1 || true
if [[ "$REAL_HEAD_BEFORE" != "$REAL_HEAD_AFTER" ]]; then
  ERRORS+=("real_repo_head_changed")
fi

echo "=== Refusal: second execution attempt ==="
curl -sS -X POST "$BROKER_URL/execute-approved" \
  -H "Content-Type: application/json" \
  -d "{\"approval_id\": \"$APPROVAL_ID\", \"confirm\": \"execute-approved-test-lane\"}" > "$PROOF_DIR/second_execution_refusal.json" || ERRORS+=("second_execution_call_failed")

python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path

resp = json.loads((Path(sys.argv[1]) / "second_execution_refusal.json").read_text())
if resp.get("ok") is True:
    raise SystemExit("second execution should be refused")
if "already_used" not in str(resp.get("error", "")):
    raise SystemExit(f"unexpected second execution refusal: {resp}")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("second_execution_not_refused")
fi

echo "=== Refusal: denied approval cannot execute ==="
printf 'denied lane change\n' >> "$DEMO_REPO/demo.txt"
git -C "$DEMO_REPO" add demo.txt >/dev/null 2>&1 || ERRORS+=("demo_git_add_denied_case_failed")
DENIED_REQ="$(call_mcp_tool "slimyos_git_commit" "{\"repo_path\": \"$DEMO_REPO\", \"message\": \"denied execution case\"}" "approved-exec-req-denied")"
printf '%s\n' "$DENIED_REQ" > "$PROOF_DIR/denied_request.json"
DENIED_APPROVAL_ID="$(python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads((Path(sys.argv[1]) / "denied_request.json").read_text())
print(payload.get("tool_result", {}).get("approval_id", ""))
PY
)"

curl -sS -X POST "$BROKER_URL/deny" \
  -H "Content-Type: application/json" \
  -d "{\"approval_id\": \"$DENIED_APPROVAL_ID\", \"decided_by\": \"smoke-approved-execution\"}" > "$PROOF_DIR/denied_decision.json" || ERRORS+=("deny_call_failed")

curl -sS -X POST "$BROKER_URL/execute-approved" \
  -H "Content-Type: application/json" \
  -d "{\"approval_id\": \"$DENIED_APPROVAL_ID\", \"confirm\": \"execute-approved-test-lane\"}" > "$PROOF_DIR/denied_execution_refusal.json" || ERRORS+=("denied_execution_call_failed")

python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path

resp = json.loads((Path(sys.argv[1]) / "denied_execution_refusal.json").read_text())
if resp.get("ok") is True:
    raise SystemExit("denied approval should not execute")
if "approval_not_executable_status:denied" not in str(resp.get("error", "")):
    raise SystemExit(f"unexpected denied refusal: {resp}")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("denied_execution_not_refused")
fi

echo "=== Refusal: args mismatch ==="
printf 'args mismatch lane change\n' >> "$DEMO_REPO/demo.txt"
git -C "$DEMO_REPO" add demo.txt >/dev/null 2>&1 || ERRORS+=("demo_git_add_args_case_failed")
ARGS_REQ="$(call_mcp_tool "slimyos_git_commit" "{\"repo_path\": \"$DEMO_REPO\", \"message\": \"expected args\"}" "approved-exec-req-args")"
printf '%s\n' "$ARGS_REQ" > "$PROOF_DIR/args_request.json"
ARGS_APPROVAL_ID="$(python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads((Path(sys.argv[1]) / "args_request.json").read_text())
print(payload.get("tool_result", {}).get("approval_id", ""))
PY
)"

curl -sS -X POST "$BROKER_URL/approve" \
  -H "Content-Type: application/json" \
  -d "{\"approval_id\": \"$ARGS_APPROVAL_ID\", \"decided_by\": \"smoke-approved-execution\"}" > "$PROOF_DIR/args_approval.json" || ERRORS+=("args_approve_failed")

curl -sS -X POST "$BROKER_URL/execute-approved" \
  -H "Content-Type: application/json" \
  -d "{\"approval_id\": \"$ARGS_APPROVAL_ID\", \"confirm\": \"execute-approved-test-lane\", \"args\": {\"repo_path\": \"$DEMO_REPO\", \"message\": \"mismatch\"}}" > "$PROOF_DIR/args_mismatch_refusal.json" || ERRORS+=("args_mismatch_execute_call_failed")

python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path

resp = json.loads((Path(sys.argv[1]) / "args_mismatch_refusal.json").read_text())
if resp.get("ok") is True:
    raise SystemExit("args mismatch should be refused")
if "args_mismatch" not in str(resp.get("error", "")):
    raise SystemExit(f"unexpected args mismatch refusal: {resp}")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("args_mismatch_not_refused")
fi

echo "=== Verify raw_shell blocked ==="
RAW_BLOCK_PAYLOAD="$(call_mcp_tool "slimyos_raw_shell" "{\"command\": \"rm -rf /\"}" "approved-exec-raw-shell")"
printf '%s\n' "$RAW_BLOCK_PAYLOAD" > "$PROOF_DIR/raw_shell_block.json"
python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads((Path(sys.argv[1]) / "raw_shell_block.json").read_text())
tool = payload.get("tool_result", {})
if tool.get("disposition") != "blocked":
    raise SystemExit(f"raw_shell should be blocked, got {tool.get('disposition')}")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("raw_shell_not_blocked")
fi

echo "=== Verify audit execution start/finish and privacy ==="
curl -sS "$BROKER_URL/audit/recent" > "$PROOF_DIR/audit_recent.json" || ERRORS+=("audit_fetch_failed")

python3 - "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path

proof = Path(sys.argv[1])
events = json.loads((proof / "audit_recent.json").read_text()).get("events", [])

start = [e for e in events if e.get("event_type") == "approval_execution_start"]
finish = [e for e in events if e.get("event_type") == "approval_execution_finish"]

if not start:
    raise SystemExit("missing approval_execution_start")
if not finish:
    raise SystemExit("missing approval_execution_finish")

(proof / "audit_execution_start.json").write_text(json.dumps(start[-1], indent=2))
(proof / "audit_execution_finish.json").write_text(json.dumps(finish[-1], indent=2))

blob = json.dumps(events).lower()
issues = []
if "private chat should never persist" in blob:
    issues.append("chat_text_leaked")
if "demo_secret_key_12345" in blob:
    issues.append("secret_value_leaked")

(proof / "privacy_check.json").write_text(json.dumps({"issues": issues, "clean": len(issues) == 0}, indent=2))
if issues:
    raise SystemExit("privacy_issues_detected")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("privacy_or_audit_verification_failed")
fi

git -C "$PROJECT_ROOT" diff --name-only > "$PROOF_DIR/changed_files.txt" 2>&1 || true

python3 - "$PROOF_DIR" "$DEMO_REPO" "$PROJECT_ROOT" <<'PY' > "$PROOF_DIR/meta.json"
import json
import sys
from datetime import datetime, timezone

proof_dir, demo_repo, project_root = sys.argv[1:4]
meta = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "proof_dir": proof_dir,
    "demo_repo": demo_repo,
    "project_root": project_root,
    "checks": [
        "approval_required_with_approval_id",
        "pending_approval_visible",
        "approve_status_approved",
        "execute_approved_runs_in_demo_repo",
        "demo_repo_commit_advanced",
        "real_repo_head_unchanged",
        "execution_status_executed",
        "execution_start_finish_audited",
        "second_execution_refused",
        "denied_approval_refused",
        "args_mismatch_refused",
        "raw_shell_blocked",
        "privacy_clean",
    ],
}
print(json.dumps(meta, indent=2))
PY

python3 - "$PROOF_DIR" "${WARNINGS[*]:-}" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1], "warnings.json").write_text(json.dumps({"warnings": [w for w in sys.argv[2].split(" ") if w]}, indent=2))
PY

python3 - "$PROOF_DIR" "${ERRORS[*]:-}" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1], "errors.json").write_text(json.dumps({"errors": [e for e in sys.argv[2].split(" ") if e]}, indent=2))
PY

if [[ ${#ERRORS[@]} -eq 0 ]]; then
  echo "RESULT=PASS" > "$PROOF_DIR/RESULT.txt"
  echo "Approved execution smoke PASSED"
else
  echo "RESULT=FAIL" > "$PROOF_DIR/RESULT.txt"
  echo "Approved execution smoke FAILED"
  for err in "${ERRORS[@]}"; do
    echo "- $err"
  done
fi

cat "$PROOF_DIR/RESULT.txt"
echo "Proof directory: $PROOF_DIR"

if [[ ${#ERRORS[@]} -eq 0 ]]; then
  exit 0
fi
exit 1
