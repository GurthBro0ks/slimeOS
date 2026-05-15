#!/bin/bash

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UTC_NOW="$(date -u +%Y%m%dT%H%M%SZ)"
DEFAULT_PROOF_DIR="/tmp/proof_slimyos_claude_mcp_protocol_${UTC_NOW}"
PROOF_DIR="${1:-${SLIMYOS_PROOF_DIR:-$DEFAULT_PROOF_DIR}}"
BROKER_URL="${SLIMYOS_TOOLD_URL:-http://localhost:3003}"

mkdir -p "$PROOF_DIR"
SMOKE_OUT="$PROOF_DIR/smoke_output.txt"
exec > >(tee "$SMOKE_OUT") 2>&1

echo "SlimyOS Claude MCP protocol smoke test"
echo "Project root: $PROJECT_ROOT"
echo "Proof dir: $PROOF_DIR"
echo "Broker URL: $BROKER_URL"

python3 - <<PYEOF
import json
import subprocess
import sys
import time
from pathlib import Path

project_root = Path("$PROJECT_ROOT")
proof_dir = Path("$PROOF_DIR")
broker_url = "$BROKER_URL"
errors = []
warnings = []

proc = subprocess.Popen(
    [str(project_root / "scripts" / "run-mcp-server.sh")],
    cwd=str(project_root),
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

stdout_lines = []

def rpc(req):
    line = json.dumps(req) + "\n"
    proc.stdin.write(line)
    proc.stdin.flush()
    out_line = proc.stdout.readline().strip()
    if out_line:
        stdout_lines.append(out_line)
    if not out_line:
        raise RuntimeError("No MCP response received")
    return json.loads(out_line)

def send_notification(notif):
    line = json.dumps(notif) + "\n"
    proc.stdin.write(line)
    proc.stdin.flush()
    time.sleep(0.1)

try:
    # 1. Initialize with string id
    print("\n=== 1. Initialize (string id) ===")
    init_resp = rpc({"jsonrpc": "2.0", "id": "0", "method": "initialize", "params": {"capabilities": {}}})
    (proof_dir / "mcp_initialize_response.json").write_text(json.dumps(init_resp, indent=2))
    if init_resp.get("id") != "0":
        errors.append(f"string_id_not_preserved: expected '0', got {init_resp.get('id')}")
    if "result" not in init_resp:
        errors.append("initialize_missing_result")
    result = init_resp.get("result", {})
    if "protocolVersion" not in result:
        errors.append("initialize_missing_protocolVersion")
    if "serverInfo" not in result:
        errors.append("initialize_missing_serverInfo")
    if "capabilities" not in result:
        errors.append("initialize_missing_capabilities")
    if "error" in init_resp:
        errors.append(f"initialize_has_error: {init_resp['error']}")
    print(f"  id={init_resp.get('id')} protocolVersion={result.get('protocolVersion')} OK")

    # 2. Notification: notifications/initialized - must produce NO response
    print("\n=== 2. notifications/initialized (no response expected) ===")
    before_count = len(stdout_lines)
    send_notification({"jsonrpc": "2.0", "method": "notifications/initialized"})
    after_count = len(stdout_lines)
    if after_count != before_count:
        errors.append(f"notification_produced_response: got {after_count - before_count} extra lines")
    else:
        print("  No response produced (correct)")

    # 3. tools/list with numeric id
    print("\n=== 3. tools/list (numeric id) ===")
    list_resp = rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    (proof_dir / "mcp_tools_list_response.json").write_text(json.dumps(list_resp, indent=2))
    if list_resp.get("id") != 1:
        errors.append(f"numeric_id_not_preserved: expected 1, got {list_resp.get('id')}")
    tools = list_resp.get("result", {}).get("tools", [])
    if len(tools) < 40:
        errors.append(f"tool_count_below_threshold:{len(tools)}")
    for t in tools:
        if "name" not in t:
            errors.append(f"tool_missing_name:{t}")
        if "inputSchema" not in t:
            errors.append(f"tool_missing_inputSchema:{t.get('name')}")
        if "x_slimyos" in t:
            errors.append(f"tool_has_extra_key_x_slimyos:{t.get('name')}")
        if "structuredContent" in str(t):
            errors.append(f"tool_has_structuredContent_key:{t.get('name')}")
    print(f"  tool_count={len(tools)} OK")

    # 4. Ping with string id
    print("\n=== 4. ping ===")
    ping_resp = rpc({"jsonrpc": "2.0", "id": "ping-1", "method": "ping"})
    if ping_resp.get("id") != "ping-1":
        errors.append(f"ping_id_not_preserved: {ping_resp.get('id')}")
    if "result" not in ping_resp:
        errors.append("ping_missing_result")
    print("  ping OK")

    # 5. Safe call
    print("\n=== 5. tools/call safe ===")
    safe_resp = rpc({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "slimyos_read_file",
            "arguments": {"path": str(project_root / "README.md")},
        },
    })
    (proof_dir / "mcp_safe_call_response.json").write_text(json.dumps(safe_resp, indent=2))
    safe_result = safe_resp.get("result", {})
    if "content" not in safe_result:
        errors.append("safe_call_missing_content")
    content = safe_result.get("content", [])
    if not isinstance(content, list) or len(content) == 0:
        errors.append("safe_call_content_not_list")
    else:
        if content[0].get("type") != "text":
            errors.append(f"safe_call_content_type_not_text:{content[0].get('type')}")
    # Must NOT have structuredContent
    if "structuredContent" in safe_result:
        errors.append("safe_call_has_structuredContent_extra_key")
    # Check error response shape
    if "error" in safe_resp:
        err_obj = safe_resp["error"]
        if "timestamp" in err_obj:
            errors.append("error_response_has_timestamp_extra_key")
        if "hostname" in err_obj:
            errors.append("error_response_has_hostname_extra_key")
    print(f"  content_type={content[0].get('type') if content else 'MISSING'} isError={safe_result.get('isError')} OK")

    # 6. Blocked call
    print("\n=== 6. tools/call blocked (raw_shell) ===")
    blocked_resp = rpc({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "slimyos_raw_shell",
            "arguments": {"command": "rm -rf /"},
        },
    })
    (proof_dir / "mcp_blocked_call_response.json").write_text(json.dumps(blocked_resp, indent=2))
    blocked_result = blocked_resp.get("result", {})
    blocked_text = blocked_result.get("content", [{}])[0].get("text", "{}")
    blocked_data = json.loads(blocked_text) if blocked_text else {}
    if blocked_data.get("disposition") != "blocked":
        errors.append(f"raw_shell_not_blocked:{blocked_data.get('disposition')}")
    if not blocked_result.get("isError"):
        errors.append("blocked_call_isError_not_true")
    print(f"  disposition={blocked_data.get('disposition')} isError={blocked_result.get('isError')} OK")

    # 7. Gated call
    print("\n=== 7. tools/call gated (restart_service sshd) ===")
    gated_resp = rpc({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "slimyos_restart_service",
            "arguments": {"service_name": "sshd"},
        },
    })
    (proof_dir / "mcp_gated_call_response.json").write_text(json.dumps(gated_resp, indent=2))
    gated_result = gated_resp.get("result", {})
    gated_text = gated_result.get("content", [{}])[0].get("text", "{}")
    gated_data = json.loads(gated_text) if gated_text else {}
    if gated_data.get("disposition") not in {"blocked", "approval_required"}:
        errors.append(f"restart_service_not_gated:{gated_data.get('disposition')}")
    print(f"  disposition={gated_data.get('disposition')} OK")

    # 8. Unknown method
    print("\n=== 8. Unknown method ===")
    unknown_resp = rpc({"jsonrpc": "2.0", "id": 5, "method": "nonexistent/method"})
    if "error" not in unknown_resp:
        errors.append("unknown_method_missing_error")
    else:
        err = unknown_resp["error"]
        if not isinstance(err.get("code"), int):
            errors.append(f"error_code_not_int:{type(err.get('code'))}")
        if not isinstance(err.get("message"), str):
            errors.append(f"error_message_not_str:{type(err.get('message'))}")
        extra_keys = set(err.keys()) - {"code", "message", "data"}
        if extra_keys:
            errors.append(f"error_has_extra_keys:{extra_keys}")
    print(f"  error.code={unknown_resp.get('error',{}).get('code')} OK")

    # 9. Stdout purity check
    print("\n=== 9. Stdout purity ===")
    all_valid_jsonrpc = True
    for i, line in enumerate(stdout_lines):
        try:
            obj = json.loads(line)
            if "jsonrpc" not in obj:
                errors.append(f"stdout_line_{i}_missing_jsonrpc_key")
                all_valid_jsonrpc = False
            if "error" in obj and not isinstance(obj["error"].get("code"), int):
                errors.append(f"stdout_line_{i}_raw_error_object")
                all_valid_jsonrpc = False
        except json.JSONDecodeError:
            errors.append(f"stdout_line_{i}_not_valid_json: {line[:80]}")
            all_valid_jsonrpc = False
    (proof_dir / "stdout_purity_check.txt").write_text(
        f"lines_checked={len(stdout_lines)} all_valid_jsonrpc={all_valid_jsonrpc}\n"
    )
    print(f"  {len(stdout_lines)} lines, all valid JSON-RPC: {all_valid_jsonrpc}")

finally:
    try:
        proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        proc.kill()
    stderr_out = proc.stderr.read()
    if stderr_out:
        (proof_dir / "stderr_capture.txt").write_text(stderr_out)

meta = {
    "tool_count": len(tools),
    "stdout_lines": len(stdout_lines),
    "errors": errors,
    "warnings": warnings,
}
(proof_dir / "meta.json").write_text(json.dumps(meta, indent=2))

if errors:
    print(f"\nFAIL: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    print("RESULT=FAIL", file=open(proof_dir / "RESULT.txt", "w"))
    raise SystemExit(1)
else:
    print("\nAll protocol checks PASSED")
    print("RESULT=PASS", file=open(proof_dir / "RESULT.txt", "w"))
PYEOF

RESULT=$?

cat "$PROOF_DIR/RESULT.txt"
echo "Claude MCP protocol smoke proof directory: $PROOF_DIR"

if grep -q "RESULT=PASS" "$PROOF_DIR/RESULT.txt"; then
  exit 0
fi
exit 1
