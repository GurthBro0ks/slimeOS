"""Live runtime status collection for SlimyOS Mission Control."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib import error as urlerror
from urllib import request as urlrequest

CommandRunner = Callable[[list[str]], tuple[bool, str, str]]
HttpGetter = Callable[[str], dict]


def _default_run_command(command: list[str]) -> tuple[bool, str, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return False, "", str(exc)


def _default_http_get_json(url: str) -> dict:
    with urlrequest.urlopen(url, timeout=2.0) as response:
        return json.loads(response.read())


class RuntimeStatusCollector:
    def __init__(
        self,
        repo_path: str,
        slimyos_home: str | None = None,
        broker_url: str = "http://localhost:3003",
        hermes_models_url: str = "http://localhost:8642/v1/models",
        command_runner: CommandRunner = _default_run_command,
        http_get_json: HttpGetter = _default_http_get_json,
    ):
        self.repo_path = str(Path(repo_path).resolve())
        self.slimyos_home = str(Path(os.path.expanduser(slimyos_home or "~/.slimyos")).resolve())
        self.broker_url = broker_url.rstrip("/")
        self.hermes_models_url = hermes_models_url
        self._run_command = command_runner
        self._http_get_json = http_get_json

    def collect(self) -> dict:
        warnings: list[str] = []
        errors: list[str] = []

        services = {
            "slimyos-toold": self._service_status("slimyos-toold"),
            "slimyos-dashboard": self._service_status("slimyos-dashboard"),
        }

        for name, svc in services.items():
            if svc["status"] == "fail":
                errors.append(f"service_{name}_not_active")

        broker = self._broker_status()
        if broker["status"] == "fail":
            errors.append(broker.get("error") or "broker_unreachable")

        hermes = self._hermes_status()
        if hermes["status"] == "warn":
            warnings.append(hermes.get("auth_state", "auth_required_or_proxy_down"))

        panic = {"panicked": False, "status": "warn"}
        approvals = {"pending_count": 0}
        recent_events: list[dict] = []

        state_payload = broker.get("state")
        if state_payload:
            panic["panicked"] = bool(state_payload.get("panicked", False))
            panic["status"] = "fail" if panic["panicked"] else "pass"
            approvals["pending_count"] = len(state_payload.get("pending_approvals", []))

        audit_recent = broker.get("audit_recent")
        if audit_recent:
            recent_events = audit_recent.get("events", [])[-15:]

        recent_client_activity = self._extract_client_activity(recent_events)
        clients_seen = self._extract_clients_seen(recent_events)
        last_claude_desktop_event = self._find_last_claude_desktop_event(recent_events)

        runtime = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hostname": platform.node(),
            "repo_path": self.repo_path,
            "services": services,
            "broker": broker,
            "hermes": hermes,
            "audit": self._audit_status(audit_recent),
            "proof_packs": self._proof_pack_status(),
            "approvals": approvals,
            "panic": panic,
            "recent_events": recent_events,
            "recent_client_activity": recent_client_activity,
            "clients_seen": clients_seen,
            "last_claude_desktop_event": last_claude_desktop_event,
            "warnings": warnings,
            "errors": errors,
        }
        return runtime

    def _extract_client_activity(self, events: list[dict]) -> list[dict]:
        activity = []
        for event in events:
            if event.get("event_type") not in {
                "tool_executed",
                "tool_allowed",
                "tool_blocked",
                "tool_approval_required",
                "approval_requested",
                "approval_decided",
            }:
                continue
            ci = event.get("client_identity", {}) or {}
            activity.append({
                "timestamp": event.get("timestamp", ""),
                "client_name": ci.get("client_name", event.get("agent_id", "unknown")),
                "client_id": ci.get("client_id", event.get("agent_id", "unknown")),
                "transport": ci.get("transport", event.get("agent_runtime", "unknown")),
                "tool_name": event.get("tool_name", ""),
                "disposition": event.get("disposition", ""),
                "policy_rule": event.get("policy_rule", ""),
                "files_modified": bool(event.get("files_changed", [])),
                "unsafe_action": event.get("tool_name") == "raw_shell" and event.get("disposition") == "allowed",
                "result_summary": (event.get("result", {}) or {}).get("output", "")[:80],
            })
        return activity[-10:]

    def _extract_clients_seen(self, events: list[dict]) -> list[dict]:
        seen: dict[str, dict] = {}
        for event in events:
            ci = event.get("client_identity", {}) or {}
            cid = ci.get("client_id", event.get("agent_id", "unknown"))
            if cid not in seen:
                seen[cid] = {
                    "client_id": cid,
                    "client_name": ci.get("client_name", event.get("agent_id", "unknown")),
                    "transport": ci.get("transport", event.get("agent_runtime", "unknown")),
                    "last_seen": event.get("timestamp", ""),
                    "call_count": 1,
                }
            else:
                seen[cid]["call_count"] += 1
                seen[cid]["last_seen"] = event.get("timestamp", "")
        return list(seen.values())

    def _find_last_claude_desktop_event(self, events: list[dict]) -> dict | None:
        for event in reversed(events):
            ci = event.get("client_identity", {}) or {}
            if ci.get("client_id") == "claude-desktop" or event.get("agent_id") == "claude-desktop":
                return {
                    "timestamp": event.get("timestamp", ""),
                    "tool_name": event.get("tool_name", ""),
                    "disposition": event.get("disposition", ""),
                    "policy_rule": event.get("policy_rule", ""),
                }
        return None

    def _service_status(self, service_name: str) -> dict:
        enabled_ok, enabled_out, enabled_err = self._run_command(["systemctl", "--user", "is-enabled", service_name])
        active_ok, active_out, active_err = self._run_command(["systemctl", "--user", "is-active", service_name])

        enabled = enabled_out if enabled_ok else "unknown"
        active = active_out if active_ok else "inactive"

        return {
            "enabled": enabled,
            "active": active,
            "status": "pass" if active == "active" else "fail",
            "error": enabled_err or active_err,
        }

    def _broker_status(self) -> dict:
        policy_file = Path(self.slimyos_home) / "config" / "policy.json"
        fallback_policy_file = Path(self.repo_path) / "policies" / "default.policy.json"

        output: dict[str, Any] = {
            "url": self.broker_url,
            "reachable": False,
            "health_ok": False,
            "tool_count": 0,
            "policy_loaded": False,
            "manifest_loaded": False,
            "policy_file": str(policy_file if policy_file.exists() else fallback_policy_file),
            "policy_file_exists": policy_file.exists() or fallback_policy_file.exists(),
            "status": "fail",
            "state": None,
            "audit_recent": None,
            "error": "",
        }

        try:
            health = self._http_get_json(f"{self.broker_url}/health")
            output["reachable"] = True
            output["health_ok"] = health.get("status") == "ok"
            output["tool_count"] = int(health.get("tools", 0))

            tools_payload = self._http_get_json(f"{self.broker_url}/tools")
            tool_count = int(tools_payload.get("count", len(tools_payload.get("tools", []))))
            output["manifest_loaded"] = tool_count > 0

            output["state"] = self._http_get_json(f"{self.broker_url}/state")
            output["audit_recent"] = self._http_get_json(f"{self.broker_url}/audit/recent")

            output["policy_loaded"] = bool(output["policy_file_exists"] and output["health_ok"])
            if output["health_ok"] and output["manifest_loaded"]:
                output["status"] = "pass"
        except (urlerror.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            output["error"] = str(exc)

        return output

    def _hermes_status(self) -> dict:
        installed = bool(shutil.which("hermes") or Path(os.path.expanduser("~/.local/bin/hermes")).exists())
        binary = shutil.which("hermes") or os.path.expanduser("~/.local/bin/hermes")

        output = {
            "installed": installed,
            "binary": binary if installed else "",
            "proxy_url": self.hermes_models_url,
            "proxy_reachable": False,
            "models": [],
            "auth_state": "auth_required_or_proxy_down",
            "status": "warn",
            "error": "",
        }

        if not installed:
            output["auth_state"] = "not_installed"
            return output

        try:
            payload = self._http_get_json(self.hermes_models_url)
            output["proxy_reachable"] = True
            output["models"] = payload.get("data", payload.get("models", []))
            output["auth_state"] = "connected"
            output["status"] = "pass"
        except (urlerror.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            output["error"] = str(exc)

        return output

    def _audit_status(self, audit_recent: dict | None) -> dict:
        audit_dir = Path(self.slimyos_home) / "audit"
        latest_file = ""
        latest_mtime = 0.0

        if audit_dir.exists():
            for candidate in audit_dir.glob("audit-*.jsonl"):
                try:
                    stat = candidate.stat()
                except OSError:
                    continue
                if stat.st_mtime > latest_mtime:
                    latest_mtime = stat.st_mtime
                    latest_file = str(candidate)

        recent_event_count = 0
        if audit_recent:
            recent_event_count = int(audit_recent.get("count", len(audit_recent.get("events", []))))

        return {
            "path": str(audit_dir),
            "exists": audit_dir.exists(),
            "latest_file": latest_file,
            "recent_event_count": recent_event_count,
            "status": "pass" if audit_dir.exists() else "fail",
        }

    def _proof_pack_status(self) -> dict:
        proof_dir = Path(self.slimyos_home) / "proofs"
        latest = ""
        latest_mtime = 0.0

        if proof_dir.exists():
            for candidate in proof_dir.rglob("*"):
                try:
                    stat = candidate.stat()
                except OSError:
                    continue
                if stat.st_mtime > latest_mtime:
                    latest_mtime = stat.st_mtime
                    latest = str(candidate)

        return {
            "path": str(proof_dir),
            "exists": proof_dir.exists(),
            "latest": latest,
            "status": "pass" if proof_dir.exists() else "warn",
        }
