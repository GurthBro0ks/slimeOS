#!/bin/bash

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UTC_NOW="$(date -u +%Y%m%dT%H%M%SZ)"
DEFAULT_PROOF_DIR="/tmp/proof_slimyos_client_preflight_${UTC_NOW}"
PROOF_DIR="${1:-${SLIMYOS_PREFLIGHT_PROOF_DIR:-$DEFAULT_PROOF_DIR}}"

mkdir -p "$PROOF_DIR"
PRE_OUT="$PROOF_DIR/preflight_output.txt"
exec > >(tee "$PRE_OUT") 2>&1

echo "SlimyOS client adapter preflight"
echo "Project root: $PROJECT_ROOT"
echo "Proof dir: $PROOF_DIR"

python3 - <<PY
import json
from pathlib import Path
from adapters.client_preflight import PreflightConfig, run_client_preflight, write_preflight_artifacts

project_root = Path("$PROJECT_ROOT")
proof_dir = Path("$PROOF_DIR")

cfg = PreflightConfig(repo_path=str(project_root))
result = run_client_preflight(cfg)
write_preflight_artifacts(result, str(proof_dir))

if result.get("broker_health"):
    (proof_dir / "broker_health.json").write_text(json.dumps(result["broker_health"], indent=2))
if result.get("dashboard_runtime"):
    (proof_dir / "dashboard_runtime.json").write_text(json.dumps(result["dashboard_runtime"], indent=2))

print(json.dumps({
    "final_result": result.get("final_result"),
    "warnings": result.get("warnings", []),
    "errors": result.get("errors", []),
    "proof_dir": str(proof_dir),
}, indent=2))
PY

RESULT_LINE="$(cat "$PROOF_DIR/RESULT.txt" 2>/dev/null || true)"
echo "${RESULT_LINE}"
echo "Client preflight proof directory: $PROOF_DIR"

if [[ "$RESULT_LINE" == "RESULT=PASS" ]]; then
  exit 0
fi
exit 1
