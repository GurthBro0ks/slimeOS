#!/bin/bash

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UTC_NOW="$(date -u +%Y%m%dT%H%M%SZ)"
DEFAULT_PROOF_DIR="/tmp/proof_slimyos_claude_desktop_live_${UTC_NOW}"
PROOF_DIR="$DEFAULT_PROOF_DIR"
BROKER_URL="${SLIMYOS_TOOLD_URL:-http://localhost:3003}"

usage() {
  echo "Usage: $0 [--proof-dir <path>] [--broker-url <url>]"
  echo ""
  echo "Verifies installed Claude Desktop MCP config for SlimyOS."
  echo "Read-only. Does not mutate configs."
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --proof-dir)
      PROOF_DIR="$2"
      shift 2
      ;;
    --broker-url)
      BROKER_URL="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

mkdir -p "$PROOF_DIR"
SMOKE_OUTPUT="$PROOF_DIR/smoke_output.txt"
exec > >(tee "$SMOKE_OUTPUT") 2>&1

echo "SlimyOS Claude Desktop MCP post-install verification"
echo "Repo root: $PROJECT_ROOT"
echo "Proof dir: $PROOF_DIR"
echo "Broker URL: $BROKER_URL"

git -C "$PROJECT_ROOT" status -sb > "$PROOF_DIR/git_status_before.txt" 2>&1 || true
git -C "$PROJECT_ROOT" status --short >> "$PROOF_DIR/git_status_before.txt" 2>&1 || true

python3 - <<PY
import json
import sys
from adapters.claude_desktop_verify import run_full_verification

meta = run_full_verification(
    repo_root="$PROJECT_ROOT",
    proof_dir="$PROOF_DIR",
    broker_url="$BROKER_URL",
)

print(json.dumps(meta, indent=2))

print("\n--- Manual operator prompt ---")
with open("$PROOF_DIR/manual_operator_prompt.md") as f:
    print(f.read())

if meta.get("result") != "PASS":
    sys.exit(1)
PY

RESULT_CODE=$?

git -C "$PROJECT_ROOT" status -sb > "$PROOF_DIR/git_status_after.txt" 2>&1 || true
git -C "$PROJECT_ROOT" status --short >> "$PROOF_DIR/git_status_after.txt" 2>&1 || true
git -C "$PROJECT_ROOT" diff --name-only > "$PROOF_DIR/changed_files.txt" 2>&1 || true

if [[ $RESULT_CODE -eq 0 ]]; then
  echo "RESULT=PASS" > "$PROOF_DIR/RESULT.txt"
else
  echo "RESULT=FAIL" > "$PROOF_DIR/RESULT.txt"
fi

cat "$PROOF_DIR/RESULT.txt"
echo "Claude Desktop verify proof directory: $PROOF_DIR"

if [[ $RESULT_CODE -eq 0 ]]; then
  exit 0
fi
exit 1
