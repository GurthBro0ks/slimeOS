#!/bin/bash
# Gate: ensure no freeform sudo in codebase
set -euo pipefail
HITS=$(grep -r "subprocess.*sudo\|os.system.*sudo\|Popen.*sudo" services/ tools/ --include="*.py" -l 2>/dev/null || true)
if [ -n "$HITS" ]; then
    echo "❌ Freeform sudo found in: $HITS"
    exit 1
fi
echo "✅ No freeform sudo in codebase"
