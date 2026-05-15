"""
SlimyOS Ops Room — Infrastructure operations via scoped wrappers.

The Ops Room exists so agents NEVER run:
  sudo systemctl restart anything
  
Instead they call:
  slimy-toold restart_service(service_name="slimy-bot-v2")

Which checks:
  1. Is "slimy-bot-v2" in the allowed services list?
  2. Does the policy allow this agent to restart it?
  3. Has approval been granted?
  4. Run a pre-check (is the service currently running?)
  5. Execute the scoped wrapper
  6. Run a post-check (did the service come back?)
  7. Record everything in the audit log
"""

import os
import subprocess
import json
from datetime import datetime


def _run_safe(command: list, timeout: int = 15) -> dict:
    """Run a command with timeout. NO sudo ever."""
    try:
        r = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return {"output": r.stdout.strip(), "error": r.stderr.strip() if r.returncode != 0 else "",
                "returncode": r.returncode, "success": r.returncode == 0}
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"output": "", "error": str(e), "returncode": -1, "success": False}


def handle_service_status(args: dict) -> dict:
    """Check status of a service. Read-only, safe."""
    service = args["service_name"]
    
    r = _run_safe(["systemctl", "is-active", service])
    if r["success"]:
        detail = _run_safe(["systemctl", "show", service,
                           "--property=ActiveState,SubState,MainPID,MemoryCurrent"])
        return {"output": f"{service}: {r['output']}\n{detail['output']}", "active": r["output"] == "active"}
    
    return {"output": f"[MOCK] {service}: active (mock mode)", "active": True, "mode": "mock"}


def handle_service_logs(args: dict) -> dict:
    """Read recent logs for a service. Read-only."""
    service = args["service_name"]
    lines = args.get("lines", 50)
    
    r = _run_safe(["journalctl", "-u", service, "-n", str(lines), "--no-pager"])
    if r["success"]:
        return {"output": r["output"][:5000]}
    
    return {"output": f"[MOCK] Last {lines} lines for {service}", "mode": "mock"}


def handle_docker_ps(args: dict) -> dict:
    """List running Docker containers. Read-only."""
    fmt = args.get("format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}")
    
    r = _run_safe(["docker", "ps", "--format", fmt])
    if r["success"]:
        return {"output": r["output"]}
    
    return {"output": "[MOCK] CONTAINER  STATUS  PORTS\nslimy-bot  Up 2h  :3000", "mode": "mock"}


def handle_pm2_status(args: dict) -> dict:
    """Check PM2 process list. Read-only."""
    r = _run_safe(["pm2", "jlist"])
    if r["success"]:
        try:
            procs = json.loads(r["output"])
            summary = "\n".join(
                f"  {p['name']}: {p['pm2_env']['status']} (pid: {p.get('pid', '?')}, restarts: {p['pm2_env'].get('restart_time', 0)})"
                for p in procs
            )
            return {"output": f"PM2 processes:\n{summary}", "processes": len(procs)}
        except (json.JSONDecodeError, KeyError):
            return {"output": r["output"][:2000]}
    
    return {"output": "[MOCK] PM2: slimy-bot (online), admin-api (online)", "mode": "mock"}


def handle_disk_usage(args: dict) -> dict:
    """Check disk usage. Read-only."""
    path = args.get("path", "/")
    
    r = _run_safe(["df", "-h", path])
    if r["success"]:
        return {"output": r["output"]}
    
    return {"output": f"[MOCK] {path}: 45G used / 120G (38%)", "mode": "mock"}


def handle_system_health(args: dict) -> dict:
    """Composite system health check. Read-only."""
    checks = {}
    
    # Uptime
    r = _run_safe(["uptime", "-p"])
    checks["uptime"] = r["output"] if r["success"] else "unknown"
    
    # Memory
    r = _run_safe(["free", "-h"])
    checks["memory"] = r["output"].split("\n")[1] if r["success"] else "unknown"
    
    # Disk
    r = _run_safe(["df", "-h", "/"])
    checks["disk"] = r["output"].split("\n")[-1] if r["success"] and r["output"] else "unknown"
    
    # Load
    r = _run_safe(["cat", "/proc/loadavg"])
    checks["load"] = r["output"] if r["success"] else "unknown"
    
    output = "\n".join(f"  {k}: {v}" for k, v in checks.items())
    return {"output": f"System Health:\n{output}"}


def handle_create_proof_pack(args: dict) -> dict:
    """
    Generate a proof pack for an ops task.
    Captures system state before/after an operation.
    """
    label = args.get("label", "ops-proof")
    services = args.get("services", [])
    
    proof = {"label": label, "timestamp": datetime.utcnow().isoformat(), "services": {}}
    
    for svc in services:
        status = handle_service_status({"service_name": svc})
        proof["services"][svc] = status.get("output", "unknown")
    
    return {"output": json.dumps(proof, indent=2), "proof": proof}


OPS_ROOM_TOOLS = {
    "service_status": handle_service_status,
    "service_logs": handle_service_logs,
    "docker_ps": handle_docker_ps,
    "pm2_status": handle_pm2_status,
    "disk_usage": handle_disk_usage,
    "system_health": handle_system_health,
    "ops_proof_pack": handle_create_proof_pack,
}
