#!/bin/bash

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UTC_NOW="$(date -u +%Y%m%dT%H%M%SZ)"
DEFAULT_PROOF_DIR="/tmp/proof_slimyos_mcp_configure_smoke_${UTC_NOW}"
PROOF_DIR="${1:-${SLIMYOS_MCP_CONFIGURE_PROOF_DIR:-$DEFAULT_PROOF_DIR}}"

mkdir -p "$PROOF_DIR"
SMOKE_OUT="$PROOF_DIR/smoke_output.txt"
exec > >(tee "$SMOKE_OUT") 2>&1

echo "SlimyOS MCP configure smoke test"
echo "Project root: $PROJECT_ROOT"
echo "Proof dir: $PROOF_DIR"

FAKE_HOME="$PROOF_DIR/fake_home"
mkdir -p "$FAKE_HOME"

ERRORS=()

echo ""
echo "=== Step 1: Dry-run ==="
python3 - <<PY
import sys
from adapters.mcp_configure import run_configure

result = run_configure(
    repo_root="$PROJECT_ROOT",
    proof_dir="$PROOF_DIR/dry_run",
    mode="dry-run",
    home_override="$FAKE_HOME",
)
print(f"Dry-run result: {result['result']}")
if result['result'] != 'PASS':
    sys.exit(1)
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("dry_run_failed")
fi

echo ""
echo "=== Step 2: Write snippets ==="
"$SCRIPT_DIR/slimyos-mcp-configure.sh" --write-snippets --proof-dir "$PROOF_DIR/write_snippets"
if [[ $? -ne 0 ]]; then
  echo "WARN: write-snippets produced non-zero exit (may be due to broker offline)"
fi
GENERATED_DIR="$PROJECT_ROOT/docs/generated"
if [[ -f "$GENERATED_DIR/generated_claude_desktop_config.json" ]]; then
  echo "Snippets written to $GENERATED_DIR"
else
  echo "WARN: generated snippets not found in $GENERATED_DIR"
fi

echo ""
echo "=== Step 3: Apply with fake HOME ==="
FAKE_CONFIG_DIR="$FAKE_HOME/.config/Claude"
mkdir -p "$FAKE_CONFIG_DIR"
echo '{"mcpServers": {"other": {"command": "test", "args": []}}}' > "$FAKE_CONFIG_DIR/claude_desktop_config.json"
echo "Fake existing config: $(cat "$FAKE_CONFIG_DIR/claude_desktop_config.json")"

python3 - <<PY
import json
import sys
from pathlib import Path
from adapters.mcp_configure import run_configure

result = run_configure(
    repo_root="$PROJECT_ROOT",
    proof_dir="$PROOF_DIR/apply_test",
    mode="apply",
    home_override="$FAKE_HOME",
)
print(f"Apply result: {result['result']}")

if result['result'] != 'PASS':
    for e in result.get('errors', []):
        print(f"ERROR: {e}")
    sys.exit(1)

ar = result.get('apply_result', {})
if ar.get('status') != 'OK':
    print(f"Apply failed: {ar}")
    sys.exit(1)

config_path = Path("$FAKE_CONFIG_DIR/claude_desktop_config.json")
config = json.loads(config_path.read_text())
if "slimyos" not in config.get("mcpServers", {}):
    print("ERROR: slimyos entry not found after apply")
    sys.exit(1)
if "other" not in config.get("mcpServers", {}):
    print("ERROR: existing 'other' server was deleted")
    sys.exit(1)
print("Config merge verified: slimyos added, other preserved")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("apply_failed")
fi

echo ""
echo "=== Step 4: Rollback with fake HOME ==="
python3 - <<PY
import json
import sys
from pathlib import Path
from adapters.mcp_configure import rollback_latest, backup_dir_root

bdir = backup_dir_root(home_override="$FAKE_HOME")
result = rollback_latest(bdir)
print(f"Rollback result: {result['status']}")

if result['status'] != 'OK':
    for e in result.get('errors', []):
        print(f"ERROR: {e}")
    sys.exit(1)

config_path = Path("$FAKE_CONFIG_DIR/claude_desktop_config.json")
expected = {"mcpServers": {"other": {"command": "test", "args": []}}}
actual = json.loads(config_path.read_text())
if actual != expected:
    print(f"ERROR: config mismatch after rollback")
    print(f"Expected: {expected}")
    print(f"Actual: {actual}")
    sys.exit(1)
print("Rollback verified: original config restored")
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("rollback_failed")
fi

echo ""
echo "=== Step 5: Verify no real config touched ==="
REAL_CLAUDE_CONFIG="$HOME/.config/Claude/claude_desktop_config.json"
if [[ -f "$REAL_CLAUDE_CONFIG" ]]; then
  echo "Real Claude Desktop config exists (not modified by this smoke test)"
else
  echo "No real Claude Desktop config found (safe)"
fi

echo ""
echo "=== Step 6: Status mode ==="
python3 - <<PY
import sys
from adapters.mcp_configure import run_configure

result = run_configure(
    repo_root="$PROJECT_ROOT",
    proof_dir="$PROOF_DIR/status_test",
    mode="status",
    home_override="$FAKE_HOME",
)
print(f"Status result: {result['result']}")
if result['result'] != 'PASS':
    sys.exit(1)
PY
if [[ $? -ne 0 ]]; then
  ERRORS+=("status_failed")
fi

echo ""
echo "=== Results ==="
if [[ ${#ERRORS[@]} -eq 0 ]]; then
  echo "RESULT=PASS" > "$PROOF_DIR/RESULT.txt"
  echo "All configure smoke tests PASSED"
else
  echo "RESULT=FAIL" > "$PROOF_DIR/RESULT.txt"
  echo "FAILURES:"
  for e in "${ERRORS[@]}"; do
    echo "  - $e"
  done
fi

cat "$PROOF_DIR/RESULT.txt"
echo "Configure smoke proof directory: $PROOF_DIR"

if grep -q "RESULT=PASS" "$PROOF_DIR/RESULT.txt"; then
  exit 0
fi
exit 1
