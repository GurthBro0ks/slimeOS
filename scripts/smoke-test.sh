#!/bin/bash
# SlimyOS Smoke Test
# Runs the integration test and reports results.
# Exit 0 = all pass, Exit 1 = failures

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo ""
echo "🐌 SlimyOS Habitat — Smoke Test"
echo "================================"
echo ""

cd "$PROJECT_ROOT"

python3 tests/test_integration.py
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "🐌 All checks passed. SlimyOS Habitat proof-of-life verified."
else
    echo "❌ Some checks failed. See output above."
fi

exit $EXIT_CODE
