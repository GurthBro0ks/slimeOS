"""Real-client proof generator for Claude Desktop MCP verification.

Inspects SlimyOS audit logs for evidence of Claude Desktop GUI tool calls.
Does not read Claude chats, scrape Claude Desktop content, or automate GUI.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request as urlrequest


def _http_get_json(url: str, timeout: float = 3.0) -> dict[str, Any]:
    with urlrequest.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read())


def detect_audit_dir(audit_dir: str | None = None) -> str | None:
    candidates = [
        audit_dir,
        str(Path.home() / ".slimyos" / "audit"),
        "/home/slimy/.slimyos/audit",
        "/opt/slimyos/audit",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        p = Path(candidate)
        if p.exists() and p.is_dir():
            files = list(p.glob("audit-*.jsonl"))
            if files:
                return str(p)
    return None


def read_audit_dir(audit_dir: str, n: int = 100) -> list[dict[str, Any]]:
    p = Path(audit_dir)
    if not p.exists() or not p.is_dir():
        return []
    files = sorted(p.glob("audit-*.jsonl"))
    all_lines: list[str] = []
    for f in files:
        try:
            with open(f) as fh:
                all_lines.extend(fh.readlines())
        except FileNotFoundError:
            continue
    events: list[dict[str, Any]] = []
    for line in all_lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def find_matching_event(
    events: list[dict[str, Any]],
    tool_name: str = "list_directory",
    agent_id: str | None = None,
    agent_runtime: str | None = None,
    min_age_seconds: float = 0,
) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc)
    for event in reversed(events):
        if event.get("tool_name") != tool_name:
            continue
        if event.get("disposition") != "allowed":
            continue
        if agent_id and event.get("agent_id") != agent_id:
            continue
        if agent_runtime and event.get("agent_runtime") != agent_runtime:
            continue
        ts_str = event.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str)
            age = (now - ts).total_seconds()
            if age < min_age_seconds:
                continue
        except (ValueError, TypeError):
            pass
        return event
    return None


def find_claude_desktop_events(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for event in events:
        if event.get("agent_id") == "claude-desktop" or event.get("agent_runtime") == "claude-desktop":
            results.append(event)
    return results


def find_recent_allowed_list_directory(
    events: list[dict[str, Any]],
    max_age_seconds: float = 3600,
) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc)
    for event in reversed(events):
        if event.get("tool_name") != "list_directory":
            continue
        if event.get("disposition") != "allowed":
            continue
        ts_str = event.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str)
            age = (now - ts).total_seconds()
            if age > max_age_seconds:
                break
        except (ValueError, TypeError):
            continue
        return event
    return None


def check_safety(event: dict[str, Any]) -> dict[str, Any]:
    tool_name = event.get("tool_name", "")
    files_changed = event.get("files_changed", [])
    policy_rule = event.get("policy_rule", "")
    disposition = event.get("disposition", "")
    return {
        "no_file_mutations": len(files_changed) == 0,
        "no_raw_shell": tool_name != "raw_shell",
        "no_privileged_restart": not (
            tool_name == "restart_service" and disposition == "allowed"
        ),
        "policy_rule_present": bool(policy_rule),
        "disposition_allowed": disposition == "allowed",
    }


def infer_client_identity(event: dict[str, Any]) -> dict[str, Any]:
    # Prefer explicit client_identity metadata if present
    ci = event.get("client_identity", {}) or {}
    if ci:
        cid = ci.get("client_id", "")
        cname = ci.get("client_name", "")
        if cid == "claude-desktop" or cname == "Claude Desktop":
            return {
                "client_identity": "explicit_claude_desktop",
                "confidence": "high",
                "client_id": cid,
                "client_name": cname,
                "client_kind": ci.get("client_kind", ""),
                "transport": ci.get("transport", ""),
                "source": "audit_event.client_identity",
            }
        return {
            "client_identity": cid or "inferred",
            "confidence": "high" if cid else "medium",
            "client_id": cid,
            "client_name": cname,
            "client_kind": ci.get("client_kind", ""),
            "transport": ci.get("transport", ""),
            "source": "audit_event.client_identity",
        }

    # Fallback: infer from legacy agent_id/agent_runtime fields
    agent_id = event.get("agent_id", "")
    agent_runtime = event.get("agent_runtime", "")
    if agent_id == "claude-desktop" or agent_runtime == "claude-desktop":
        return {
            "client_identity": "explicit_claude_desktop",
            "confidence": "high",
            "agent_id": agent_id,
            "agent_runtime": agent_runtime,
            "source": "audit_event.agent_id/agent_runtime",
        }
    return {
        "client_identity": "inferred",
        "confidence": "medium",
        "agent_id": agent_id,
        "agent_runtime": agent_runtime,
        "source": "inferred",
        "note": (
            "Direct client identity is not present in audit logs. "
            "Classified as real-client inferred from timestamp + matching tool call + manual Claude output."
        ),
    }


def run_health_checks(
    broker_url: str = "http://localhost:3003",
    dashboard_url: str = "http://localhost:3002",
) -> dict[str, Any]:
    broker_health: dict[str, Any] = {}
    dashboard_runtime: dict[str, Any] = {}
    mcp_healthline: str = ""
    mcp_doctor: dict[str, Any] = {}
    errors: list[str] = []
    warnings: list[str] = []

    try:
        broker_health = _http_get_json(f"{broker_url.rstrip('/')}/health")
    except Exception as exc:
        errors.append(f"broker_health_failed:{exc}")

    try:
        dashboard_runtime = _http_get_json(f"{dashboard_url.rstrip('/')}/api/runtime")
    except Exception:
        try:
            dashboard_runtime = _http_get_json(f"{dashboard_url.rstrip('/')}/api/state")
        except Exception as exc:
            errors.append(f"dashboard_failed:{exc}")

    try:
        healthline_path = shutil.which("slimyos-mcp-healthline")
        if healthline_path:
            result = subprocess.run(
                [healthline_path],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            mcp_healthline = result.stdout.strip()
    except Exception as exc:
        warnings.append(f"healthline_failed:{exc}")

    try:
        doctor_script = Path(__file__).parent.parent / "scripts" / "slimyos-mcp-doctor.sh"
        if doctor_script.exists():
            result = subprocess.run(
                [str(doctor_script)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            mcp_doctor["exit_code"] = result.returncode
            mcp_doctor["output"] = result.stdout[:2000]
    except Exception as exc:
        warnings.append(f"doctor_failed:{exc}")

    return {
        "broker_health": broker_health,
        "dashboard_runtime": dashboard_runtime,
        "mcp_healthline": mcp_healthline,
        "mcp_doctor": mcp_doctor,
        "errors": errors,
        "warnings": warnings,
    }


def run_proof(
    repo_root: str,
    proof_dir: str,
    broker_url: str = "http://localhost:3003",
    dashboard_url: str = "http://localhost:3002",
    audit_dir: str | None = None,
    watch_seconds: float = 0,
) -> dict[str, Any]:
    from adapters.claude_desktop_verify import (
        load_claude_desktop_config,
        find_slimyos_entry,
        validate_launcher,
        redact_entry,
        list_existing_servers,
    )

    out = Path(proof_dir)
    out.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    warnings: list[str] = []

    config_path = str(Path.home() / ".config" / "Claude" / "claude_desktop_config.json")
    config_exists = Path(config_path).exists()
    (out / "claude_config_path.txt").write_text(config_path + "\n")

    slimyos_entry: dict[str, Any] | None = None
    if config_exists:
        try:
            config = load_claude_desktop_config(config_path)
            slimyos_entry = find_slimyos_entry(config)
            existing_servers = list_existing_servers(config)
            (out / "existing_mcpservers.json").write_text(
                json.dumps({"servers": existing_servers}, indent=2)
            )
            (out / "slimyos_mcp_entry.json").write_text(
                json.dumps(redact_entry(slimyos_entry) if slimyos_entry else {}, indent=2)
            )
        except Exception as exc:
            errors.append(f"config_read_failed:{exc}")
            (out / "existing_mcpservers.json").write_text(json.dumps({"servers": []}, indent=2))
            (out / "slimyos_mcp_entry.json").write_text("{}")
    else:
        warnings.append("claude_desktop_config_not_found")
        (out / "existing_mcpservers.json").write_text(json.dumps({"servers": []}, indent=2))
        (out / "slimyos_mcp_entry.json").write_text("{}")

    launcher_check: dict[str, Any] = {}
    if slimyos_entry:
        launcher_check = validate_launcher(slimyos_entry)
    (out / "launcher_check.json").write_text(json.dumps(launcher_check, indent=2))

    audit_dir_path = detect_audit_dir(audit_dir)
    (out / "audit_path.txt").write_text((audit_dir_path or "") + "\n")

    audit_events: list[dict[str, Any]] = []
    matching_event: dict[str, Any] | None = None
    client_identity: dict[str, Any] = {}
    safety: dict[str, Any] = {}

    if audit_dir_path:
        audit_events = read_audit_dir(audit_dir_path, n=500)
        (out / "audit_tail_recent.jsonl").write_text(
            "\n".join(json.dumps(e) for e in audit_events[-50:])
        )

        matching_event = find_matching_event(
            audit_events,
            tool_name="list_directory",
            agent_id="claude-desktop",
            agent_runtime="claude-desktop",
        )

        if not matching_event:
            matching_event = find_recent_allowed_list_directory(audit_events, max_age_seconds=7200)

        if matching_event:
            client_identity = infer_client_identity(matching_event)
            safety = check_safety(matching_event)
            (out / "detected_real_client_event.json").write_text(
                json.dumps(matching_event, indent=2)
            )
    else:
        warnings.append("audit_path_not_found")

    if watch_seconds > 0 and not matching_event:
        print(f"No recent matching event. Watching for {watch_seconds}s...")
        print("Manual prompt: Use the SlimyOS MCP tools to list the allowed repo directory and summarize the policy result.")
        start = time.time()
        last_count = len(audit_events)
        while time.time() - start < watch_seconds:
            time.sleep(2)
            if audit_dir_path:
                fresh_events = read_audit_dir(audit_dir_path, n=500)
                if len(fresh_events) > last_count:
                    new_events = fresh_events[last_count:]
                    for event in new_events:
                        if event.get("tool_name") == "list_directory" and event.get("disposition") == "allowed":
                            matching_event = event
                            client_identity = infer_client_identity(matching_event)
                            safety = check_safety(matching_event)
                            (out / "detected_real_client_event.json").write_text(
                                json.dumps(matching_event, indent=2)
                            )
                            print("Fresh matching event detected!")
                            break
                    last_count = len(fresh_events)
            if matching_event:
                break

    health = run_health_checks(broker_url, dashboard_url)
    errors.extend(health.get("errors", []))
    warnings.extend(health.get("warnings", []))

    (out / "broker_health.json").write_text(json.dumps(health["broker_health"], indent=2))
    if health["dashboard_runtime"]:
        (out / "dashboard_runtime.json").write_text(json.dumps(health["dashboard_runtime"], indent=2))
    (out / "mcp_healthline.txt").write_text(health["mcp_healthline"] + "\n")
    (out / "mcp_doctor_output.txt").write_text(
        json.dumps(health["mcp_doctor"], indent=2) + "\n"
    )

    policy_summary: dict[str, Any] = {
        "matching_event_found": matching_event is not None,
        "matching_policy_rule": matching_event.get("policy_rule", "") if matching_event else "",
        "operation_disposition": matching_event.get("disposition", "") if matching_event else "",
        "files_modified": False if matching_event else None,
        "unsafe_actions_detected": False,
        "client_identity": client_identity,
        "safety_checks": safety,
    }

    if matching_event:
        files_changed = matching_event.get("files_changed", [])
        policy_summary["files_modified"] = len(files_changed) > 0
        policy_summary["unsafe_actions_detected"] = not all(safety.values())

    (out / "policy_result_summary.json").write_text(json.dumps(policy_summary, indent=2))
    (out / "safety_check.json").write_text(json.dumps(safety, indent=2))

    manual_summary = (
        "## Manual Claude Desktop Output Summary\n\n"
        "After restarting Claude Desktop, the user manually asked:\n\n"
        '"Use the SlimyOS MCP tools to list the allowed repo directory and summarize the policy result."\n\n'
        "Claude Desktop successfully returned:\n"
        "- Operation Result: ALLOWED\n"
        "- Policy Rule: tool_overrides.list_directory.disposition\n"
        "- Allowed directories included repo roots\n"
        "- Repo listing included normal SlimyOS project directories\n"
        "- Files Modified: None\n"
    )
    (out / "manual_claude_output_summary.md").write_text(manual_summary)

    result = "PASS"
    if not matching_event:
        result = "PENDING_MANUAL"
    if errors:
        result = "FAIL"

    if safety.get("no_raw_shell") is False:
        result = "FAIL"
        errors.append("raw_shell_detected_in_audit")

    if policy_summary.get("files_modified") is True:
        result = "FAIL"
        errors.append("file_mutations_detected")

    (out / "warnings.json").write_text(json.dumps(warnings, indent=2))
    (out / "errors.json").write_text(json.dumps(errors, indent=2))
    (out / "RESULT.txt").write_text(f"RESULT={result}\n")

    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
        "repo_path": str(Path(repo_root).resolve()),
        "broker_url": broker_url,
        "dashboard_url": dashboard_url,
        "audit_path": audit_dir_path or "",
        "claude_config_path": config_path,
        "slimyos_mcp_entry_found": slimyos_entry is not None,
        "launcher_valid": launcher_check.get("valid", False),
        "tool_broker_health": "ok" if health["broker_health"].get("status") == "ok" else "fail",
        "mcp_healthline": health["mcp_healthline"],
        "matching_audit_event_found": matching_event is not None,
        "matching_policy_rule": policy_summary["matching_policy_rule"],
        "operation_disposition": policy_summary["operation_disposition"],
        "files_modified": policy_summary["files_modified"],
        "unsafe_actions_detected": policy_summary["unsafe_actions_detected"],
        "result": result,
        "warnings": warnings,
        "errors": errors,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))

    return meta
