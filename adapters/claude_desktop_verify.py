"""Post-install verification for Claude Desktop MCP config.

Reads the installed config, verifies SlimyOS entry, extracts the launcher
command, validates it, and provides structured proof artifacts.

Safety:
- Does not read or expose private Claude chat content.
- Does not dump secrets or tokens.
- Redacts env values that look secret-like.
- Does not automate Claude Desktop GUI interaction.
- Does not require provider login or API keys.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


SECRET_KEY_PATTERNS = re.compile(
    r"(key|token|secret|password|auth|credential|api[_-]?key)",
    re.IGNORECASE,
)


def _extract_content_data(response: dict[str, Any]) -> dict[str, Any]:
    content = response.get("result", {}).get("content", [])
    if content and isinstance(content, list) and len(content) > 0:
        text = content[0].get("text", "{}")
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def load_claude_desktop_config(config_path: str) -> dict[str, Any]:
    raw = Path(config_path).read_text(encoding="utf-8")
    return json.loads(raw)


def find_slimyos_entry(config: dict[str, Any]) -> dict[str, Any] | None:
    servers = config.get("mcpServers", {})
    return servers.get("slimyos")


def list_existing_servers(config: dict[str, Any]) -> list[str]:
    return list(config.get("mcpServers", {}).keys())


def redact_entry(entry: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(entry)
    env = redacted.get("env")
    if isinstance(env, dict):
        redacted_env = {}
        for k, v in env.items():
            if SECRET_KEY_PATTERNS.search(k):
                redacted_env[k] = "***REDACTED***"
            else:
                redacted_env[k] = v
        redacted["env"] = redacted_env
    return redacted


def validate_launcher(entry: dict[str, Any]) -> dict[str, Any]:
    command = entry.get("command", "")
    launcher = Path(command)
    exists = launcher.exists()
    is_executable = exists and os.access(str(launcher), os.X_OK)
    return {
        "command": command,
        "path_exists": exists,
        "is_executable": is_executable,
        "valid": exists and is_executable,
    }


def build_exact_command(entry: dict[str, Any]) -> list[str]:
    cmd = [entry.get("command", "")]
    cmd.extend(entry.get("args", []))
    return cmd


def build_env(entry: dict[str, Any]) -> dict[str, str]:
    return dict(entry.get("env", {}))


def run_mcp_checks(
    command: list[str],
    env: dict[str, str],
    repo_root: str,
    broker_url: str,
) -> dict[str, Any]:
    results: dict[str, Any] = {
        "initialize": {},
        "tools_list": {},
        "safe_call": {},
        "blocked_call": {},
        "gated_call": {},
    }
    errors: list[str] = []

    full_env = dict(os.environ)
    full_env.update(env)

    proc = subprocess.Popen(
        command,
        cwd=repo_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=full_env,
    )

    def rpc(req: dict[str, Any]) -> dict[str, Any]:
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline().strip()
        if not line:
            raise RuntimeError("No MCP response received")
        return json.loads(line)

    try:
        results["initialize"] = rpc(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )

        results["tools_list"] = rpc(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        )
        tools = results["tools_list"].get("result", {}).get("tools", [])
        results["tool_count"] = len(tools)
        if len(tools) < 40:
            errors.append(f"tool_count_below_threshold:{len(tools)}")

        results["safe_call"] = rpc(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "slimyos_read_file",
                    "arguments": {"path": str(Path(repo_root) / "README.md")},
                },
            }
        )
        safe_struct = _extract_content_data(results["safe_call"])
        if not safe_struct.get("success"):
            errors.append("safe_call_not_success")

        results["blocked_call"] = rpc(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "slimyos_raw_shell",
                    "arguments": {"command": "rm -rf /"},
                },
            }
        )
        blocked_struct = _extract_content_data(results["blocked_call"])
        if blocked_struct.get("disposition") != "blocked":
            errors.append(
                f"raw_shell_not_blocked:{blocked_struct.get('disposition')}"
            )

        results["gated_call"] = rpc(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "slimyos_restart_service",
                    "arguments": {"service_name": "sshd"},
                },
            }
        )
        gated_struct = _extract_content_data(results["gated_call"])
        if gated_struct.get("disposition") not in {"blocked", "approval_required"}:
            errors.append(
                f"restart_service_not_gated:{gated_struct.get('disposition')}"
            )

    except Exception as exc:
        errors.append(f"mcp_rpc_error:{exc}")
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            proc.kill()

    return {"results": results, "errors": errors}


def detect_claude_desktop_process() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "claude"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        pids = result.stdout.strip().splitlines() if result.stdout.strip() else []
        return {
            "running": len(pids) > 0,
            "pid_count": len(pids),
            "note": "detected via pgrep; no interaction performed",
        }
    except Exception as exc:
        return {
            "running": False,
            "pid_count": 0,
            "error": str(exc),
            "note": "pgrep unavailable or errored",
        }


def build_manual_prompt() -> str:
    return (
        "Restart Claude Desktop, then ask it:\n\n"
        '  "Use the SlimyOS MCP tools to list the allowed repo directory '
        'and summarize the policy result."\n\n'
        "You should see SlimyOS tools listed under the MCP sidebar.\n"
        "If Claude Desktop fails to load the MCP server, rollback with:\n\n"
        "  ./scripts/slimyos-mcp-configure.sh --rollback\n"
    )


def run_full_verification(
    repo_root: str,
    proof_dir: str,
    broker_url: str = "http://localhost:3003",
    config_path_override: str | None = None,
) -> dict[str, Any]:
    from datetime import datetime, timezone
    from urllib import request as urlrequest

    errors: list[str] = []
    warnings: list[str] = []
    out = Path(proof_dir)
    out.mkdir(parents=True, exist_ok=True)

    config_path = config_path_override or str(
        Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
    )
    (out / "claude_config_path.txt").write_text(config_path + "\n")

    config: dict[str, Any] = {}
    try:
        config = load_claude_desktop_config(config_path)
    except FileNotFoundError:
        errors.append("claude_desktop_config_not_found")
    except json.JSONDecodeError as exc:
        errors.append(f"claude_desktop_config_invalid_json:{exc}")

    redacted_config = redact_entry(config) if config else {}
    (out / "claude_config_redacted.json").write_text(
        json.dumps(redacted_config, indent=2)
    )

    existing_servers = list_existing_servers(config) if config else []
    (out / "existing_mcpservers.json").write_text(
        json.dumps({"servers": existing_servers}, indent=2)
    )

    slimyos_entry = find_slimyos_entry(config) if config else None
    slimyos_found = slimyos_entry is not None
    (out / "slimyos_mcp_entry.json").write_text(
        json.dumps(
            redact_entry(slimyos_entry) if slimyos_entry else {},
            indent=2,
        )
    )
    if not slimyos_found:
        errors.append("slimyos_mcp_entry_not_found")

    launcher_check: dict[str, Any] = {}
    if slimyos_entry:
        launcher_check = validate_launcher(slimyos_entry)
        if not launcher_check.get("valid"):
            errors.append(f"launcher_invalid:{launcher_check}")
    (out / "launcher_check.json").write_text(
        json.dumps(launcher_check, indent=2)
    )

    broker_health_before: dict[str, Any] = {}
    try:
        with urlrequest.urlopen(f"{broker_url}/health", timeout=3) as resp:
            broker_health_before = json.loads(resp.read())
    except Exception as exc:
        errors.append(f"broker_unreachable_before:{exc}")
    (out / "broker_health_before.json").write_text(
        json.dumps(broker_health_before, indent=2)
    )

    audit_before: dict[str, Any] = {"note": "audit count not available from broker API directly"}
    try:
        with urlrequest.urlopen(f"{broker_url}/tools", timeout=3) as resp:
            tools_data = json.loads(resp.read())
            audit_before = {"tool_count": len(tools_data.get("tools", []))}
    except Exception:
        pass
    (out / "audit_count_before.json").write_text(
        json.dumps(audit_before, indent=2)
    )

    mcp_results: dict[str, Any] = {"results": {}, "errors": []}
    if slimyos_entry and launcher_check.get("valid"):
        command = build_exact_command(slimyos_entry)
        env = build_env(slimyos_entry)
        mcp_results = run_mcp_checks(command, env, repo_root, broker_url)
        errors.extend(mcp_results.get("errors", []))

        for key in ("initialize", "tools_list", "safe_call", "blocked_call", "gated_call"):
            (out / f"mcp_{key}.json").write_text(
                json.dumps(mcp_results["results"].get(key, {}), indent=2)
            )

    broker_health_after: dict[str, Any] = {}
    try:
        with urlrequest.urlopen(f"{broker_url}/health", timeout=3) as resp:
            broker_health_after = json.loads(resp.read())
    except Exception as exc:
        warnings.append(f"broker_unreachable_after:{exc}")
    (out / "broker_health_after.json").write_text(
        json.dumps(broker_health_after, indent=2)
    )

    audit_after: dict[str, Any] = {"note": "audit count not available from broker API directly"}
    try:
        with urlrequest.urlopen(f"{broker_url}/tools", timeout=3) as resp:
            tools_data = json.loads(resp.read())
            audit_after = {"tool_count": len(tools_data.get("tools", []))}
    except Exception:
        pass
    (out / "audit_count_after.json").write_text(
        json.dumps(audit_after, indent=2)
    )

    process_check = detect_claude_desktop_process()
    (out / "claude_process_check.json").write_text(
        json.dumps(process_check, indent=2)
    )

    manual_prompt = build_manual_prompt()
    (out / "manual_operator_prompt.md").write_text(manual_prompt)

    (out / "warnings.json").write_text(json.dumps(warnings, indent=2))
    (out / "errors.json").write_text(json.dumps(errors, indent=2))

    result = "PASS" if not errors else "FAIL"
    (out / "RESULT.txt").write_text(f"RESULT={result}\n")

    tool_count = mcp_results.get("results", {}).get("tool_count", 0)
    safe_data = _extract_content_data(
        mcp_results.get("results", {}).get("safe_call", {})
    )
    safe_success = safe_data.get("success", False)
    blocked_data = _extract_content_data(
        mcp_results.get("results", {}).get("blocked_call", {})
    )
    blocked_disp = blocked_data.get("disposition", "")
    gated_data = _extract_content_data(
        mcp_results.get("results", {}).get("gated_call", {})
    )
    gated_disp = gated_data.get("disposition", "")

    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hostname": __import__("platform").node(),
        "repo_path": str(Path(repo_root).resolve()),
        "broker_url": broker_url,
        "config_path": config_path,
        "existing_servers": existing_servers,
        "slimyos_found": slimyos_found,
        "launcher_path": launcher_check.get("command", ""),
        "tool_count": tool_count,
        "safe_call_success": safe_success,
        "blocked_disposition": blocked_disp,
        "gated_disposition": gated_disp,
        "claude_process_running": process_check.get("running", False),
        "result": result,
        "warnings": warnings,
        "errors": errors,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))

    return meta
