#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BROKER_URL="${SLIMYOS_TOOLD_URL:-http://localhost:3003}"

if ! curl -sS "$BROKER_URL/health" >/dev/null 2>&1; then
  echo "[slimyos-mcp] error: Tool Broker unreachable at $BROKER_URL" >&2
  echo "[slimyos-mcp] start it with: python3 serve.py" >&2
  exit 1
fi

cd "$PROJECT_ROOT"
exec python3 adapters/mcp_server.py
