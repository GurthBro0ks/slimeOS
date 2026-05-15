#!/bin/bash

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UTC_NOW="$(date -u +%Y%m%dT%H%M%SZ)"
DEFAULT_PROOF_DIR="/tmp/proof_slimyos_mcp_bridge_${UTC_NOW}"
PROOF_DIR="${1:-${SLIMYOS_MCP_PROOF_DIR:-$DEFAULT_PROOF_DIR}}"
BROKER_URL="${SLIMYOS_TOOLD_URL:-http://localhost:3003}"

mkdir -p "$PROOF_DIR"
SMOKE_OUT="$PROOF_DIR/smoke_output.txt"
exec > >(tee "$SMOKE_OUT") 2>&1

echo "SlimyOS MCP bridge smoke test"
echo "Project root: $PROJECT_ROOT"
echo "Proof dir: $PROOF_DIR"

git -C "$PROJECT_ROOT" status -sb > "$PROOF_DIR/git_status_before.txt" 2>&1 || true
git -C "$PROJECT_ROOT" status --short >> "$PROOF_DIR/git_status_before.txt" 2>&1 || true

if ! curl -sS "$BROKER_URL/health" > "$PROOF_DIR/broker_health.json"; then
  echo "Broker health check failed"
  echo "RESULT=FAIL" > "$PROOF_DIR/RESULT.txt"
  exit 1
fi

python3 - <<PY > "$PROOF_DIR/test_output.txt" 2>&1
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

project_root = Path("$PROJECT_ROOT")
proof_dir = Path("$PROOF_DIR")

errors = []

proc = subprocess.Popen(
    [str(project_root / "scripts" / "run-mcp-server.sh")],
    cwd=str(project_root),
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

def rpc(req):
    proc.stdin.write(json.dumps(req) + "\\n")
    proc.stdin.flush()
    line = proc.stdout.readline().strip()
    if not line:
        raise RuntimeError("No MCP response received")
    return json.loads(line)

try:
    init_resp = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    (proof_dir / "mcp_initialize.json").write_text(json.dumps(init_resp, indent=2))

    list_resp = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    (proof_dir / "mcp_tools_list.json").write_text(json.dumps(list_resp, indent=2))
    tools = list_resp.get("result", {}).get("tools", [])
    if len(tools) < 40:
        errors.append(f"mcp_tool_count_below_threshold:{len(tools)}")

    safe_resp = rpc({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "slimyos_read_file",
            "arguments": {"path": str(project_root / "README.md")},
        },
    })
    (proof_dir / "mcp_safe_call.json").write_text(json.dumps(safe_resp, indent=2))
    safe_struct = safe_resp.get("result", {}).get("structuredContent", {})
    if not safe_struct.get("success", False):
        errors.append("mcp_safe_call_failed")

    blocked_resp = rpc({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "slimyos_raw_shell",
            "arguments": {"command": "rm -rf /"},
        },
    })
    (proof_dir / "mcp_blocked_call.json").write_text(json.dumps(blocked_resp, indent=2))
    blocked_struct = blocked_resp.get("result", {}).get("structuredContent", {})
    if blocked_struct.get("disposition") != "blocked":
        errors.append(f"mcp_raw_shell_not_blocked:{blocked_struct.get('disposition')}")

    gated_resp = rpc({
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "slimyos_restart_service",
            "arguments": {"service_name": "sshd"},
        },
    })
    (proof_dir / "mcp_gated_call.json").write_text(json.dumps(gated_resp, indent=2))
    gated_struct = gated_resp.get("result", {}).get("structuredContent", {})
    if gated_struct.get("disposition") not in {"blocked", "approval_required"}:
        errors.append(f"mcp_restart_service_not_gated:{gated_struct.get('disposition')}")

    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "proof_dir": str(proof_dir),
        "repo_path": str(project_root),
        "tool_count": len(tools),
        "errors": errors,
    }
    (proof_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    if errors:
        print("FAIL")
        for item in errors:
            print(item)
        raise SystemExit(1)
    print("PASS")
finally:
    try:
        proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        proc.kill()
PY

if [[ $? -eq 0 ]]; then
  echo "RESULT=PASS" > "$PROOF_DIR/RESULT.txt"
else
  echo "RESULT=FAIL" > "$PROOF_DIR/RESULT.txt"
fi

git -C "$PROJECT_ROOT" status -sb > "$PROOF_DIR/git_status_after.txt" 2>&1 || true
git -C "$PROJECT_ROOT" status --short >> "$PROOF_DIR/git_status_after.txt" 2>&1 || true
git -C "$PROJECT_ROOT" diff --name-only > "$PROOF_DIR/changed_files.txt" 2>&1 || true

cat "$PROOF_DIR/RESULT.txt"
echo "MCP smoke proof directory: $PROOF_DIR"

if grep -q "RESULT=PASS" "$PROOF_DIR/RESULT.txt"; then
  exit 0
fi
exit 1
