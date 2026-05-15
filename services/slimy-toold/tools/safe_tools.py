"""
Safe mock tools for SlimyOS proof-of-life.

These tools perform REAL but SAFE operations:
- read_file: reads actual files (within allowed paths)
- write_file: writes to actual files (within allowed paths)
- list_directory: lists actual directories
- run_tests: simulates test execution
- git_status: simulates git status
- restart_service: BLOCKED — demonstrates policy enforcement
- install_package: BLOCKED — demonstrates policy enforcement
"""

import os
from pathlib import Path


def handle_read_file(args: dict) -> dict:
    """Read a file's contents. Safe: read-only operation."""
    path = os.path.expanduser(args["path"])
    max_lines = args.get("max_lines", 500)
    
    if not os.path.exists(path):
        return {"output": f"File not found: {path}", "error": True}
    
    if not os.path.isfile(path):
        return {"output": f"Not a file: {path}", "error": True}
    
    size = os.path.getsize(path)
    with open(path, "r", errors="replace") as f:
        lines = f.readlines()[:max_lines]
    
    content = "".join(lines)
    return {
        "output": content,
        "lines": len(lines),
        "size_bytes": size,
        "truncated": len(lines) >= max_lines,
    }


def handle_list_directory(args: dict) -> dict:
    """List directory contents. Safe: read-only operation."""
    path = os.path.expanduser(args.get("path", "."))
    
    if not os.path.isdir(path):
        return {"output": f"Not a directory: {path}", "error": True}
    
    entries = []
    for entry in sorted(os.listdir(path)):
        full = os.path.join(path, entry)
        etype = "dir" if os.path.isdir(full) else "file"
        size = os.path.getsize(full) if os.path.isfile(full) else 0
        entries.append({"name": entry, "type": etype, "size": size})
    
    return {"output": "\n".join(e["name"] for e in entries), "entries": entries}


def handle_write_file(args: dict) -> dict:
    """Write content to a file. Real but scoped to allowed paths."""
    path = os.path.expanduser(args["path"])
    content = args["content"]
    mode = args.get("mode", "overwrite")
    
    # Create parent dirs if needed
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    
    file_mode = "w" if mode == "overwrite" else "a"
    with open(path, file_mode) as f:
        f.write(content)
    
    return {
        "output": f"Written {len(content)} bytes to {path}",
        "files_changed": [path],
    }


def handle_run_tests(args: dict) -> dict:
    """Simulate running tests. Safe: mock output only."""
    project_path = args.get("project_path", ".")
    test_command = args.get("test_command", "npm test")
    
    # Mock test output — real test execution comes in Phase 3
    return {
        "output": (
            f"[MOCK] Running '{test_command}' in {project_path}\n"
            "  ✓ test_policy_loads (0.02s)\n"
            "  ✓ test_tool_allowed (0.01s)\n"
            "  ✓ test_tool_blocked (0.01s)\n"
            "  ✓ test_audit_written (0.03s)\n"
            "\n"
            "4 tests passed, 0 failed"
        ),
        "tests_passed": 4,
        "tests_failed": 0,
    }


def handle_git_status(args: dict) -> dict:
    """Check git status. Safe: read-only operation."""
    repo_path = os.path.expanduser(args.get("repo_path", "."))
    
    # Check if it's actually a git repo
    git_dir = os.path.join(repo_path, ".git")
    if os.path.isdir(git_dir):
        # Real git status would go here (Phase 3)
        return {"output": f"[MOCK] Git repo at {repo_path}: clean, on branch main"}
    
    return {"output": f"Not a git repository: {repo_path}", "error": True}


def handle_restart_service(args: dict) -> dict:
    """
    Restart a service. MOCK ONLY — real execution requires:
    1. Policy approval
    2. Scoped wrapper (not raw systemctl)
    3. Pre/post health checks
    
    This mock demonstrates the interface without touching real services.
    """
    service = args.get("service_name", "unknown")
    return {
        "output": f"[MOCK] Would restart service: {service}",
        "note": "Real service restart not implemented in Phase 0-2",
    }


def handle_install_package(args: dict) -> dict:
    """
    Install a package. MOCK ONLY — real execution requires:
    1. Policy approval
    2. Btrfs snapshot first
    3. Scoped wrapper
    
    This mock demonstrates the interface without installing anything.
    """
    package = args.get("package_name", "unknown")
    return {
        "output": f"[MOCK] Would install package: {package}",
        "note": "Real package install not implemented in Phase 0-2",
    }


# Registry of all mock tool handlers
SAFE_TOOLS = {
    "read_file": handle_read_file,
    "list_directory": handle_list_directory,
    "write_file": handle_write_file,
    "run_tests": handle_run_tests,
    "git_status": handle_git_status,
    "restart_service": handle_restart_service,
    "install_package": handle_install_package,
}
