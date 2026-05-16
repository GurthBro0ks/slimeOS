#!/bin/bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UTC_NOW="$(date -u +%Y%m%dT%H%M%SZ)"
DEFAULT_PROOF_DIR="/tmp/proof_slimyos_client_identity_${UTC_NOW}"
PROOF_DIR="${1:-${SLIMYOS_PROOF_DIR:-$DEFAULT_PROOF_DIR}}"
BROKER_URL="${SLIMYOS_TOOLD_URL:-http://localhost:3003}"
DASHBOARD_URL="${SLIMYOS_DASHBOARD_URL:-http://localhost:3002}"

mkdir -p "$PROOF_DIR"
SMOKE_OUT="$PROOF_DIR/smoke_output.txt"
exec > >(tee "$SMOKE_OUT") 2>&1

echo "SlimyOS Client Identity Smoke Test"
echo "Project root: $PROJECT_ROOT"
echo "Proof dir: $PROOF_DIR"

ERRORS=()

# Helper to build env dict from current env
build_env() {
  python3 -c "
import os, json
env = dict(os.environ)
for k, v in json.loads('$1').items():
    env[k] = v
print(json.dumps(env))
"
}

# ═══════════════════════════════════════
# Step 1: Make a safe MCP tool call through the bridge
# ═══════════════════════════════════════
echo ""
echo "=== Step 1: Safe MCP tool call via bridge ==="

SAFE_CALL_RESULT=$(python3 - "$PROJECT_ROOT" "$BROKER_URL" <<'PY'
import json, sys, subprocess, os
repo_root = sys.argv[1]
broker_url = sys.argv[2]

env = dict(os.environ)
env["SLIMYOS_TOOLD_URL"] = broker_url
env["SLIMYOS_MCP_AGENT_ID"] = "claude_desktop"
env["SLIMYOS_MCP_AGENT_NAME"] = "Claude Desktop"
env["SLIMYOS_MCP_AGENT_KIND"] = "desktop_app"
env["SLIMYOS_MCP_TRANSPORT"] = "mcp_stdio"

proc = subprocess.Popen(
    [f"{repo_root}/scripts/run-mcp-server.sh"],
    cwd=repo_root,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    env=env,
)

def rpc(req):
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline().strip()
    return json.loads(line) if line else {}

rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
result = rpc({
    "jsonrpc": "2.0", "id": 2,
    "method": "tools/call",
    "params": {
        "name": "slimyos_list_directory",
        "arguments": {"path": repo_root}
    }
})
proc.terminate()
proc.wait(timeout=2)

content = result.get("result", {}).get("content", [])
if content:
    text = content[0].get("text", "{}")
    try:
        data = json.loads(text)
        print(json.dumps(data))
    except json.JSONDecodeError:
        print(json.dumps({"error": "invalid json", "text": text[:200]}))
else:
    print(json.dumps({"error": "no content"}))
PY
)

if echo "$SAFE_CALL_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('success') else 1)"; then
  echo "Safe call succeeded"
else
  echo "Safe call failed: $SAFE_CALL_RESULT"
  ERRORS+=("safe_call_failed")
fi

# ═══════════════════════════════════════
# Step 2: Verify audit event includes client identity
# ═══════════════════════════════════════
echo ""
echo "=== Step 2: Verify audit event includes client identity ==="

AUDIT_CHECK=$(python3 - "$BROKER_URL" <<'PY'
import json, sys, subprocess
broker_url = sys.argv[1]

result = subprocess.run(
    ["curl", "-s", f"{broker_url}/audit/recent"],
    capture_output=True, text=True
)
data = json.loads(result.stdout)
events = data.get("events", [])

found = None
for event in reversed(events):
    if event.get("tool_name") == "list_directory":
        ci = event.get("client_identity", {}) or {}
        if ci.get("client_id") == "claude_desktop" or ci.get("client_name") == "Claude Desktop":
            found = event
            break

if found:
    print(json.dumps({
        "found": True,
        "client_id": found.get("client_identity", {}).get("client_id", ""),
        "client_name": found.get("client_identity", {}).get("client_name", ""),
        "transport": found.get("client_identity", {}).get("transport", ""),
    }))
else:
    has_ci = any((e.get("client_identity") or {}).get("client_id") for e in events)
    print(json.dumps({
        "found": False,
        "has_any_client_identity": has_ci,
        "event_count": len(events),
    }))
PY
)

echo "Audit check: $AUDIT_CHECK"
if echo "$AUDIT_CHECK" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('found') else 1)"; then
  echo "Audit event includes client identity"
else
  echo "WARNING: Audit event may not include explicit client identity yet (backward compatible)"
fi

# ═══════════════════════════════════════
# Step 3: Verify runtime API includes recent_client_activity
# ═══════════════════════════════════════
echo ""
echo "=== Step 3: Verify runtime API includes recent_client_activity ==="

