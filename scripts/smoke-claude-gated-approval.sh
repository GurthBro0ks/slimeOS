#!/bin/bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UTC_NOW="$(date -u +%Y%m%dT%H%M%SZ)"
PROOF_DIR="${1:-/tmp/proof_slimyos_claude_gated_approval_smoke_${UTC_NOW}}"

mkdir -p "$PROOF_DIR"
exec > >(tee "$PROOF_DIR/smoke_output.txt") 2>&1

echo "SlimyOS Claude gated approval smoke"
echo "Project root: $PROJECT_ROOT"
echo "Proof dir: $PROOF_DIR"

python3 - "$PROJECT_ROOT" "$PROOF_DIR" <<'PY'
import json
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
proof_dir = Path(sys.argv[2])

sys.path.insert(0, str(repo_root))
from adapters import prove_claude_gated_approval as pcga

errors = []
warnings = []

config_path = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
config_exists = config_path.exists()
before_stat = config_path.stat().st_mtime if config_exists else None

event = {
    "event_id": "evt-pass",
    "tool_name": "git_commit",
    "disposition": "approval_required",
    "tool_args": {
        "repo_path": "/tmp/demo",
        "message": "harmless",
        "access_token": "[REDACTED]",
    },
    "metadata": {"approval_id": "apr-pass"},
    "client_identity": {
        "client_id": "claude_desktop",
        "client_name": "Claude Desktop",
        "transport": "mcp_stdio",
    },
}
approval = {
    "approval_id": "apr-pass",
    "tool_name": "git_commit",
    "disposition": "approval_required",
    "status": "pending",
    "execution_status": "not_executed",
    "requested_args_redacted": {
        "repo_path": "/tmp/demo",
        "message": "harmless",
        "access_token": "[REDACTED]",
    },
    "client_identity": {
        "client_id": "claude_desktop",
        "client_name": "Claude Desktop",
        "transport": "mcp_stdio",
    },
}
state = {"pending_approvals": [{"approval_id": "apr-pass", "status": "pending"}]}

pass_result = pcga.evaluate_approval_observation(approval, event, state, True, gated_tool="git_commit")
if pass_result.get("result") != "PASS":
    errors.append(f"pass_path_failed:{pass_result}")

pending_result = pcga.evaluate_approval_observation(None, None, state, True, gated_tool="git_commit")
if pending_result.get("result") != "PENDING_MANUAL":
    errors.append(f"pending_manual_path_failed:{pending_result}")

missing_ci_approval = dict(approval)
missing_ci_approval["approval_id"] = "apr-no-ci"
missing_ci_approval["client_identity"] = {}
missing_ci_event = dict(event)
missing_ci_event["metadata"] = {"approval_id": "apr-no-ci"}
missing_ci_event["client_identity"] = {}
missing_ci_state = {"pending_approvals": [{"approval_id": "apr-no-ci", "status": "pending"}]}
missing_ci = pcga.evaluate_approval_observation(missing_ci_approval, missing_ci_event, missing_ci_state, True, gated_tool="git_commit")
if missing_ci.get("result") != "FAIL" or "client_identity_not_claude_desktop" not in missing_ci.get("errors", []):
    errors.append(f"missing_client_identity_not_failed:{missing_ci}")

unknown_ci_approval = dict(approval)
unknown_ci_approval["approval_id"] = "apr-unknown-ci"
unknown_ci_approval["client_identity"] = {
    "client_id": "unknown",
    "client_name": "Unknown Client",
    "transport": "mcp_stdio",
}
unknown_ci_event = dict(event)
unknown_ci_event["metadata"] = {"approval_id": "apr-unknown-ci"}
unknown_ci_state = {"pending_approvals": [{"approval_id": "apr-unknown-ci", "status": "pending"}]}
unknown_ci = pcga.evaluate_approval_observation(unknown_ci_approval, unknown_ci_event, unknown_ci_state, True, gated_tool="git_commit")
if unknown_ci.get("result") != "FAIL" or "client_identity_not_claude_desktop" not in unknown_ci.get("errors", []):
    errors.append(f"unknown_client_identity_not_failed:{unknown_ci}")

executed_approval = dict(approval)
executed_approval["approval_id"] = "apr-executed"
executed_approval["execution_status"] = "executed"
executed_event = dict(event)
executed_event["metadata"] = {"approval_id": "apr-executed"}
executed_state = {"pending_approvals": [{"approval_id": "apr-executed", "status": "pending"}]}
executed = pcga.evaluate_approval_observation(executed_approval, executed_event, executed_state, True, gated_tool="git_commit")
if executed.get("result") != "FAIL":
    errors.append(f"executed_status_not_failed:{executed}")

secret_leak_approval = dict(approval)
secret_leak_approval["approval_id"] = "apr-secret"
secret_leak_approval["requested_args_redacted"] = {
    "repo_path": "/tmp/demo",
    "api_key": "not-redacted-secret-value-123456",
}
secret_leak_event = dict(event)
secret_leak_event["metadata"] = {"approval_id": "apr-secret"}
secret_leak_state = {"pending_approvals": [{"approval_id": "apr-secret", "status": "pending"}]}
secret_leak = pcga.evaluate_approval_observation(secret_leak_approval, secret_leak_event, secret_leak_state, True, gated_tool="git_commit")
if secret_leak.get("result") != "FAIL":
    errors.append(f"secret_leak_not_failed:{secret_leak}")

repo_changed = pcga.evaluate_approval_observation(approval, event, state, False, gated_tool="git_commit")
if repo_changed.get("result") != "FAIL" or "real_repo_changed" not in repo_changed.get("errors", []):
    errors.append(f"repo_changed_not_failed:{repo_changed}")

if config_exists:
    after_stat = config_path.stat().st_mtime
    if before_stat != after_stat:
        errors.append("real_claude_config_touched")

result = "PASS" if not errors else "FAIL"

(proof_dir / "pass_result.json").write_text(json.dumps(pass_result, indent=2), encoding="utf-8")
(proof_dir / "pending_result.json").write_text(json.dumps(pending_result, indent=2), encoding="utf-8")
(proof_dir / "missing_ci_result.json").write_text(json.dumps(missing_ci, indent=2), encoding="utf-8")
(proof_dir / "unknown_ci_result.json").write_text(json.dumps(unknown_ci, indent=2), encoding="utf-8")
(proof_dir / "executed_result.json").write_text(json.dumps(executed, indent=2), encoding="utf-8")
(proof_dir / "secret_leak_result.json").write_text(json.dumps(secret_leak, indent=2), encoding="utf-8")
(proof_dir / "repo_changed_result.json").write_text(json.dumps(repo_changed, indent=2), encoding="utf-8")
(proof_dir / "warnings.json").write_text(json.dumps(warnings, indent=2), encoding="utf-8")
(proof_dir / "errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
(proof_dir / "RESULT.txt").write_text(f"RESULT={result}\n", encoding="utf-8")

print(f"RESULT={result}")
if errors:
    print(json.dumps(errors, indent=2))
    raise SystemExit(1)
PY

echo "Proof directory: $PROOF_DIR"
