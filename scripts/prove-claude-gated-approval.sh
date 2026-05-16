#!/bin/bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UTC_NOW="$(date -u +%Y%m%dT%H%M%SZ)"
MODE=""
WATCH_SECONDS="180"
BROKER_URL="${SLIMYOS_TOOLD_URL:-http://localhost:3003}"
DASHBOARD_URL="${SLIMYOS_DASHBOARD_URL:-http://localhost:3002}"
GATED_TOOL="${SLIMYOS_GATED_TOOL_NAME:-git_commit}"
PROOF_DIR="/tmp/proof_slimyos_claude_gated_approval_${UTC_NOW}"

usage() {
  echo "Usage: $0 --prepare|--watch [--proof-dir <path>] [--watch-seconds <N>] [--broker-url <url>] [--dashboard-url <url>] [--gated-tool <name>]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prepare)
      MODE="prepare"
      shift
      ;;
    --watch)
      MODE="watch"
      shift
      ;;
    --watch-seconds)
      WATCH_SECONDS="$2"
      shift 2
      ;;
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
    --gated-tool)
      GATED_TOOL="$2"
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

if [[ -z "$MODE" ]]; then
  usage
  exit 1
fi

mkdir -p "$PROOF_DIR"
exec > >(tee "$PROOF_DIR/smoke_output.txt") 2>&1

echo "SlimyOS Claude Desktop gated approval proof"
echo "Repo root: $PROJECT_ROOT"
echo "Proof dir: $PROOF_DIR"
echo "Mode: $MODE"
echo "Broker URL: $BROKER_URL"
echo "Dashboard URL: $DASHBOARD_URL"
echo "Gated tool: $GATED_TOOL"

git -C "$PROJECT_ROOT" status -sb > "$PROOF_DIR/git_status_before.txt" 2>&1 || true
git -C "$PROJECT_ROOT" status --short >> "$PROOF_DIR/git_status_before.txt" 2>&1 || true

python3 - "$PROJECT_ROOT" "$PROOF_DIR" "$BROKER_URL" "$DASHBOARD_URL" "$MODE" "$WATCH_SECONDS" "$GATED_TOOL" <<'PY'
import json
import sys

from adapters.prove_claude_gated_approval import run_prepare, run_watch

repo_root, proof_dir, broker_url, dashboard_url, mode, watch_seconds, gated_tool = sys.argv[1:8]

if mode == "prepare":
    meta = run_prepare(
        repo_root=repo_root,
        proof_dir=proof_dir,
        broker_url=broker_url,
        dashboard_url=dashboard_url,
        gated_tool=gated_tool,
    )
else:
    meta = run_watch(
        repo_root=repo_root,
        proof_dir=proof_dir,
        broker_url=broker_url,
        dashboard_url=dashboard_url,
        timeout_seconds=int(watch_seconds),
        gated_tool=gated_tool,
    )

print(json.dumps(meta, indent=2))

result = meta.get("result", "FAIL")
if result == "FAIL":
    sys.exit(1)
if result == "PENDING_MANUAL":
    sys.exit(2)
sys.exit(0)
PY

RESULT_CODE=$?

git -C "$PROJECT_ROOT" status -sb > "$PROOF_DIR/git_status_after.txt" 2>&1 || true
git -C "$PROJECT_ROOT" status --short >> "$PROOF_DIR/git_status_after.txt" 2>&1 || true

if [[ -f "$PROOF_DIR/RESULT.txt" ]]; then
  cat "$PROOF_DIR/RESULT.txt"
else
  if [[ $RESULT_CODE -eq 0 ]]; then
    echo "RESULT=PASS" > "$PROOF_DIR/RESULT.txt"
  elif [[ $RESULT_CODE -eq 2 ]]; then
    echo "RESULT=PENDING_MANUAL" > "$PROOF_DIR/RESULT.txt"
  else
    echo "RESULT=FAIL" > "$PROOF_DIR/RESULT.txt"
  fi
  cat "$PROOF_DIR/RESULT.txt"
fi

echo "Proof directory: $PROOF_DIR"

if grep -q "RESULT=PASS" "$PROOF_DIR/RESULT.txt" 2>/dev/null; then
  exit 0
elif grep -q "RESULT=PENDING_MANUAL" "$PROOF_DIR/RESULT.txt" 2>/dev/null; then
  exit 2
fi
exit 1
