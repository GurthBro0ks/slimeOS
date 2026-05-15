#!/bin/bash

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UTC_NOW="$(date -u +%Y%m%dT%H%M%SZ)"
DEFAULT_PROOF_DIR="/tmp/proof_slimyos_mcp_configure_${UTC_NOW}"
PROOF_DIR="$DEFAULT_PROOF_DIR"
MODE="dry-run"
WRITE_SNIPPETS=0
BROKER_URL="${SLIMYOS_TOOLD_URL:-http://localhost:3003}"

usage() {
  echo "Usage: $0 [--apply] [--rollback] [--status] [--write-snippets] [--proof-dir <path>] [--broker-url <url>]"
  echo ""
  echo "Modes:"
  echo "  (default)        Dry-run: detect config paths, generate snippets into proof dir only"
  echo "  --write-snippets Write generated snippets into docs/generated/"
  echo "  --apply          Safely apply supported config changes with backup"
  echo "  --rollback       Restore most recent backup created by this script"
  echo "  --status         Show current detected config state (no mutation)"
  echo ""
  echo "Options:"
  echo "  --proof-dir DIR  Override proof directory"
  echo "  --broker-url URL Override broker URL (default: http://localhost:3003)"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      MODE="apply"
      shift
      ;;
    --rollback)
      MODE="rollback"
      shift
      ;;
    --status)
      MODE="status"
      shift
      ;;
    --write-snippets)
      WRITE_SNIPPETS=1
      shift
      ;;
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

echo "SlimyOS MCP configure"
echo "Mode: $MODE"
echo "Repo root: $PROJECT_ROOT"
echo "Proof dir: $PROOF_DIR"
echo "Broker URL: $BROKER_URL"
echo "Write snippets: $WRITE_SNIPPETS"

git -C "$PROJECT_ROOT" status -sb > "$PROOF_DIR/git_status_before.txt" 2>&1 || true
git -C "$PROJECT_ROOT" status --short >> "$PROOF_DIR/git_status_before.txt" 2>&1 || true

if [[ "$MODE" == "apply" ]]; then
  echo ""
  echo "WARNING: --apply will modify MCP client config files."
  echo "A timestamped backup will be created before any changes."
  echo ""
fi

python3 - <<PY
import json
import sys
from adapters.mcp_configure import run_configure

summary = run_configure(
    repo_root="$PROJECT_ROOT",
    proof_dir="$PROOF_DIR",
    broker_url="$BROKER_URL",
    mode="$MODE",
)

print(json.dumps({k: v for k, v in summary.items() if k != "detected"}, indent=2))

print("\n--- Detected clients ---")
detected = summary.get("detected", {})
for client, info in detected.items():
    print(f"  {client}: status={info.get('status', 'unknown')}")

if "$MODE" == "dry-run":
    print("\n--- Generated snippets in proof dir ---")
    print(f"  $PROOF_DIR/generated_claude_desktop_config.json")
    print(f"  $PROOF_DIR/generated_claude_code_notes.md")
    print(f"  $PROOF_DIR/generated_opencode_notes.md")
    print(f"  $PROOF_DIR/generated_codex_notes.md")

if "$MODE" == "apply" and summary.get("apply_result"):
    ar = summary["apply_result"]
    print(f"\nApply result: {ar.get('status', 'unknown')}")
    if ar.get("backup"):
        print(f"Backup: {ar['backup'].get('backup_dir', 'unknown')}")

if "$MODE" == "rollback" and summary.get("rollback_result"):
    rr = summary["rollback_result"]
    print(f"\nRollback result: {rr.get('status', 'unknown')}")
    print(f"Restored from: {rr.get('restored_from', 'unknown')}")

if "$MODE" == "status" and summary.get("status_result"):
    sr = summary["status_result"]
    print("\n--- Status ---")
    for client, info in sr.get("clients", {}).items():
        print(f"  {client}: {json.dumps(info)}")

if "$MODE" == "dry-run":
    print("\nTo apply: $0 --apply")
    print("To rollback: $0 --rollback")
    print("To check status: $0 --status")

if summary.get("result") != "PASS":
    sys.exit(1)
PY

RESULT_CODE=$?

if [[ "$WRITE_SNIPPETS" -eq 1 ]]; then
  GENERATED_DIR="$PROJECT_ROOT/docs/generated"
  mkdir -p "$GENERATED_DIR"
  for f in "$PROOF_DIR"/generated_*; do
    [[ -f "$f" ]] && cp "$f" "$GENERATED_DIR/"
  done
  echo "Snippets written to $GENERATED_DIR"
fi

git -C "$PROJECT_ROOT" status -sb > "$PROOF_DIR/git_status_after.txt" 2>&1 || true
git -C "$PROJECT_ROOT" status --short >> "$PROOF_DIR/git_status_after.txt" 2>&1 || true
git -C "$PROJECT_ROOT" diff --name-only > "$PROOF_DIR/changed_files.txt" 2>&1 || true

if [[ $RESULT_CODE -eq 0 ]]; then
  echo "RESULT=PASS" > "$PROOF_DIR/RESULT.txt"
else
  echo "RESULT=FAIL" > "$PROOF_DIR/RESULT.txt"
fi

cat "$PROOF_DIR/RESULT.txt"
echo "MCP configure proof directory: $PROOF_DIR"

if [[ $RESULT_CODE -eq 0 ]]; then
  exit 0
fi
exit 1
