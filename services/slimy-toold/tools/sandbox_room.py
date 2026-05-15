"""
SlimyOS Sandbox Room — Isolated execution for risky tasks.

Anything unknown, untrusted, or dangerous goes here first.
The sandbox provides:
- Docker container isolation
- Temporary filesystem (destroyed after task)
- Network restrictions
- Screenshot capture from inside sandbox
- Trajectory recording for proof packs

Implementation levels:
1. Docker container (available now)
2. trycua/cua VM sandbox (future — Linux Docker mode)
3. bubblewrap/firejail lightweight sandbox (future)
"""

import os
import subprocess
import json
import uuid
import tempfile
from datetime import datetime


def _docker_available() -> bool:
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def handle_sandbox_create(args: dict) -> dict:
    """Create a new sandbox environment."""
    sandbox_id = args.get("sandbox_id", str(uuid.uuid4())[:8])
    image = args.get("image", "ubuntu:22.04")
    network = args.get("network", "none")  # none, bridge, host
    
    if _docker_available():
        r = subprocess.run(
            ["docker", "create", "--name", f"slimyos-sandbox-{sandbox_id}",
             f"--network={network}", "--rm", image, "sleep", "3600"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            subprocess.run(
                ["docker", "start", f"slimyos-sandbox-{sandbox_id}"],
                capture_output=True, timeout=10,
            )
            return {
                "output": f"Sandbox {sandbox_id} created (image={image}, network={network})",
                "sandbox_id": sandbox_id,
                "mode": "docker",
            }
        return {"output": "", "error": f"Docker create failed: {r.stderr}"}
    
    return {
        "output": f"[MOCK] Sandbox {sandbox_id} created (image={image}, network={network})",
        "sandbox_id": sandbox_id,
        "mode": "mock",
    }


def handle_sandbox_exec(args: dict) -> dict:
    """Execute a command inside a sandbox."""
    sandbox_id = args["sandbox_id"]
    command = args["command"]
    timeout = args.get("timeout_seconds", 30)
    
    if _docker_available():
        try:
            r = subprocess.run(
                ["docker", "exec", f"slimyos-sandbox-{sandbox_id}", "sh", "-c", command],
                capture_output=True, text=True, timeout=timeout,
            )
            return {
                "output": r.stdout,
                "error": r.stderr if r.returncode != 0 else "",
                "exit_code": r.returncode,
                "mode": "docker",
            }
        except subprocess.TimeoutExpired:
            return {"output": "", "error": f"Command timed out ({timeout}s)"}
    
    return {
        "output": f"[MOCK] Sandbox {sandbox_id} exec: {command}",
        "mode": "mock",
    }


def handle_sandbox_destroy(args: dict) -> dict:
    """Destroy a sandbox — all data inside is lost."""
    sandbox_id = args["sandbox_id"]
    
    if _docker_available():
        subprocess.run(
            ["docker", "rm", "-f", f"slimyos-sandbox-{sandbox_id}"],
            capture_output=True, timeout=10,
        )
        return {"output": f"Sandbox {sandbox_id} destroyed", "mode": "docker"}
    
    return {"output": f"[MOCK] Sandbox {sandbox_id} destroyed", "mode": "mock"}


def handle_sandbox_copy_out(args: dict) -> dict:
    """Copy a file from sandbox to host (for proof packs)."""
    sandbox_id = args["sandbox_id"]
    src = args["src_path"]
    dst = args["dst_path"]
    
    if _docker_available():
        r = subprocess.run(
            ["docker", "cp", f"slimyos-sandbox-{sandbox_id}:{src}", dst],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            return {"output": f"Copied {src} → {dst}", "mode": "docker"}
        return {"output": "", "error": r.stderr}
    
    return {"output": f"[MOCK] Copy {src} → {dst}", "mode": "mock"}


SANDBOX_ROOM_TOOLS = {
    "sandbox_create": handle_sandbox_create,
    "sandbox_exec": handle_sandbox_exec,
    "sandbox_destroy": handle_sandbox_destroy,
    "sandbox_copy_out": handle_sandbox_copy_out,
}