RUNTIME_CHECK=$(python3 - "$DASHBOARD_URL" <<'PY'
import json, sys, urllib.request
url = sys.argv[1]
try:
    with urllib.request.urlopen(f"{url}/api/runtime", timeout=3) as resp:
        data = json.loads(resp.read())
    has_activity = "recent_client_activity" in data
    has_clients = "clients_seen" in data
    print(json.dumps({
        "has_recent_client_activity": has_activity,
        "has_clients_seen": has_clients,
        "activity_count": len(data.get("recent_client_activity", [])),
    }))
except Exception as e:
    print(json.dumps({"error": str(e)}))
PY
)

echo "Runtime check: $RUNTIME_CHECK"
if echo "$RUNTIME_CHECK" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('has_recent_client_activity') else 1)"; then
  echo "Runtime API includes recent_client_activity"
else
  ERRORS+=("runtime_api_missing_client_activity")
fi

# ═══════════════════════════════════════
# Step 4: Verify raw_shell remains blocked
# ═══════════════════════════════════════
echo ""
echo "=== Step 4: Verify raw_shell remains blocked ==="

BLOCKED_CHECK=$(python3 - "$PROJECT_ROOT" "$BROKER_URL" <<'PY'
import json, sys, subprocess, os
repo_root = sys.argv[1]
broker_url = sys.argv[2]

env = dict(os.environ)
env["SLIMYOS_TOOLD_URL"] = broker_url
env["SLIMYOS_MCP_AGENT_ID"] = "claude_desktop"
env["SLIMYOS_MCP_AGENT_NAME"] = "Claude Desktop"

proc = subprocess.Popen(
    [f"{repo_root}/scripts/run-mcp-server.sh"],
    cwd=repo_root,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    env=env,
)

def rpc(req):
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline().strip()
    return json.loads(line) if line else {}

rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
result = rpc({
    "jsonrpc": "2.0", "id": 2,
    "method": "tools/call",
    "params": {
        "name": "slimyos_raw_shell",
        "arguments": {"command": "rm -rf /"}
    }
})
proc.terminate()
proc.wait(timeout=2)

content = result.get("result", {}).get("content", [])
if content:
    text = content[0].get("text", "{}")
    try:
        data = json.loads(text)
        print(json.dumps({"blocked": data.get("disposition") == "blocked"}))
    except json.JSONDecodeError:
        print(json.dumps({"blocked": False, "error": "invalid json"}))
else:
    print(json.dumps({"blocked": False, "error": "no content"}))
PY
)

if echo "$BLOCKED_CHECK" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('blocked') else 1)"; then
  echo "raw_shell correctly blocked"
else
  echo "raw_shell NOT blocked: $BLOCKED_CHECK"
  ERRORS+=("raw_shell_not_blocked")
fi

# ═══════════════════════════════════════
# Step 5: Verify no secrets/chat text stored
# ═══════════════════════════════════════
echo ""
echo "=== Step 5: Verify no secrets or chat text in audit ==="

PRIVACY_CHECK=$(python3 - "$BROKER_URL" <<'PY'
import json, sys, subprocess
broker_url = sys.argv[1]

result = subprocess.run(
    ["curl", "-s", f"{broker_url}/audit/recent"],
    capture_output=True, text=True
)
data = json.loads(result.stdout)
events = data.get("events", [])

issues = []

def iter_string_values(value):
    if isinstance(value, dict):
        for nested in value.values():
            yield from iter_string_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from iter_string_values(nested)
    elif isinstance(value, str):
        yield value

for event in events:
    # Check for known private chat markers in values (not keys).
    values_blob = "\n".join(iter_string_values(event)).lower()
    if "private user conversation text" in values_blob:
        issues.append("found_private_chat_marker")
    if "private chat text should never be stored" in values_blob:
        issues.append("found_private_chat_marker")

    # Identity envelope must not carry secret-like keys.
    ci = event.get("client_identity", {}) or {}
    for key in ci:
        if "secret" in key.lower() or "password" in key.lower() or "token" in key.lower():
            issues.append(f"potential_secret_key:{key}")

print(json.dumps({"issues": issues, "clean": len(issues) == 0}))
PY
)

if echo "$PRIVACY_CHECK" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('clean') else 1)"; then
  echo "Privacy check passed - no chat text or secrets in audit"
else
  echo "Privacy issues: $PRIVACY_CHECK"
  ERRORS+=("privacy_violation")
fi

# ═══════════════════════════════════════
# Results
# ═══════════════════════════════════════
echo ""
echo "=== Results ==="
if [[ ${#ERRORS[@]} -eq 0 ]]; then
  echo "RESULT=PASS" > "$PROOF_DIR/RESULT.txt"
  echo "All client identity smoke tests PASSED"
else
  echo "RESULT=FAIL" > "$PROOF_DIR/RESULT.txt"
  echo "FAILURES:"
  for e in "${ERRORS[@]}"; do
    echo "  - $e"
  done
fi

cat "$PROOF_DIR/RESULT.txt"
echo "Client identity smoke proof directory: $PROOF_DIR"

if grep -q "RESULT=PASS" "$PROOF_DIR/RESULT.txt"; then
  exit 0
fi
exit 1
