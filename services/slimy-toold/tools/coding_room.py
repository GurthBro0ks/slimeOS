"""
SlimyOS Coding Room — Real Git Tools

These perform REAL git operations, scoped to allowed project roots.

Rules enforced by the Coding Room:
- No commits without running tests first
- No pushes without approval
- No dependency changes without report
- Always capture diff
- Always produce proof pack
"""

import os
import subprocess
import shutil
from pathlib import Path
from datetime import datetime


def _run_git(repo_path: str, *args, check=True) -> dict:
    """Run a git command in the given repo. Returns stdout/stderr."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "output": result.stdout.strip(),
            "error": result.stderr.strip() if result.returncode != 0 else "",
            "returncode": result.returncode,
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"output": "", "error": "Git command timed out (30s)", "returncode": -1, "success": False}
    except FileNotFoundError:
        return {"output": "", "error": "git not found on PATH", "returncode": -1, "success": False}


def handle_git_status(args: dict) -> dict:
    """Real git status."""
    repo = os.path.expanduser(args["repo_path"])
    if not os.path.isdir(os.path.join(repo, ".git")):
        return {"output": f"Not a git repo: {repo}", "error": True}
    
    status = _run_git(repo, "status", "--porcelain")
    branch = _run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    log = _run_git(repo, "log", "--oneline", "-5")
    
    files_status = status["output"] or "(clean)"
    return {
        "output": f"Branch: {branch['output']}\nStatus:\n{files_status}\nRecent commits:\n{log['output']}",
        "branch": branch["output"],
        "clean": status["output"] == "",
        "files": status["output"],
    }


def handle_git_create_branch(args: dict) -> dict:
    """Create and checkout a new branch."""
    repo = os.path.expanduser(args["repo_path"])
    branch = args["branch_name"]
    
    # Sanitize branch name
    safe_branch = branch.replace(" ", "-").replace("/", "-")
    if not safe_branch.replace("-", "").replace("_", "").isalnum():
        return {"output": "", "error": f"Invalid branch name: {branch}"}
    
    result = _run_git(repo, "checkout", "-b", safe_branch)
    if result["success"]:
        return {"output": f"Created and checked out branch: {safe_branch}"}
    else:
        return {"output": "", "error": result["error"]}


def handle_git_diff(args: dict) -> dict:
    """Capture the full diff of staged and unstaged changes."""
    repo = os.path.expanduser(args["repo_path"])
    staged = args.get("staged", False)
    
    if staged:
        result = _run_git(repo, "diff", "--cached")
    else:
        result = _run_git(repo, "diff")
    
    # Also get unstaged if we asked for staged
    if staged:
        unstaged = _run_git(repo, "diff")
        full_diff = result["output"]
        if unstaged["output"]:
            full_diff += "\n\n--- Unstaged ---\n" + unstaged["output"]
    else:
        full_diff = result["output"]
    
    # Count changed files
    stat = _run_git(repo, "diff", "--stat")
    
    return {
        "output": full_diff or "(no changes)",
        "stat": stat["output"],
        "has_changes": bool(full_diff.strip()),
    }


def handle_git_add(args: dict) -> dict:
    """Stage files for commit."""
    repo = os.path.expanduser(args["repo_path"])
    files = args.get("files", ["."])
    
    if isinstance(files, str):
        files = [files]
    
    results = []
    for f in files:
        r = _run_git(repo, "add", f)
        results.append(r)
    
    staged = _run_git(repo, "diff", "--cached", "--name-only")
    return {
        "output": f"Staged files:\n{staged['output']}",
        "files_changed": staged["output"].split("\n") if staged["output"] else [],
    }


def handle_git_commit(args: dict) -> dict:
    """
    Commit staged changes.
    
    IMPORTANT: In real SlimyOS, this requires:
    1. Tests must have passed in this task
    2. Diff must be captured in proof pack
    3. Approval required before push
    """
    repo = os.path.expanduser(args["repo_path"])
    message = args["message"]
    
    # Verify there are staged changes
    staged = _run_git(repo, "diff", "--cached", "--name-only")
    if not staged["output"].strip():
        return {"output": "", "error": "Nothing staged to commit."}
    
    result = _run_git(repo, "commit", "-m", message)
    
    if result["success"]:
        sha = _run_git(repo, "rev-parse", "--short", "HEAD")
        files = staged["output"].strip().split("\n")
        return {
            "output": f"Committed: {sha['output']} — {message}",
            "sha": sha["output"],
            "files_changed": files,
        }
    else:
        return {"output": "", "error": result["error"]}


def handle_git_log(args: dict) -> dict:
    """View recent git log."""
    repo = os.path.expanduser(args["repo_path"])
    count = args.get("count", 10)
    
    result = _run_git(repo, "log", f"--oneline", f"-{count}")
    return {"output": result["output"]}


def handle_run_tests_real(args: dict) -> dict:
    """
    Run actual test commands in a project directory.
    Captures stdout/stderr and exit code.
    """
    project = os.path.expanduser(args["project_path"])
    command = args.get("test_command", "npm test")
    timeout = args.get("timeout_seconds", 120)
    
    if not os.path.isdir(project):
        return {"output": "", "error": f"Project dir not found: {project}"}
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=project,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        
        output = result.stdout
        if result.stderr:
            output += "\n--- stderr ---\n" + result.stderr
        
        return {
            "output": output,
            "exit_code": result.returncode,
            "success": result.returncode == 0,
            "tests_passed": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"output": "", "error": f"Tests timed out after {timeout}s", "success": False}
    except Exception as e:
        return {"output": "", "error": str(e), "success": False}


def handle_file_snapshot(args: dict) -> dict:
    """
    Capture a before/after snapshot of a file.
    Used by proof packs to show what changed.
    """
    path = os.path.expanduser(args["path"])
    label = args.get("label", "snapshot")
    
    if not os.path.exists(path):
        return {"output": "", "error": f"File not found: {path}"}
    
    with open(path, "r", errors="replace") as f:
        content = f.read()
    
    return {
        "output": content,
        "label": label,
        "path": path,
        "size_bytes": os.path.getsize(path),
        "timestamp": datetime.utcnow().isoformat(),
    }


# Registry
CODING_ROOM_TOOLS = {
    "git_status": handle_git_status,
    "git_create_branch": handle_git_create_branch,
    "git_diff": handle_git_diff,
    "git_add": handle_git_add,
    "git_commit": handle_git_commit,
    "git_log": handle_git_log,
    "run_tests_real": handle_run_tests_real,
    "file_snapshot": handle_file_snapshot,
}
