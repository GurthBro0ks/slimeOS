#!/bin/bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UTC_NOW="$(date -u +%Y%m%dT%H%M%SZ)"
DEFAULT_PROOF_DIR="/tmp/proof_slimyos_claude_desktop_real_client_${UTC_NOW}"
PROOF_DIR="$DEFAULT_PROOF_DIR"
BROKER_URL="${SLIMYOS_TOOLD_URL:-http://localhost:3003}"
DASHBOARD_URL="${SLIMYOS_DASHBOARD_URL:-http://localhost:3002}"
WATCH_SECONDS=0
MODE="recent"

usage() {
  echo "Usage: $0 [--proof-dir <path>] [--broker-url <url>] [--dashboard-url <url>] [--recent] [--watch <seconds>]"
  echo ""
  echo "  --recent       Inspect recent audit events for Claude Desktop evidence (default)"
  echo "  --watch N      Watch for N seconds and wait for a fresh policy-enforced event"
  echo ""
  echo "Captures a formal real-client verification proof pack from SlimyOS audit/tool-broker evidence."
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
    --dashboard-url)
      DASHBOARD_URL="$2"
      shift 2
      ;;
    --recent)
      MODE="recent"
      shift
      ;;
    --watch)
      WATCH_SECONDS="$2"
      MODE="watch"
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

echo "SlimyOS Claude Desktop Real-Client Proof Pack"
echo "Repo root: $PROJECT_ROOT"
echo "Proof dir: $PROOF_DIR"
echo "Broker URL: $BROKER_URL"
echo "Dashboard URL: $DASHBOARD_URL"
echo "Mode: $MODE"

git -C "$PROJECT_ROOT" status -sb > "$PROOF_DIR/git_status_before.txt" 2>&1 || true
git -C "$PROJECT_ROOT" status --short >> "$PROOF_DIR/git_status_before.txt" 2>&1 || true

python3 - "$PROJECT_ROOT" "$PROOF_DIR" "$BROKER_URL" "$DASHBOARD_URL" "$WATCH_SECONDS" <<'PY'
import json
import sys
from adapters.prove_claude_desktop_client import run_proof

repo_root = sys.argv[1]
proof_dir = sys.argv[2]
broker_url = sys.argv[3]
dashboard_url = sys.argv[4]
watch_seconds = float(sys.argv[5])

meta = run_proof(
    repo_root=repo_root,
    proof_dir=proof_dir,
    broker_url=broker_url,
    dashboard_url=dashboard_url,
    watch_seconds=watch_seconds,
)

print(json.dumps(meta, indent=2))

if meta.get("result") == "FAIL":
    sys.exit(1)
PY

RESULT_CODE=$?

git -C "$PROJECT_ROOT" status -sb > "$PROOF_DIR/git_status_after.txt" 2>&1 || true
git -C "$PROJECT_ROOT" status --short >> "$PROOF_DIR/git_status_after.txt" 2>&1 || true
git -C "$PROJECT_ROOT" diff --name-only > "$PROOF_DIR/changed_files.txt" 2>&1 || true

if [[ $RESULT_CODE -eq 0 ]]; then
  if grep -q "PENDING_MANUAL" "$PROOF_DIR/RESULT.txt" 2>/dev/null; then
    echo "RESULT=PENDING_MANUAL" > "$PROOF_DIR/RESULT.txt"
  else
    echo "RESULT=PASS" > "$PROOF_DIR/RESULT.txt"
  fi
else
  echo "RESULT=FAIL" > "$PROOF_DIR/RESULT.txt"
fi

cat "$PROOF_DIR/RESULT.txt"
echo "Proof directory: $PROOF_DIR"

if grep -q "RESULT=PASS" "$PROOF_DIR/RESULT.txt" 2>/dev/null; then
  exit 0
elif grep -q "RESULT=PENDING_MANUAL" "$PROOF_DIR/RESULT.txt" 2>/dev/null; then
  exit 2
fi
exit 1
