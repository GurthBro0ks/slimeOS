#!/bin/bash

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UTC_NOW="$(date -u +%Y%m%dT%H%M%SZ)"
DEFAULT_PROOF_DIR="/tmp/proof_slimyos_mcp_doctor_${UTC_NOW}"
PROOF_DIR="$DEFAULT_PROOF_DIR"
WRITE_SNIPPETS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --write-snippets)
      WRITE_SNIPPETS=1
      shift
      ;;
    --proof-dir)
      PROOF_DIR="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--write-snippets] [--proof-dir <path>]" >&2
      exit 1
      ;;
  esac
done

mkdir -p "$PROOF_DIR"
SMOKE_OUTPUT="$PROOF_DIR/smoke_output.txt"
exec > >(tee "$SMOKE_OUTPUT") 2>&1

echo "SlimyOS MCP doctor (dry-run by default)"
echo "Repo root: $PROJECT_ROOT"
echo "Proof dir: $PROOF_DIR"
echo "write_snippets: $WRITE_SNIPPETS"

git -C "$PROJECT_ROOT" status -sb > "$PROOF_DIR/git_status_before.txt" 2>&1 || true
git -C "$PROJECT_ROOT" status --short >> "$PROOF_DIR/git_status_before.txt" 2>&1 || true

python3 - <<PY
import json
import sys
from adapters.mcp_doctor import run_mcp_doctor

summary = run_mcp_doctor(
    repo_root="$PROJECT_ROOT",
    proof_dir="$PROOF_DIR",
    write_snippets=bool($WRITE_SNIPPETS),
)

print(json.dumps(summary, indent=2))

print("\n--- Generated snippets ---")
for name in (
    "generated_claude_desktop_config.json",
    "generated_claude_code_notes.md",
    "generated_opencode_notes.md",
    "generated_codex_notes.md",
):
    print(f"\n## {name}")
    with open(f"$PROOF_DIR/{name}", "r", encoding="utf-8") as handle:
        print(handle.read())

if summary.get("result") != "PASS":
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
echo "MCP doctor proof directory: $PROOF_DIR"

if [[ $RESULT_CODE -eq 0 ]]; then
  exit 0
fi
exit 1
