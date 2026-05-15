#!/bin/bash

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UTC_NOW="$(date -u +%Y%m%dT%H%M%SZ)"
DEFAULT_PROOF_DIR="/tmp/proof_slimyos_smoke_claude_desktop_${UTC_NOW}"
PROOF_DIR="${1:-${SLIMYOS_PROOF_DIR:-$DEFAULT_PROOF_DIR}}"

mkdir -p "$PROOF_DIR"
SMOKE_OUT="$PROOF_DIR/smoke_output.txt"
exec > >(tee "$SMOKE_OUT") 2>&1

echo "SlimyOS Claude Desktop MCP smoke test (fake HOME)"
echo "Project root: $PROJECT_ROOT"
echo "Proof dir: $PROOF_DIR"

ERRORS=()

FAKE_HOME="$PROOF_DIR/fake_home"
FAKE_CONFIG_DIR="$FAKE_HOME/.config/Claude"
mkdir -p "$FAKE_CONFIG_DIR"

FAKE_LAUNCHER="$PROOF_DIR/fake_launcher.sh"
echo '#!/bin/bash' > "$FAKE_LAUNCHER"
echo 'cat' >> "$FAKE_LAUNCHER"
chmod +x "$FAKE_LAUNCHER"

echo ""
echo "=== Step 1: Test config with existing servers + slimyos ==="
FAKE_CONFIG="$FAKE_CONFIG_DIR/claude_desktop_config.json"
cat > "$FAKE_CONFIG" <<CONF
{
  "mcpServers": {
    "google-drive": {"command": "/usr/bin/gdrive", "args": []},
    "gmail": {"command": "/usr/bin/gmail", "args": []},
    "slimyos": {
      "command": "$FAKE_LAUNCHER",
      "args": [],
      "env": {
        "SLIMYOS_TOOLD_URL": "http://localhost:3003",
        "SECRET_API_KEY": "should_be_redacted"
      }
    }
  }
}
CONF

python3 - <<PY
import json
import sys
from adapters.claude_desktop_verify import (
    load_claude_desktop_config, find_slimyos_entry,
    list_existing_servers, redact_entry, validate_launcher,
    build_exact_command,
)

config = load_claude_desktop_config("$FAKE_CONFIG")
servers = list_existing_servers(config)
print(f"Existing servers: {servers}")
if sorted(servers) != ["gmail", "google-drive", "slimyos"]:
    print("ERROR: server list mismatch")
    sys.exit(1)

entry = find_slimyos_entry(config)
if entry is None:
    print("ERROR: slimyos entry not found")
    sys.exit(1)
print(f"SlimyOS entry found: command={entry['command']}")

redacted = redact_entry(entry)
print(f"Redacted entry: {json.dumps(redacted, indent=2)}")
if redacted["env"]["SECRET_API_KEY"] != "***REDACTED***":
    print("ERROR: secret not redacted")
    sys.exit(1)
if redacted["env"]["SLIMYOS_TOOLD_URL"] == "***REDACTED***":
    print("ERROR: normal env var was redacted")
    sys.exit(1)
print("Redaction verified")

launcher = validate_launcher(entry)
if not launcher["valid"]:
    print(f"ERROR: launcher invalid: {launcher}")
    sys.exit(1)
print(f"Launcher valid: {launcher}")

cmd = build_exact_command(entry)
print(f"Command: {cmd}")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("config_with_slimyos_failed")
fi

echo ""
echo "=== Step 2: Test missing SlimyOS entry ==="
cat > "$FAKE_CONFIG" <<CONF
{
  "mcpServers": {
    "other": {"command": "/usr/bin/other", "args": []}
  }
}
CONF

python3 - <<PY
import sys
from adapters.claude_desktop_verify import load_claude_desktop_config, find_slimyos_entry

config = load_claude_desktop_config("$FAKE_CONFIG")
entry = find_slimyos_entry(config)
if entry is not None:
    print("ERROR: slimyos should not be found")
    sys.exit(1)
print("Correctly returns None when slimyos missing")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("missing_slimyos_detection_failed")
fi

echo ""
echo "=== Step 3: Test invalid launcher ==="
cat > "$FAKE_CONFIG" <<CONF
{
  "mcpServers": {
    "slimyos": {
      "command": "/nonexistent/launcher.sh",
      "args": []
    }
  }
}
CONF

python3 - <<PY
import sys
from adapters.claude_desktop_verify import load_claude_desktop_config, find_slimyos_entry, validate_launcher

config = load_claude_desktop_config("$FAKE_CONFIG")
entry = find_slimyos_entry(config)
launcher = validate_launcher(entry)
if launcher["valid"]:
    print("ERROR: launcher should be invalid")
    sys.exit(1)
print(f"Correctly detects invalid launcher: {launcher}")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("invalid_launcher_detection_failed")
fi

echo ""
echo "=== Step 4: Verify no real user config touched ==="
REAL_CFG="$HOME/.config/Claude/claude_desktop_config.json"
if [[ -f "$REAL_CFG" ]]; then
  echo "Real config exists (not modified by this smoke test)"
else
  echo "No real config found (safe)"
fi

echo ""
echo "=== Results ==="
if [[ ${#ERRORS[@]} -eq 0 ]]; then
  echo "RESULT=PASS" > "$PROOF_DIR/RESULT.txt"
  echo "All Claude Desktop verify smoke tests PASSED"
else
  echo "RESULT=FAIL" > "$PROOF_DIR/RESULT.txt"
  echo "FAILURES:"
  for e in "${ERRORS[@]}"; do
    echo "  - $e"
  done
fi

cat "$PROOF_DIR/RESULT.txt"
echo "Smoke proof directory: $PROOF_DIR"

if grep -q "RESULT=PASS" "$PROOF_DIR/RESULT.txt"; then
  exit 0
fi
exit 1
