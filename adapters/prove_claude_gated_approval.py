"""Proof workflow for real Claude Desktop gated approval visibility.

This module supports two modes used by scripts/prove-claude-gated-approval.sh:
- prepare: collect health/baseline evidence and emit manual operator prompt
- watch: wait for a real Claude Desktop approval_required event and verify
  pending approval visibility in Mission Control without execution
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from adapters.claude_desktop_verify import (
    find_slimyos_entry,
    load_claude_desktop_config,
    redact_entry,
)


SECRET_KEY_RE = re.compile(
    r"(key|token|secret|password|auth|credential|api[_-]?key)",
    re.IGNORECASE,
)
TOKENISH_VALUE_RE = re.compile(r"[A-Za-z0-9_\-]{20,}")
CHAT_KEY_RE = re.compile(r"(chat|conversation|prompt|messages|history)", re.IGNORECASE)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_get_json(url: str, timeout: float = 3.0) -> dict[str, Any]:
    with urlrequest.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read())


def _safe_http_get_json(url: str) -> tuple[dict[str, Any], str]:
    try:
        return _http_get_json(url), ""
    except Exception as exc:
        return {}, str(exc)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events) + ("\n" if events else ""), encoding="utf-8")


def _run_git(repo_root: str, *args: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode == 0, output.strip()


def snapshot_repo_state(repo_root: str) -> dict[str, Any]:
    ok_head, head_out = _run_git(repo_root, "rev-parse", "HEAD")
    ok_status, status_out = _run_git(repo_root, "status", "--porcelain")
    return {
        "head_ok": ok_head,
        "head": head_out if ok_head else "",
        "status_ok": ok_status,
        "status_porcelain": status_out if ok_status else "",
    }


def repo_unchanged(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return (
        before.get("head", "") == after.get("head", "")
        and before.get("status_porcelain", "") == after.get("status_porcelain", "")
    )


def redact_secret_like_args(payload: Any) -> Any:
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        omitted = 0
        for key, value in payload.items():
            if CHAT_KEY_RE.search(key or ""):
                omitted += 1
                continue
            if SECRET_KEY_RE.search(key or ""):
                out[key] = "[REDACTED]"
            else:
                out[key] = redact_secret_like_args(value)
        if omitted:
            out["private_fields_omitted"] = out.get("private_fields_omitted", 0) + omitted
        return out
    if isinstance(payload, list):
        return [redact_secret_like_args(item) for item in payload]
    if isinstance(payload, str):
        if TOKENISH_VALUE_RE.search(payload) and any(ch.isdigit() for ch in payload):
            return "[REDACTED]"
        return payload
    return payload


def contains_chat_text(payload: Any) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if CHAT_KEY_RE.search(key or ""):
                return True
            if contains_chat_text(value):
                return True
        return False
    if isinstance(payload, list):
        return any(contains_chat_text(item) for item in payload)
    return False


def contains_unredacted_secret_like_values(payload: Any) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, str) and SECRET_KEY_RE.search(key or ""):
                if value != "[REDACTED]":
                    return True
            if contains_unredacted_secret_like_values(value):
                return True
        return False
    if isinstance(payload, list):
        return any(contains_unredacted_secret_like_values(item) for item in payload)
    return False


def normalize_tool_name(tool_name: str) -> str:
    return tool_name[8:] if tool_name.startswith("slimyos_") else tool_name


def extract_approval_id_from_event(event: dict[str, Any] | None) -> str:
    if not event:
        return ""
    metadata = event.get("metadata", {}) or {}
    return str(metadata.get("approval_id") or event.get("approval_id") or "")


def find_matching_event(events: list[dict[str, Any]], gated_tool: str) -> dict[str, Any] | None:
    for event in reversed(events):
        if normalize_tool_name(str(event.get("tool_name", ""))) != gated_tool:
            continue
        if event.get("disposition") != "approval_required":
            continue
        return event
    return None


def find_matching_approval(approvals: list[dict[str, Any]], gated_tool: str, approval_id: str = "") -> dict[str, Any] | None:
    for approval in reversed(approvals):
        if approval_id and str(approval.get("approval_id", "")) != approval_id:
            continue
        if normalize_tool_name(str(approval.get("tool_name", ""))) != gated_tool:
            continue
        return approval
    return None


def evaluate_approval_observation(
    approval: dict[str, Any] | None,
    event: dict[str, Any] | None,
    dashboard_state: dict[str, Any] | None,
    repo_unchanged_ok: bool,
    gated_tool: str = "git_commit",
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not approval and not event:
        return {
            "result": "PENDING_MANUAL",
            "errors": [],
            "warnings": ["no_matching_event_or_approval"],
            "approval_id": "",
            "tool_name": "",
            "original_tool_name": "",
            "policy_rule": "",
            "approval_status": "",
            "client_identity": {},
            "pending_approval_card": {},
        }

    approval_id = str((approval or {}).get("approval_id", "") or extract_approval_id_from_event(event))
    if not approval_id:
        errors.append("missing_approval_id")

    original_tool_name = str((approval or {}).get("tool_name", "") or (event or {}).get("tool_name", ""))
    tool_name = normalize_tool_name(original_tool_name)
    if tool_name != gated_tool:
        errors.append(f"unexpected_tool_name:{tool_name}")

    disposition = str((event or {}).get("disposition", "") or (approval or {}).get("disposition", ""))
    if disposition != "approval_required":
        errors.append(f"unexpected_disposition:{disposition}")

    approval_status = str((approval or {}).get("status", ""))
    if approval_status and approval_status != "pending":
        errors.append(f"approval_status_not_pending:{approval_status}")
    elif not approval_status:
        errors.append("approval_status_missing")

    execution_status = str((approval or {}).get("execution_status", ""))
    if execution_status == "executed":
        errors.append("execution_already_happened")

    ci = (approval or {}).get("client_identity", {}) or (event or {}).get("client_identity", {}) or {}
    if str(ci.get("client_id", "")) != "claude_desktop":
        errors.append("client_identity_not_claude_desktop")

    pending_approval_card: dict[str, Any] = {}
    pending_list = (dashboard_state or {}).get("pending_approvals", []) if dashboard_state else []
    for item in pending_list:
        if str(item.get("approval_id", "")) == approval_id:
            pending_approval_card = item
            break
    if not pending_approval_card:
        errors.append("dashboard_pending_approval_missing")

    approval_args = dict((approval or {}).get("requested_args_redacted", {}) or {})
    event_args = dict((event or {}).get("tool_args", {}) or {})
    if contains_chat_text(approval_args) or contains_chat_text(event_args):
        errors.append("chat_text_detected_in_stored_payload")
    if contains_unredacted_secret_like_values(approval_args) or contains_unredacted_secret_like_values(event_args):
        errors.append("unredacted_secret_like_values_detected")

    if not repo_unchanged_ok:
        errors.append("real_repo_changed")

    if errors:
        return {
            "result": "FAIL",
            "errors": errors,
            "warnings": warnings,
            "approval_id": approval_id,
            "tool_name": tool_name,
            "original_tool_name": original_tool_name,
            "policy_rule": str((approval or {}).get("policy_rule", "") or (event or {}).get("policy_rule", "")),
            "approval_status": approval_status,
            "client_identity": ci,
            "pending_approval_card": pending_approval_card,
        }

    return {
        "result": "PASS",
        "errors": [],
        "warnings": warnings,
        "approval_id": approval_id,
        "tool_name": tool_name,
        "original_tool_name": original_tool_name,
        "policy_rule": str((approval or {}).get("policy_rule", "") or (event or {}).get("policy_rule", "")),
        "approval_status": approval_status,
        "client_identity": ci,
        "pending_approval_card": pending_approval_card,
    }


def preflight_checks(repo_root: str, broker_url: str, dashboard_url: str) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    broker_health: dict[str, Any] = {}
    dashboard_health: dict[str, Any] = {}
    dashboard_state: dict[str, Any] = {}
    tools_payload: dict[str, Any] = {}

    try:
        broker_health = _http_get_json(f"{broker_url.rstrip('/')}/health")
        if broker_health.get("status") != "ok":
            errors.append("broker_health_not_ok")
    except Exception as exc:
        errors.append(f"broker_unreachable:{exc}")

    try:
        tools_payload = _http_get_json(f"{broker_url.rstrip('/')}/tools")
        if int(tools_payload.get("count", 0)) <= 0:
            errors.append("broker_tool_manifest_empty")
    except Exception as exc:
        errors.append(f"broker_tools_unreachable:{exc}")

    try:
        dashboard_health = _http_get_json(f"{dashboard_url.rstrip('/')}/health")
        if dashboard_health.get("status") != "ok":
            errors.append("dashboard_health_not_ok")
    except Exception as exc:
        errors.append(f"dashboard_unreachable:{exc}")

    try:
        dashboard_state = _http_get_json(f"{dashboard_url.rstrip('/')}/api/state")
    except Exception as exc:
        errors.append(f"dashboard_state_unreachable:{exc}")

    policy_candidates = [
        Path(repo_root) / "policies" / "default.policy.json",
        Path(os.path.expanduser("~/.slimyos/config/policy.json")),
    ]
    if not any(p.exists() for p in policy_candidates):
        errors.append("policy_file_missing")

    config_path = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
    slimyos_entry: dict[str, Any] = {}
    if not config_path.exists():
        errors.append("claude_desktop_config_missing")
    else:
        try:
            config = load_claude_desktop_config(str(config_path))
            entry = find_slimyos_entry(config)
            if not entry:
                errors.append("slimyos_mcp_entry_missing")
            else:
                slimyos_entry = redact_entry(entry)
        except Exception as exc:
            errors.append(f"claude_config_read_failed:{exc}")

    mcp_healthline_output = ""
    healthline_script = Path(repo_root) / "scripts" / "slimyos-mcp-healthline.sh"
    if healthline_script.exists():
        try:
            proc = subprocess.run(
                [str(healthline_script)],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            mcp_healthline_output = (proc.stdout or "").strip()
            if proc.returncode != 0:
                warnings.append(f"mcp_healthline_nonzero:{proc.returncode}")
        except Exception as exc:
            warnings.append(f"mcp_healthline_failed:{exc}")

    return {
        "errors": errors,
        "warnings": warnings,
        "broker_health": broker_health,
        "dashboard_health": dashboard_health,
        "dashboard_state": dashboard_state,
        "tools_payload": tools_payload,
        "config_path": str(config_path),
        "slimyos_entry": slimyos_entry,
        "mcp_healthline": mcp_healthline_output,
    }


def run_prepare(
    repo_root: str,
    proof_dir: str,
    broker_url: str,
    dashboard_url: str,
    gated_tool: str = "git_commit",
) -> dict[str, Any]:
    out = Path(proof_dir)
    out.mkdir(parents=True, exist_ok=True)

    check = preflight_checks(repo_root, broker_url, dashboard_url)
    errors = list(check["errors"])
    warnings = list(check["warnings"])

    audit_before: list[dict[str, Any]] = []
    approvals_before: list[dict[str, Any]] = []
    if not errors:
        audit_payload, audit_err = _safe_http_get_json(f"{broker_url.rstrip('/')}/audit/recent")
        approvals_payload, approvals_err = _safe_http_get_json(f"{broker_url.rstrip('/')}/approvals")
        if audit_err:
            errors.append(f"audit_recent_unreachable:{audit_err}")
        else:
            audit_before = audit_payload.get("events", [])
        if approvals_err:
            errors.append(f"approvals_unreachable:{approvals_err}")
        else:
            approvals_before = approvals_payload.get("approvals", [])
    dashboard_before = check.get("dashboard_state", {})

    repo_before = snapshot_repo_state(repo_root)
    repo_after = snapshot_repo_state(repo_root)
    unchanged = repo_unchanged(repo_before, repo_after)

    manual_prompt = (
        'Use the SlimyOS MCP tools to request a git_commit with a harmless test message, '
        'but do not execute anything. I only want to verify that SlimyOS returns '
        'approval_required and creates a Mission Control approval card.'
    )

    (out / "manual_operator_prompt.md").write_text(
        "# Manual Claude Desktop Prompt\n\n"
        "Paste this into Claude Desktop:\n\n"
        f"\"{manual_prompt}\"\n",
        encoding="utf-8",
    )

    _write_json(out / "meta.json", {
        "timestamp": _now_utc(),
        "mode": "prepare",
        "repo_root": repo_root,
        "broker_url": broker_url,
        "dashboard_url": dashboard_url,
        "gated_tool": gated_tool,
    })
    (out / "claude_config_path.txt").write_text(check.get("config_path", "") + "\n", encoding="utf-8")
    _write_json(out / "slimyos_mcp_entry.json", check.get("slimyos_entry", {}))
    _write_json(out / "broker_health.json", check.get("broker_health", {}))
    _write_json(out / "dashboard_state_before.json", dashboard_before)
    _write_json(out / "dashboard_state_after.json", dashboard_before)
    _write_json(out / "approvals_before.json", {"approvals": approvals_before, "count": len(approvals_before)})
    _write_json(out / "approvals_after.json", {"approvals": approvals_before, "count": len(approvals_before)})
    _write_jsonl(out / "audit_tail_before.jsonl", audit_before[-100:])
    _write_jsonl(out / "audit_tail_after.jsonl", audit_before[-100:])
    _write_json(out / "detected_claude_approval.json", {})
    _write_json(out / "pending_approval_card.json", {})
    (out / "real_repo_status_before.txt").write_text(repo_before.get("status_porcelain", "") + "\n", encoding="utf-8")
    (out / "real_repo_status_after.txt").write_text(repo_after.get("status_porcelain", "") + "\n", encoding="utf-8")
    _write_json(out / "safety_check.json", {
        "real_repo_unchanged": unchanged,
        "no_execution_performed": True,
    })
    _write_json(out / "privacy_check.json", {
        "chat_text_stored": False,
        "unredacted_secret_like_values": False,
    })
    _write_json(out / "warnings.json", warnings)
    _write_json(out / "errors.json", errors)

    ok_diff, diff_out = _run_git(repo_root, "diff", "--name-only")
    changed = diff_out if ok_diff else ""
    (out / "changed_files.txt").write_text(changed + ("\n" if changed else ""), encoding="utf-8")

    result = "FAIL" if errors else "PENDING_MANUAL"
    (out / "RESULT.txt").write_text(f"RESULT={result}\n", encoding="utf-8")

    return {
        "result": result,
        "proof_dir": str(out),
        "errors": errors,
        "warnings": warnings,
        "manual_prompt": manual_prompt,
    }


def run_watch(
    repo_root: str,
    proof_dir: str,
    broker_url: str,
    dashboard_url: str,
    timeout_seconds: int = 180,
    gated_tool: str = "git_commit",
) -> dict[str, Any]:
    out = Path(proof_dir)
    out.mkdir(parents=True, exist_ok=True)

    check = preflight_checks(repo_root, broker_url, dashboard_url)
    errors = list(check["errors"])
    warnings = list(check["warnings"])

    if errors:
        _write_json(out / "meta.json", {
            "timestamp": _now_utc(),
            "mode": "watch",
            "repo_root": repo_root,
            "broker_url": broker_url,
            "dashboard_url": dashboard_url,
            "gated_tool": gated_tool,
            "timeout_seconds": timeout_seconds,
        })
        (out / "manual_operator_prompt.md").write_text(
            "# Manual Claude Desktop Prompt\n\n"
            "Use the SlimyOS MCP tools to request a git_commit with a harmless test message, "
            "but do not execute anything. I only want to verify that SlimyOS returns "
            "approval_required and creates a Mission Control approval card.\n",
            encoding="utf-8",
        )
        (out / "claude_config_path.txt").write_text(check.get("config_path", "") + "\n", encoding="utf-8")
        _write_json(out / "slimyos_mcp_entry.json", check.get("slimyos_entry", {}))
        _write_json(out / "broker_health.json", check.get("broker_health", {}))
        _write_json(out / "dashboard_state_before.json", check.get("dashboard_state", {}))
        _write_json(out / "dashboard_state_after.json", check.get("dashboard_state", {}))
        _write_json(out / "approvals_before.json", {"approvals": [], "count": 0})
        _write_json(out / "approvals_after.json", {"approvals": [], "count": 0})
        _write_jsonl(out / "audit_tail_before.jsonl", [])
        _write_jsonl(out / "audit_tail_after.jsonl", [])
        _write_json(out / "detected_claude_approval.json", {})
        _write_json(out / "pending_approval_card.json", {})
        (out / "real_repo_status_before.txt").write_text("\n", encoding="utf-8")
        (out / "real_repo_status_after.txt").write_text("\n", encoding="utf-8")
        _write_json(out / "safety_check.json", {
            "real_repo_unchanged": True,
            "execution_observed": False,
        })
        _write_json(out / "privacy_check.json", {
            "chat_text_stored": False,
            "unredacted_secret_like_values": False,
        })
        (out / "changed_files.txt").write_text("", encoding="utf-8")
        _write_json(out / "errors.json", errors)
        _write_json(out / "warnings.json", warnings)
        (out / "RESULT.txt").write_text("RESULT=FAIL\n", encoding="utf-8")
        return {"result": "FAIL", "errors": errors, "warnings": warnings, "proof_dir": str(out)}

    approvals_payload, approvals_err = _safe_http_get_json(f"{broker_url.rstrip('/')}/approvals")
    audit_payload, audit_err = _safe_http_get_json(f"{broker_url.rstrip('/')}/audit/recent")
    dashboard_before, dashboard_err = _safe_http_get_json(f"{dashboard_url.rstrip('/')}/api/state")
    approvals_before = approvals_payload.get("approvals", [])
    audit_before = audit_payload.get("events", [])
    if approvals_err:
        errors.append(f"approvals_unreachable:{approvals_err}")
    if audit_err:
        errors.append(f"audit_recent_unreachable:{audit_err}")
    if dashboard_err:
        errors.append(f"dashboard_state_unreachable:{dashboard_err}")

    if errors:
        _write_json(out / "meta.json", {
            "timestamp": _now_utc(),
            "mode": "watch",
            "repo_root": repo_root,
            "broker_url": broker_url,
            "dashboard_url": dashboard_url,
            "gated_tool": gated_tool,
            "timeout_seconds": timeout_seconds,
        })
        (out / "manual_operator_prompt.md").write_text(
            "# Manual Claude Desktop Prompt\n\n"
            "Use the SlimyOS MCP tools to request a git_commit with a harmless test message, "
            "but do not execute anything. I only want to verify that SlimyOS returns "
            "approval_required and creates a Mission Control approval card.\n",
            encoding="utf-8",
        )
        (out / "claude_config_path.txt").write_text(check.get("config_path", "") + "\n", encoding="utf-8")
        _write_json(out / "slimyos_mcp_entry.json", check.get("slimyos_entry", {}))
        _write_json(out / "broker_health.json", check.get("broker_health", {}))
        _write_json(out / "dashboard_state_before.json", dashboard_before or check.get("dashboard_state", {}))
        _write_json(out / "dashboard_state_after.json", dashboard_before or check.get("dashboard_state", {}))
        _write_json(out / "approvals_before.json", {"approvals": approvals_before, "count": len(approvals_before)})
        _write_json(out / "approvals_after.json", {"approvals": approvals_before, "count": len(approvals_before)})
        _write_jsonl(out / "audit_tail_before.jsonl", audit_before[-100:])
        _write_jsonl(out / "audit_tail_after.jsonl", audit_before[-100:])
        _write_json(out / "detected_claude_approval.json", {})
        _write_json(out / "pending_approval_card.json", {})
        (out / "real_repo_status_before.txt").write_text("\n", encoding="utf-8")
        (out / "real_repo_status_after.txt").write_text("\n", encoding="utf-8")
        _write_json(out / "safety_check.json", {
            "real_repo_unchanged": True,
            "execution_observed": False,
        })
        _write_json(out / "privacy_check.json", {
            "chat_text_stored": False,
            "unredacted_secret_like_values": False,
        })
        (out / "changed_files.txt").write_text("", encoding="utf-8")
        _write_json(out / "errors.json", errors)
        _write_json(out / "warnings.json", warnings)
        (out / "RESULT.txt").write_text("RESULT=FAIL\n", encoding="utf-8")
        return {"result": "FAIL", "errors": errors, "warnings": warnings, "proof_dir": str(out)}

    before_ids = {str(a.get("approval_id", "")) for a in approvals_before if a.get("approval_id")}
    before_event_ids = {str(e.get("event_id", "")) for e in audit_before if e.get("event_id")}
    repo_before = snapshot_repo_state(repo_root)

    detected_approval: dict[str, Any] = {}
    detected_event: dict[str, Any] = {}
    pending_card: dict[str, Any] = {}
    saw_candidate = False

    deadline = time.time() + max(1, int(timeout_seconds))
    dashboard_after: dict[str, Any] = dashboard_before
    approvals_after: list[dict[str, Any]] = approvals_before
    audit_after: list[dict[str, Any]] = audit_before

    while time.time() < deadline:
        try:
            approvals_after = _http_get_json(f"{broker_url.rstrip('/')}/approvals?limit=200").get("approvals", [])
            audit_after = _http_get_json(f"{broker_url.rstrip('/')}/audit/recent").get("events", [])
            dashboard_after = _http_get_json(f"{dashboard_url.rstrip('/')}/api/state")
        except (urlerror.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"watch_fetch_error:{exc}")
            break

        new_approvals = [a for a in approvals_after if str(a.get("approval_id", "")) not in before_ids]
        new_events = [e for e in audit_after if str(e.get("event_id", "")) not in before_event_ids]

        event = find_matching_event(new_events, gated_tool=gated_tool)
        event_approval_id = extract_approval_id_from_event(event)
        approval = find_matching_approval(new_approvals, gated_tool=gated_tool, approval_id=event_approval_id) if event_approval_id else None
        if not approval:
            approval = find_matching_approval(new_approvals, gated_tool=gated_tool)

        if event and not approval:
            saw_candidate = True
            detected_event = event
            time.sleep(2)
            continue

        if approval or event:
            saw_candidate = True
            detected_approval = approval or {}
            detected_event = event or {}
            eval_result = evaluate_approval_observation(
                approval=approval,
                event=event,
                dashboard_state=dashboard_after,
                repo_unchanged_ok=True,
                gated_tool=gated_tool,
            )
            if eval_result["result"] == "PASS":
                pending_card = eval_result.get("pending_approval_card", {})
                break
            if eval_result["result"] == "FAIL":
                errors.extend(eval_result.get("errors", []))
                pending_card = eval_result.get("pending_approval_card", {})
                break

        time.sleep(2)

    repo_after = snapshot_repo_state(repo_root)
    unchanged = repo_unchanged(repo_before, repo_after)
    if not unchanged:
        errors.append("real_repo_changed")

    _write_json(out / "meta.json", {
        "timestamp": _now_utc(),
        "mode": "watch",
        "repo_root": repo_root,
        "broker_url": broker_url,
        "dashboard_url": dashboard_url,
        "gated_tool": gated_tool,
        "timeout_seconds": timeout_seconds,
    })
    (out / "claude_config_path.txt").write_text(check.get("config_path", "") + "\n", encoding="utf-8")
    (out / "manual_operator_prompt.md").write_text(
        "# Manual Claude Desktop Prompt\n\n"
        "Use the SlimyOS MCP tools to request a git_commit with a harmless test message, "
        "but do not execute anything. I only want to verify that SlimyOS returns "
        "approval_required and creates a Mission Control approval card.\n",
        encoding="utf-8",
    )
    _write_json(out / "slimyos_mcp_entry.json", check.get("slimyos_entry", {}))
    _write_json(out / "broker_health.json", check.get("broker_health", {}))
    _write_json(out / "dashboard_state_before.json", dashboard_before)
    _write_json(out / "dashboard_state_after.json", dashboard_after)
    _write_json(out / "approvals_before.json", {"approvals": approvals_before, "count": len(approvals_before)})
    _write_json(out / "approvals_after.json", {"approvals": approvals_after, "count": len(approvals_after)})
    _write_jsonl(out / "audit_tail_before.jsonl", audit_before[-100:])
    _write_jsonl(out / "audit_tail_after.jsonl", audit_after[-100:])
    _write_json(out / "detected_claude_approval.json", {
        "approval": detected_approval,
        "event": detected_event,
    })
    _write_json(out / "pending_approval_card.json", pending_card)
    (out / "real_repo_status_before.txt").write_text(repo_before.get("status_porcelain", "") + "\n", encoding="utf-8")
    (out / "real_repo_status_after.txt").write_text(repo_after.get("status_porcelain", "") + "\n", encoding="utf-8")
    _write_json(out / "safety_check.json", {
        "real_repo_unchanged": unchanged,
        "execution_observed": str((detected_approval or {}).get("execution_status", "")) == "executed",
    })
    _write_json(out / "privacy_check.json", {
        "chat_text_stored": contains_chat_text((detected_approval or {}).get("requested_args_redacted", {}))
        or contains_chat_text((detected_event or {}).get("tool_args", {})),
        "unredacted_secret_like_values": contains_unredacted_secret_like_values((detected_approval or {}).get("requested_args_redacted", {}))
        or contains_unredacted_secret_like_values((detected_event or {}).get("tool_args", {})),
    })

    ok_diff, diff_out = _run_git(repo_root, "diff", "--name-only")
    changed = diff_out if ok_diff else ""
    (out / "changed_files.txt").write_text(changed + ("\n" if changed else ""), encoding="utf-8")

    if errors:
        result = "FAIL"
    elif detected_approval and pending_card:
        result = "PASS"
    elif saw_candidate:
        errors.append("candidate_seen_but_not_fully_verified")
        result = "FAIL"
    else:
        result = "PENDING_MANUAL"

    _write_json(out / "warnings.json", warnings)
    _write_json(out / "errors.json", errors)
    (out / "RESULT.txt").write_text(f"RESULT={result}\n", encoding="utf-8")

    return {
        "result": result,
        "proof_dir": str(out),
        "errors": errors,
        "warnings": warnings,
        "approval_id": str((detected_approval or {}).get("approval_id", "") or extract_approval_id_from_event(detected_event)),
        "pending_detected": bool(detected_approval and pending_card),
        "detected_client_identity": (detected_approval or {}).get("client_identity", {}) or (detected_event or {}).get("client_identity", {}),
        "detected_tool_name": normalize_tool_name(str((detected_approval or {}).get("tool_name", "") or (detected_event or {}).get("tool_name", ""))),
        "detected_original_tool_name": str((detected_approval or {}).get("tool_name", "") or (detected_event or {}).get("tool_name", "")),
        "detected_policy_rule": str((detected_approval or {}).get("policy_rule", "") or (detected_event or {}).get("policy_rule", "")),
        "detected_approval_status": str((detected_approval or {}).get("status", "")),
        "failure_reasons": errors,
    }
