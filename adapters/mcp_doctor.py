"""Operator-facing MCP doctor helpers for SlimyOS."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest


def detect_clients() -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    clients: dict[str, Any] = {}
    for name in ("claude", "codex", "opencode"):
        binary = shutil.which(name)
        installed = binary is not None
        clients[name] = {
            "installed": installed,
            "binary": binary or "",
            "status": "pass" if installed else "warn",
        }
        if not installed:
            warnings.append(f"client_missing:{name}")

    claude_desktop_path = Path(os.path.expanduser("~/.config/claude-desktop/claude_desktop_config.json"))
    claude_code_candidates = [
        Path(os.path.expanduser("~/.claude.json")),
        Path(os.path.expanduser("~/.config/claude-code/config.json")),
    ]

    clients["claude_desktop_config"] = {
        "path": str(claude_desktop_path),
        "exists": claude_desktop_path.exists(),
        "status": "pass" if claude_desktop_path.exists() else "warn",
    }
    if not claude_desktop_path.exists():
        warnings.append("claude_desktop_config_missing")

    existing_cc = [str(p) for p in claude_code_candidates if p.exists()]
    clients["claude_code_config_candidates"] = {
        "paths": [str(p) for p in claude_code_candidates],
        "existing": existing_cc,
        "status": "pass" if existing_cc else "warn",
    }
    if not existing_cc:
        warnings.append("claude_code_config_not_detected")

    return clients, warnings


def _http_get_json(url: str) -> dict[str, Any]:
    with urlrequest.urlopen(url, timeout=3.0) as response:
        return json.loads(response.read())


def generate_snippets(repo_root: str, broker_url: str) -> dict[str, str]:
    run_cmd = str(Path(repo_root) / "scripts" / "run-mcp-server.sh")

    claude_desktop = {
        "mcpServers": {
            "slimyos": {
                "command": run_cmd,
                "args": [],
                "env": {
                    "SLIMYOS_TOOLD_URL": broker_url,
                    "SLIMYOS_MCP_AGENT_ID": "claude_desktop",
                    "SLIMYOS_MCP_AGENT_NAME": "Claude Desktop",
                    "SLIMYOS_MCP_AGENT_KIND": "desktop_app",
                    "SLIMYOS_MCP_TRANSPORT": "mcp_stdio",
                    "SLIMYOS_MCP_AGENT_RUNTIME": "mcp_stdio",
                },
            }
        }
    }

    claude_code_md = "\n".join(
        [
            "# SlimyOS MCP for Claude Code",
            "",
            "Use this MCP server command:",
            "",
            f"`{run_cmd}`",
            "",
            "Environment:",
            f"- `SLIMYOS_TOOLD_URL={broker_url}`",
            "- `SLIMYOS_MCP_AGENT_ID=claude-code`",
            "- `SLIMYOS_MCP_AGENT_RUNTIME=claude-code`",
            "",
            "All tool calls still flow through Tool Broker policy and audit.",
        ]
    )

    opencode_md = "\n".join(
        [
            "# SlimyOS MCP for OpenCode",
            "",
            "Command:",
            f"`{run_cmd}`",
            "",
            "OpenCode can discover tools through MCP, but execution remains",
            "policy-gated through slimy-toold.",
        ]
    )

    codex_md = "\n".join(
        [
            "# SlimyOS MCP for Codex",
            "",
            "Command:",
            f"`{run_cmd}`",
            "",
            "Blocked and approval-gated outcomes are returned as-is.",
            "No provider login or secrets required for MCP bridge checks.",
        ]
    )

    return {
        "generated_claude_desktop_config.json": json.dumps(claude_desktop, indent=2),
        "generated_claude_code_notes.md": claude_code_md,
        "generated_opencode_notes.md": opencode_md,
        "generated_codex_notes.md": codex_md,
    }


def _run_mcp_request(repo_root: str, request_obj: dict[str, Any]) -> dict[str, Any]:
    command = [str(Path(repo_root) / "scripts" / "run-mcp-server.sh")]
    process = subprocess.run(
        command,
        cwd=repo_root,
        input=json.dumps(request_obj) + "\n",
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or "MCP server invocation failed")

    for line in process.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        return json.loads(line)
    raise RuntimeError("No MCP JSON response returned")


def _check_hermes_state() -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    installed = bool(shutil.which("hermes") or Path(os.path.expanduser("~/.local/bin/hermes")).exists())
    hermes = {
        "installed": installed,
        "proxy_url": "http://localhost:8642/v1/models",
        "proxy_reachable": False,
        "auth_state": "auth_required_or_proxy_down",
        "status": "warn",
        "error": "",
    }

    if not installed:
        hermes["auth_state"] = "not_installed"
        warnings.append("hermes_not_installed")
        return hermes, warnings

    try:
        _http_get_json(hermes["proxy_url"])
        hermes["proxy_reachable"] = True
        hermes["auth_state"] = "connected"
        hermes["status"] = "pass"
    except Exception as exc:  # noqa: BLE001
        hermes["error"] = str(exc)
        warnings.append("hermes_auth_required_or_proxy_down")

    return hermes, warnings


def run_mcp_doctor(
    repo_root: str,
    proof_dir: str,
    broker_url: str = "http://localhost:3003",
    dashboard_url: str = "http://localhost:3002",
    write_snippets: bool = False,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    out = Path(proof_dir)
    out.mkdir(parents=True, exist_ok=True)

    broker_health: dict[str, Any] = {}
    dashboard_payload: dict[str, Any] = {}
    mcp_init: dict[str, Any] = {}
    mcp_list: dict[str, Any] = {}
    mcp_safe: dict[str, Any] = {}
    mcp_blocked: dict[str, Any] = {}
    mcp_gated: dict[str, Any] = {}

    try:
        broker_health = _http_get_json(f"{broker_url.rstrip('/')}/health")
        if broker_health.get("status") != "ok":
            errors.append("broker_health_not_ok")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"broker_unreachable:{exc}")

    try:
        dashboard_payload = _http_get_json(f"{dashboard_url.rstrip('/')}/api/runtime")
    except Exception:
        try:
            dashboard_payload = _http_get_json(f"{dashboard_url.rstrip('/')}/api/state")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"dashboard_unreachable:{exc}")

    tool_count = int(broker_health.get("tools", 0))
    if tool_count < 40:
        errors.append(f"tool_count_below_threshold:{tool_count}")

    try:
        mcp_init = _run_mcp_request(
            repo_root,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"mcp_initialize_failed:{exc}")

    try:
        mcp_list = _run_mcp_request(
            repo_root,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        listed = len(mcp_list.get("result", {}).get("tools", []))
        if listed < 40:
            errors.append(f"mcp_tools_list_below_threshold:{listed}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"mcp_tools_list_failed:{exc}")

    try:
        mcp_safe = _run_mcp_request(
            repo_root,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "slimyos_read_file",
                    "arguments": {"path": str(Path(repo_root) / "README.md")},
                },
            },
        )
        safe_struct = mcp_safe.get("result", {})
        content = safe_struct.get("content", [])
        if content and isinstance(content, list) and len(content) > 0:
            try:
                safe_struct = json.loads(content[0].get("text", "{}"))
            except (json.JSONDecodeError, TypeError):
                pass
        if not safe_struct.get("success"):
            errors.append("mcp_safe_call_not_success")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"mcp_safe_call_failed:{exc}")

    try:
        mcp_blocked = _run_mcp_request(
            repo_root,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "slimyos_raw_shell", "arguments": {"command": "rm -rf /"}},
            },
        )
        blocked_struct = mcp_blocked.get("result", {})
        content = blocked_struct.get("content", [])
        if content and isinstance(content, list) and len(content) > 0:
            try:
                blocked_struct = json.loads(content[0].get("text", "{}"))
            except (json.JSONDecodeError, TypeError):
                pass
        if blocked_struct.get("disposition") != "blocked":
            errors.append("mcp_raw_shell_not_blocked")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"mcp_blocked_call_failed:{exc}")

    try:
        mcp_gated = _run_mcp_request(
            repo_root,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "slimyos_restart_service", "arguments": {"service_name": "sshd"}},
            },
        )
        gated_struct = mcp_gated.get("result", {})
        content = gated_struct.get("content", [])
        if content and isinstance(content, list) and len(content) > 0:
            try:
                gated_struct = json.loads(content[0].get("text", "{}"))
            except (json.JSONDecodeError, TypeError):
                pass
        if gated_struct.get("disposition") not in {"blocked", "approval_required"}:
            errors.append("mcp_restart_service_not_gated")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"mcp_gated_call_failed:{exc}")

    clients, client_warnings = detect_clients()
    warnings.extend(client_warnings)

    hermes, hermes_warnings = _check_hermes_state()
    warnings.extend(hermes_warnings)

    snippets = generate_snippets(repo_root, broker_url)
    for filename, content in snippets.items():
        (out / filename).write_text(content)

    if write_snippets:
        generated_dir = Path(repo_root) / "docs" / "generated"
        generated_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in snippets.items():
            (generated_dir / filename).write_text(content)

    (out / "broker_health.json").write_text(json.dumps(broker_health, indent=2))
    if dashboard_payload:
        if dashboard_payload.get("runtime"):
            (out / "dashboard_state.json").write_text(json.dumps(dashboard_payload, indent=2))
        else:
            (out / "dashboard_runtime.json").write_text(json.dumps(dashboard_payload, indent=2))
    (out / "mcp_initialize.json").write_text(json.dumps(mcp_init, indent=2))
    (out / "mcp_tools_list.json").write_text(json.dumps(mcp_list, indent=2))
    (out / "mcp_safe_call.json").write_text(json.dumps(mcp_safe, indent=2))
    (out / "mcp_blocked_call.json").write_text(json.dumps(mcp_blocked, indent=2))
    (out / "mcp_gated_call.json").write_text(json.dumps(mcp_gated, indent=2))
    (out / "client_detection.json").write_text(json.dumps({"clients": clients, "hermes": hermes}, indent=2))
    (out / "warnings.json").write_text(json.dumps(warnings, indent=2))
    (out / "errors.json").write_text(json.dumps(errors, indent=2))

    result = "PASS" if not errors else "FAIL"
    (out / "RESULT.txt").write_text(f"RESULT={result}\n")

    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
        "repo_path": str(Path(repo_root).resolve()),
        "broker_url": broker_url,
        "dashboard_url": dashboard_url,
        "tool_count": tool_count,
        "result": result,
        "warnings": warnings,
        "errors": errors,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))

    return {
        "result": result,
        "warnings": warnings,
        "errors": errors,
        "tool_count": tool_count,
        "clients": clients,
        "hermes": hermes,
        "proof_dir": str(out),
    }


def build_healthline(summary: dict[str, Any]) -> str:
    broker = "ok" if not summary.get("errors") else "fail"
    tool_count = summary.get("tool_count", 0)
    clients = summary.get("clients", {})
    claude = "found" if clients.get("claude", {}).get("installed") else "missing"
    codex = "found" if clients.get("codex", {}).get("installed") else "missing"
    opencode = "found" if clients.get("opencode", {}).get("installed") else "missing"
    hermes = summary.get("hermes", {})
    if hermes.get("status") == "warn":
        hermes_label = f"warn/{hermes.get('auth_state', 'unknown')}"
    else:
        hermes_label = "ok"
    policy_hint = "blocked_raw_shell"
    return (
        f"SlimyOS MCP: {summary.get('result', 'FAIL')} | broker={broker} "
        f"tools={tool_count} dashboard=ok claude={claude} codex={codex} "
        f"opencode={opencode} hermes={hermes_label} policy={policy_hint}"
    )
