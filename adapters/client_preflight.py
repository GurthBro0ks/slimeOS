"""Client adapter preflight checks for SlimyOS control plane."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest


@dataclass
class PreflightConfig:
    repo_path: str
    broker_url: str = "http://localhost:3003"
    dashboard_url: str = "http://localhost:3002"
    hermes_models_url: str = "http://localhost:8642/v1/models"


def _http_get_json(url: str, timeout: float = 3.0) -> dict:
    with urlrequest.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read())


def _http_post_json(url: str, payload: dict, timeout: float = 3.0) -> dict:
    data = json.dumps(payload).encode()
    request = urlrequest.Request(
        url,
        method="POST",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urlrequest.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _tool_call(
    broker_url: str,
    tool_name: str,
    args: dict,
    agent_id: str = "client-preflight",
    agent_runtime: str = "preflight",
    task_id: str = "client-preflight-task",
) -> dict:
    return _http_post_json(
        f"{broker_url.rstrip('/')}/tools/{tool_name}",
        {
            "args": args,
            "agent_id": agent_id,
            "agent_runtime": agent_runtime,
            "task_id": task_id,
        },
    )


def run_client_preflight(config: PreflightConfig) -> dict:
    warnings: list[str] = []
    errors: list[str] = []

    result: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
        "repo_path": str(Path(config.repo_path).resolve()),
        "broker_url": config.broker_url,
        "dashboard_url": config.dashboard_url,
        "broker_health": {},
        "tool_count": 0,
        "safe_call_result": {},
        "blocked_call_results": {},
        "approval_gate_result": {},
        "hermes": {},
        "clients": {},
        "warnings": warnings,
        "errors": errors,
        "final_result": "FAIL",
    }

    # Core control plane checks
    try:
        health = _http_get_json(f"{config.broker_url.rstrip('/')}/health")
        result["broker_health"] = health
        if health.get("status") != "ok":
            errors.append("broker_health_not_ok")
        result["tool_count"] = int(health.get("tools", 0))
        if result["tool_count"] < 40:
            errors.append("tool_count_below_threshold")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"broker_unreachable:{exc}")

    try:
        runtime = _http_get_json(f"{config.dashboard_url.rstrip('/')}/api/runtime")
        result["dashboard_runtime"] = runtime
    except Exception as exc:  # noqa: BLE001
        errors.append(f"dashboard_unreachable:{exc}")

    repo_readme = os.path.join(config.repo_path, "README.md")
    try:
        safe_call = _tool_call(config.broker_url, "read_file", {"path": repo_readme})
        result["safe_call_result"] = safe_call
        if not safe_call.get("success"):
            errors.append("safe_tool_call_failed")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"safe_tool_call_exception:{exc}")

    # Blocked and gated checks
    try:
        raw_shell = _tool_call(config.broker_url, "raw_shell", {"command": "rm -rf /"})
        result["blocked_call_results"]["raw_shell"] = raw_shell
        if raw_shell.get("disposition") != "blocked":
            errors.append("raw_shell_not_blocked")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"raw_shell_check_exception:{exc}")

    try:
        restart = _tool_call(config.broker_url, "restart_service", {"service_name": "sshd"})
        result["blocked_call_results"]["restart_service_sshd"] = restart
        if restart.get("disposition") not in {"blocked", "approval_required"}:
            errors.append("restart_service_sshd_not_gated")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"restart_service_check_exception:{exc}")

    try:
        git_commit = _tool_call(
            config.broker_url,
            "git_commit",
            {"repo_path": config.repo_path, "message": "preflight-check"},
        )
        result["approval_gate_result"] = git_commit
        if git_commit.get("disposition") not in {"approval_required", "blocked", "snapshot_first"}:
            errors.append("git_commit_not_gated")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"git_commit_check_exception:{exc}")

    # Hermes checks (warn-only)
    hermes_installed = bool(shutil.which("hermes") or Path(os.path.expanduser("~/.local/bin/hermes")).exists())
    hermes_state = {
        "installed": hermes_installed,
        "binary": shutil.which("hermes") or os.path.expanduser("~/.local/bin/hermes"),
        "proxy_url": config.hermes_models_url,
        "proxy_reachable": False,
        "auth_state": "auth_required_or_proxy_down",
        "status": "warn",
        "error": "",
    }
    if not hermes_installed:
        hermes_state["status"] = "warn"
        hermes_state["auth_state"] = "not_installed"
        warnings.append("hermes_not_installed")
    else:
        try:
            models_payload = _http_get_json(config.hermes_models_url)
            hermes_state["proxy_reachable"] = True
            hermes_state["status"] = "pass"
            hermes_state["auth_state"] = "connected"
            hermes_state["models"] = models_payload.get("data", models_payload.get("models", []))
        except Exception as exc:  # noqa: BLE001
            hermes_state["error"] = str(exc)
            warnings.append("hermes_auth_required_or_proxy_down")
    result["hermes"] = hermes_state

    # Client command presence checks (warn-only)
    clients: dict[str, Any] = {}
    for client in ("claude", "codex", "opencode"):
        path = shutil.which(client)
        present = path is not None
        clients[client] = {
            "installed": present,
            "binary": path or "",
            "status": "pass" if present else "warn",
        }
        if not present:
            warnings.append(f"client_missing:{client}")
    result["clients"] = clients

    result["final_result"] = "PASS" if not errors else "FAIL"
    return result


def write_preflight_artifacts(preflight_result: dict, proof_dir: str) -> None:
    out_dir = Path(proof_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "client_preflight.json").write_text(json.dumps(preflight_result, indent=2))
    (out_dir / "RESULT.txt").write_text(f"RESULT={preflight_result.get('final_result', 'FAIL')}\n")

    meta = {
        "timestamp": preflight_result.get("timestamp"),
        "proof_dir": str(out_dir),
        "repo_path": preflight_result.get("repo_path"),
        "broker_url": preflight_result.get("broker_url"),
        "dashboard_url": preflight_result.get("dashboard_url"),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
