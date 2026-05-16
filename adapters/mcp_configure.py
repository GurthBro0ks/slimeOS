"""Safe MCP client config apply + rollback for SlimyOS.

Safety rules:
- Default mode is dry-run (no mutation).
- --apply requires explicit flag.
- Every --apply creates a timestamped backup first.
- Every changed config is JSON validated where practical.
- --rollback restores the latest backup.
- No secrets, no provider login, no raw shell, no privileged changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def detect_config_paths(home_override: str | None = None) -> dict[str, Any]:
    home = Path(home_override) if home_override else Path.home()

    claude_desktop_path = home / ".config" / "Claude" / "claude_desktop_config.json"
    claude_desktop_alt = home / ".config" / "claude-desktop" / "claude_desktop_config.json"

    detected: dict[str, Any] = {
        "claude_desktop": {
            "primary_path": str(claude_desktop_path),
            "alt_path": str(claude_desktop_alt),
            "resolved_path": "",
            "exists": False,
            "status": "not_found",
        },
        "claude_code": {
            "binary": shutil.which("claude") or "",
            "installed": shutil.which("claude") is not None,
            "status": "not_found",
        },
        "opencode": {
            "binary": shutil.which("opencode") or "",
            "installed": shutil.which("opencode") is not None,
            "status": "not_found",
        },
        "codex": {
            "binary": shutil.which("codex") or "",
            "installed": shutil.which("codex") is not None,
            "status": "not_found",
        },
    }

    for path in (claude_desktop_path, claude_desktop_alt):
        if path.exists():
            detected["claude_desktop"]["resolved_path"] = str(path)
            detected["claude_desktop"]["exists"] = True
            detected["claude_desktop"]["status"] = "found"
            break

    if not detected["claude_desktop"]["exists"]:
        detected["claude_desktop"]["resolved_path"] = str(claude_desktop_path)

    for client in ("claude_code", "opencode", "codex"):
        if detected[client]["installed"]:
            detected[client]["status"] = "found"
        else:
            detected[client]["status"] = "warn"

    return detected


def generate_claude_desktop_config(
    repo_root: str,
    broker_url: str,
    existing_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_cmd = str(Path(repo_root) / "scripts" / "run-mcp-server.sh")
    slimyos_entry = {
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

    if existing_config is None:
        return {"mcpServers": {"slimyos": slimyos_entry}}

    merged = dict(existing_config)
    servers = dict(merged.get("mcpServers", {}))
    servers["slimyos"] = slimyos_entry
    merged["mcpServers"] = servers
    return merged


def generate_client_notes(repo_root: str, broker_url: str) -> dict[str, str]:
    run_cmd = str(Path(repo_root) / "scripts" / "run-mcp-server.sh")

    claude_code_md = "\n".join([
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
        "",
        "Status: MANUAL_REQUIRED if no safe file-based config path is detected.",
    ])

    opencode_md = "\n".join([
        "# SlimyOS MCP for OpenCode",
        "",
        "Command:",
        f"`{run_cmd}`",
        "",
        "OpenCode can discover tools through MCP, but execution remains",
        "policy-gated through slimy-toold.",
        "",
        "Status: MANUAL_REQUIRED if no safe config path is detected.",
    ])

    codex_md = "\n".join([
        "# SlimyOS MCP for Codex",
        "",
        "Command:",
        f"`{run_cmd}`",
        "",
        "Blocked and approval-gated outcomes are returned as-is.",
        "No provider login or secrets required for MCP bridge checks.",
        "",
        "Status: MANUAL_REQUIRED if no safe config path is detected.",
    ])

    return {
        "generated_claude_code_notes.md": claude_code_md,
        "generated_opencode_notes.md": opencode_md,
        "generated_codex_notes.md": codex_md,
    }


def sha256_of_file(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_json_string(content: str) -> tuple[bool, str]:
    try:
        json.loads(content)
        return True, ""
    except (json.JSONDecodeError, TypeError) as exc:
        return False, str(exc)


def backup_dir_root(proof_dir: str | None = None, home_override: str | None = None) -> Path:
    if proof_dir:
        return Path(proof_dir) / "backups"
    home = Path(home_override) if home_override else Path.home()
    candidate = home / ".config" / "slimyos" / "backups" / "mcp-config"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        test_file = candidate / ".write_test"
        test_file.write_text("ok")
        test_file.unlink()
        return candidate
    except (OSError, PermissionError):
        fallback = Path("/tmp/slimyos_backups_mcp-config")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def create_backup(
    target_path: str,
    client_name: str,
    backup_root: Path,
) -> dict[str, Any]:
    source = Path(target_path)
    utc_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stamp_dir = backup_root / utc_stamp
    stamp_dir.mkdir(parents=True, exist_ok=True)

    sha_before = sha256_of_file(source)
    metadata: dict[str, Any] = {
        "client": client_name,
        "target_path": str(target_path),
        "sha256_before": sha_before,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
        "restore_instructions": f"Copy the 'original' file back to {target_path}",
    }

    if source.exists():
        shutil.copy2(str(source), str(stamp_dir / "original"))
    else:
        (stamp_dir / "original_absent").write_text("file did not exist before apply\n")

    (stamp_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    return {
        "backup_dir": str(stamp_dir),
        "sha256_before": sha_before,
        "metadata": metadata,
    }


def apply_claude_desktop_config(
    target_path: str,
    repo_root: str,
    broker_url: str,
    backup_root: Path,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    target = Path(target_path)
    existing_config: dict[str, Any] | None = None

    if target.exists():
        try:
            raw = target.read_text(encoding="utf-8")
            valid, err = validate_json_string(raw)
            if not valid:
                return {
                    "status": "FAIL",
                    "errors": [f"existing_config_invalid_json:{err}"],
                    "warnings": warnings,
                }
            existing_config = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "status": "FAIL",
                "errors": [f"cannot_read_existing:{exc}"],
                "warnings": warnings,
            }

    backup_info = create_backup(target_path, "claude_desktop", backup_root)
    backup_info["metadata"]["sha256_before"] = backup_info["sha256_before"]

    new_config = generate_claude_desktop_config(repo_root, broker_url, existing_config)
    new_content = json.dumps(new_config, indent=2)

    valid, err = validate_json_string(new_content)
    if not valid:
        return {
            "status": "FAIL",
            "errors": [f"generated_config_invalid_json:{err}"],
            "warnings": warnings,
            "backup": backup_info,
        }

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new_content + "\n", encoding="utf-8")

    sha_after = sha256_of_file(target)
    backup_info["metadata"]["sha256_after"] = sha_after

    backup_meta_path = Path(backup_info["backup_dir"]) / "metadata.json"
    backup_meta = json.loads(backup_meta_path.read_text())
    backup_meta["sha256_after"] = sha_after
    backup_meta_path.write_text(json.dumps(backup_meta, indent=2))

    return {
        "status": "OK",
        "errors": errors,
        "warnings": warnings,
        "backup": backup_info,
        "sha256_after": sha_after,
    }


def rollback_latest(backup_root: Path, client_name: str | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not backup_root.exists():
        return {
            "status": "FAIL",
            "errors": ["no_backup_directory_found"],
            "warnings": warnings,
        }

    stamp_dirs = sorted(
        [d for d in backup_root.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )

    if client_name:
        filtered = []
        for d in stamp_dirs:
            meta_path = d / "metadata.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                if meta.get("client") == client_name:
                    filtered.append(d)
        stamp_dirs = filtered

    if not stamp_dirs:
        return {
            "status": "FAIL",
            "errors": ["no_backups_found"],
            "warnings": warnings,
        }

    latest = stamp_dirs[0]
    meta_path = latest / "metadata.json"
    if not meta_path.exists():
        return {
            "status": "FAIL",
            "errors": ["backup_metadata_missing"],
            "warnings": warnings,
        }

    meta = json.loads(meta_path.read_text())
    target_path = meta.get("target_path", "")
    if not target_path:
        return {
            "status": "FAIL",
            "errors": ["backup_target_path_missing"],
            "warnings": warnings,
        }

    original = latest / "original"
    original_absent = latest / "original_absent"

    if original_absent.exists():
        target = Path(target_path)
        if target.exists():
            target.unlink()
        return {
            "status": "OK",
            "errors": errors,
            "warnings": warnings,
            "restored_from": str(latest),
            "target_path": target_path,
            "action": "removed_created_file",
        }

    if not original.exists():
        return {
            "status": "FAIL",
            "errors": ["original_backup_file_missing"],
            "warnings": warnings,
        }

    shutil.copy2(str(original), str(target_path))

    target = Path(target_path)
    sha_after = sha256_of_file(target)

    valid, err = validate_json_string(target.read_text(encoding="utf-8"))
    if not valid:
        warnings.append(f"restored_file_invalid_json:{err}")

    return {
        "status": "OK",
        "errors": errors,
        "warnings": warnings,
        "restored_from": str(latest),
        "target_path": target_path,
        "sha256_after_restore": sha_after,
        "action": "restored_original",
    }


def run_configure(
    repo_root: str,
    proof_dir: str,
    broker_url: str = "http://localhost:3003",
    mode: str = "dry-run",
    home_override: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    out = Path(proof_dir)
    out.mkdir(parents=True, exist_ok=True)

    detected = detect_config_paths(home_override)
    (out / "detected_clients.json").write_text(
        json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "binary"} or v for k, v in detected.items()}, indent=2)
    )
    (out / "detected_config_paths.json").write_text(json.dumps(detected, indent=2))

    snippets = generate_claude_desktop_config(repo_root, broker_url)
    (out / "generated_claude_desktop_config.json").write_text(json.dumps(snippets, indent=2))

    client_notes = generate_client_notes(repo_root, broker_url)
    for name, content in client_notes.items():
        (out / name).write_text(content)

    planned: dict[str, Any] = {"mode": mode, "clients": {}}

    cd = detected["claude_desktop"]
    planned["clients"]["claude_desktop"] = {
        "action": "merge_or_create" if mode == "apply" else "dry-run",
        "target": cd["resolved_path"],
        "exists": cd["exists"],
    }

    for client_key in ("claude_code", "opencode", "codex"):
        if detected[client_key]["installed"]:
            planned["clients"][client_key] = {
                "action": "manual_required",
                "status": "MANUAL_REQUIRED",
            }
        else:
            planned["clients"][client_key] = {
                "action": "manual_required",
                "status": "MANUAL_REQUIRED",
            }
            warnings.append(f"client_missing:{client_key}")

    (out / "planned_changes.json").write_text(json.dumps(planned, indent=2))

    bdir = backup_dir_root(proof_dir if mode == "dry-run" else None, home_override)
    backups_manifest: list[dict[str, Any]] = []

    apply_result: dict[str, Any] | None = None
    rollback_result: dict[str, Any] | None = None
    status_result: dict[str, Any] | None = None

    if mode == "status":
        status_result = _build_status(detected, repo_root, broker_url)
        (out / "status_result.json").write_text(json.dumps(status_result, indent=2))

    elif mode == "apply":
        cd_path = cd["resolved_path"]
        apply_result = apply_claude_desktop_config(cd_path, repo_root, broker_url, bdir)
        if apply_result.get("status") != "OK":
            errors.append(f"claude_desktop_apply_failed:{apply_result.get('errors', [])}")
        if apply_result.get("backup"):
            backups_manifest.append(apply_result["backup"])
        (out / "apply_result.json").write_text(json.dumps(apply_result, indent=2))

        for client_key in ("claude_code", "opencode", "codex"):
            if not detected[client_key]["installed"]:
                warnings.append(f"client_missing:{client_key}")
            else:
                warnings.append(f"client_manual_required:{client_key}")

    elif mode == "rollback":
        rollback_result = rollback_latest(bdir)
        if rollback_result.get("status") != "OK":
            errors.append(f"rollback_failed:{rollback_result.get('errors', [])}")
        (out / "rollback_result.json").write_text(json.dumps(rollback_result, indent=2))

    (out / "backups_manifest.json").write_text(json.dumps(backups_manifest, indent=2))

    validation: dict[str, Any] = {"checks": []}
    if mode in ("apply", "rollback") and cd["resolved_path"]:
        target = Path(cd["resolved_path"])
        if target.exists():
            valid, err = validate_json_string(target.read_text(encoding="utf-8"))
            validation["checks"].append({
                "path": str(target),
                "valid_json": valid,
                "error": err,
            })
        else:
            validation["checks"].append({
                "path": str(target),
                "valid_json": True,
                "note": "file does not exist (expected after rollback of new install)",
            })
    (out / "validation_results.json").write_text(json.dumps(validation, indent=2))

    (out / "warnings.json").write_text(json.dumps(warnings, indent=2))
    (out / "errors.json").write_text(json.dumps(errors, indent=2))

    result = "PASS" if not errors else "FAIL"
    (out / "RESULT.txt").write_text(f"RESULT={result}\n")

    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
        "repo_path": str(Path(repo_root).resolve()),
        "broker_url": broker_url,
        "mode": mode,
        "result": result,
        "warnings": warnings,
        "errors": errors,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))

    return {
        "result": result,
        "mode": mode,
        "warnings": warnings,
        "errors": errors,
        "detected": detected,
        "proof_dir": str(out),
        "apply_result": apply_result,
        "rollback_result": rollback_result,
        "status_result": status_result,
    }


def _build_status(detected: dict[str, Any], repo_root: str, broker_url: str) -> dict[str, Any]:
    status: dict[str, Any] = {"clients": {}}

    cd = detected["claude_desktop"]
    slimyos_installed = False
    if cd["exists"]:
        try:
            raw = Path(cd["resolved_path"]).read_text(encoding="utf-8")
            config = json.loads(raw)
            slimyos_installed = "slimyos" in config.get("mcpServers", {})
        except (OSError, json.JSONDecodeError):
            pass

    status["clients"]["claude_desktop"] = {
        "config_path": cd["resolved_path"],
        "config_exists": cd["exists"],
        "slimyos_installed": slimyos_installed,
        "status": "installed" if slimyos_installed else "not_installed",
    }

    for client_key in ("claude_code", "opencode", "codex"):
        binary = detected[client_key].get("binary", "")
        status["clients"][client_key] = {
            "binary": binary,
            "installed": bool(binary),
            "status": "found" if binary else "missing",
            "config": "MANUAL_REQUIRED",
        }

    return status
