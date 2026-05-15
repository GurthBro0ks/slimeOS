#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TMP_PROOF_DIR="/tmp/proof_slimyos_mcp_healthline_$(date -u +%Y%m%dT%H%M%SZ)"

python3 - <<PY
from adapters.mcp_doctor import build_healthline, run_mcp_doctor

summary = run_mcp_doctor(
    repo_root="$PROJECT_ROOT",
    proof_dir="$TMP_PROOF_DIR",
    write_snippets=False,
)
print(build_healthline(summary))

if summary.get("result") != "PASS":
    raise SystemExit(1)
PY
