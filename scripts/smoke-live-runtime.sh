#!/bin/bash

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UTC_NOW="$(date -u +%Y%m%dT%H%M%SZ)"
PROOF_DIR="/tmp/proof_slimyos_live_runtime_${UTC_NOW}"
RESULT="PASS"

mkdir -p "$PROOF_DIR"
SMOKE_OUTPUT="$PROOF_DIR/smoke_output.txt"
TEST_OUTPUT="$PROOF_DIR/test_output.txt"

exec > >(tee "$SMOKE_OUTPUT") 2>&1

fail() {
  echo "FAIL: $1"
  RESULT="FAIL"
}

echo "SlimyOS live runtime smoke test"
echo "Project root: $PROJECT_ROOT"
echo "Proof dir: $PROOF_DIR"

if ! git -C "$PROJECT_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  fail "repo_detection_failed"
else
  REPO_TOP="$(git -C "$PROJECT_ROOT" rev-parse --show-toplevel)"
  if [[ "$REPO_TOP" != *"slimeOS"* && "$REPO_TOP" != *"slimyOS"* ]]; then
    fail "unexpected_repo_path:$REPO_TOP"
  fi
fi

git -C "$PROJECT_ROOT" status --short > "$PROOF_DIR/git_status.txt" 2>&1 || true
git -C "$PROJECT_ROOT" diff --name-only > "$PROOF_DIR/changed_files.txt" 2>&1 || true

if ! python3 - <<'PY' > "$TEST_OUTPUT" 2>&1
import importlib
import dashboard.runtime_status
import dashboard.mission_control
print("imports_ok")
PY
then
  fail "python_imports_failed"
fi

if ! python3 -m unittest tests.test_runtime_status >> "$TEST_OUTPUT" 2>&1; then
  fail "unit_tests_failed"
fi

if ! systemctl --user status slimyos-toold --no-pager > "$PROOF_DIR/service_status.txt" 2>&1; then
  fail "slimyos-toold_status_check_failed"
fi
systemctl --user status slimyos-dashboard --no-pager >> "$PROOF_DIR/service_status.txt" 2>&1 || fail "slimyos-dashboard_status_check_failed"

if ! curl -sS "http://localhost:3003/health" > "$PROOF_DIR/broker_health.json"; then
  fail "broker_health_unreachable"
fi

if ! curl -sS "http://localhost:3002/api/runtime" > "$PROOF_DIR/dashboard_runtime.json"; then
  fail "dashboard_runtime_unreachable"
fi

python3 - <<PY > "$PROOF_DIR/hermes_status.json" 2>&1
import json
from pathlib import Path

runtime = json.loads(Path("$PROOF_DIR/dashboard_runtime.json").read_text())
hermes = runtime.get("hermes", {})
print(json.dumps(hermes, indent=2))

status = hermes.get("status")
if status not in {"pass", "warn"}:
    raise SystemExit("hermes status must be pass or warn")
if not hermes.get("proxy_reachable", False):
    if hermes.get("auth_state") != "auth_required_or_proxy_down":
        raise SystemExit("hermes unreachable must report auth_required_or_proxy_down")
PY
if [[ $? -ne 0 ]]; then
  fail "hermes_warn_check_failed"
fi

if ! curl -sS -X POST "http://localhost:3003/tools/restart_service" \
  -H "Content-Type: application/json" \
  -d '{"args": {"service_name": "sshd"}, "agent_id": "smoke-live-runtime", "agent_runtime": "smoke"}' \
  > "$PROOF_DIR/restart_service_check.json"; then
  fail "dangerous_restart_service_call_failed"
fi

if ! curl -sS -X POST "http://localhost:3003/tools/raw_shell" \
  -H "Content-Type: application/json" \
  -d '{"args": {"command": "rm -rf /"}, "agent_id": "smoke-live-runtime", "agent_runtime": "smoke"}' \
  > "$PROOF_DIR/raw_shell_check.json"; then
  fail "unknown_tool_call_failed"
fi

python3 - <<PY
import json
from pathlib import Path

proof_dir = Path("$PROOF_DIR")
restart_data = json.loads((proof_dir / "restart_service_check.json").read_text())
raw_data = json.loads((proof_dir / "raw_shell_check.json").read_text())

restart_disposition = restart_data.get("disposition")
raw_disposition = raw_data.get("disposition")

if restart_disposition not in {"blocked", "approval_required"}:
    raise SystemExit(f"restart_service policy unexpected disposition: {restart_disposition}")
if raw_disposition != "blocked":
    raise SystemExit(f"raw_shell should be blocked, got: {raw_disposition}")
PY
if [[ $? -ne 0 ]]; then
  fail "policy_blocking_assertion_failed"
fi

python3 - <<PY > "$PROOF_DIR/meta.json"
import json
from datetime import datetime, timezone

meta = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "proof_dir": "$PROOF_DIR",
    "project_root": "$PROJECT_ROOT",
    "checks": [
        "repo_detected",
        "python_imports",
        "tool_broker_health",
        "dashboard_runtime_endpoint",
        "hermes_warn_not_fail",
        "dangerous_tool_policy",
        "unit_tests",
    ],
}
print(json.dumps(meta, indent=2))
PY

python3 - <<PY
import json
from pathlib import Path

proof_dir = Path("$PROOF_DIR")
runtime = json.loads((proof_dir / "dashboard_runtime.json").read_text())
audit_path = runtime.get("audit", {}).get("latest_file", "")

if audit_path:
    source = Path(audit_path)
    if source.exists():
        lines = source.read_text(errors="replace").splitlines()
        tail = "\n".join(lines[-40:])
        (proof_dir / "audit_tail.txt").write_text(tail)
    else:
        (proof_dir / "audit_tail.txt").write_text("audit file missing")
else:
    (proof_dir / "audit_tail.txt").write_text("no audit file reported")
PY

echo "RESULT=$RESULT" | tee "$PROOF_DIR/RESULT.txt"
echo "Smoke complete"
echo "Proof directory: $PROOF_DIR"

if [[ "$RESULT" == "PASS" ]]; then
  exit 0
fi
exit 1
