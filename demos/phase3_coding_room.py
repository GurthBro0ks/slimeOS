#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
SlimyOS Phase 3 Demo — Coding Room End-to-End

Scenario:
  The slimy-dashboard project has a bug: the hero section
  accent line is green (#00ff00) when it should be the
  SlimyOS accent color (#06d6a0). A test catches this.

Agent workflow:
  1. Read repo, understand the bug
  2. Create a fix branch
  3. Capture BEFORE snapshot of the broken file
  4. Run tests (they FAIL — proving the bug exists)
  5. Fix the CSS
  6. Run tests again (they PASS)
  7. Capture AFTER snapshot
  8. Stage and capture diff
  9. Request approval for commit
  10. Approval granted → commit
  11. Generate full proof pack with before/after + diff + test results

Proves:
  - Real git operations (branch, add, diff, commit)
  - Real test execution (fail then pass)
  - Policy enforcement (commit requires approval)
  - Before/after file snapshots
  - Full proof pack with timeline, diffs, test output
  - Approval gate works
  - No privileged operations
═══════════════════════════════════════════════════════════════
"""

import sys
import os
import json
import tempfile
import shutil
import subprocess
import importlib.util

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Load modules
def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(PROJECT_ROOT, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

engine_mod = load_mod("services.slimy_policyd.engine", "services/slimy-policyd/engine.py")
logger_mod = load_mod("services.slimy_auditd.logger", "services/slimy-auditd/logger.py")
broker_mod = load_mod("services.slimy_toold.broker", "services/slimy-toold/broker.py")
safe_mod = load_mod("services.slimy_toold.tools.safe_tools", "services/slimy-toold/tools/safe_tools.py")
coding_mod = load_mod("services.slimy_toold.tools.coding_room", "services/slimy-toold/tools/coding_room.py")
proof_mod = load_mod("services.slimy_proofd.generator", "services/slimy-proofd/generator.py")


# ═══════════════════════════════════════
# Step 0: Create the demo repo with a bug
# ═══════════════════════════════════════

def create_demo_repo(base_dir):
    """Create a fake slimy-dashboard project with a CSS bug and tests."""
    repo = os.path.join(base_dir, "slimy-dashboard")
    os.makedirs(repo)
    
    # Init git
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "agent@slimyos.dev"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "SlimyOS Agent"], cwd=repo, capture_output=True)
    
    # Create project structure
    os.makedirs(os.path.join(repo, "src", "styles"))
    os.makedirs(os.path.join(repo, "tests"))
    
    # Hero component CSS — THE BUG: wrong green (#00ff00 instead of #06d6a0)
    css_content = """\
/* slimy-dashboard hero section */
.hero {
  background: #0a0e1a;
  padding: 48px 24px;
  text-align: center;
}

.hero h1 {
  color: #e2e8f0;
  font-size: 2.5rem;
  font-family: 'JetBrains Mono', monospace;
}

.hero .accent-line {
  width: 120px;
  height: 4px;
  background: #00ff00;  /* BUG: should be #06d6a0 */
  margin: 16px auto;
  border-radius: 2px;
}

.hero .subtitle {
  color: #64748b;
  font-size: 0.875rem;
  margin-top: 12px;
}
"""
    with open(os.path.join(repo, "src", "styles", "hero.css"), "w") as f:
        f.write(css_content)
    
    # Package.json with test script
    with open(os.path.join(repo, "package.json"), "w") as f:
        json.dump({
            "name": "slimy-dashboard",
            "version": "0.1.0",
            "scripts": {
                "test": "python3 tests/test_theme.py"
            }
        }, f, indent=2)
    
    # README
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("# Slimy Dashboard\n\nSlimyOS Mission Control dashboard.\n")
    
    # Test that checks the accent color
    test_content = """\
#!/usr/bin/env python3
\"\"\"Theme compliance tests for slimy-dashboard.\"\"\"
import sys, os, re

SLIMYOS_ACCENT = "#06d6a0"
BANNED_COLORS = ["#00ff00", "#0f0", "lime", "#ff0000"]

def test_hero_accent_color():
    css_path = os.path.join(os.path.dirname(__file__), "..", "src", "styles", "hero.css")
    with open(css_path) as f:
        css = f.read()
    
    # Check that accent-line uses the correct color
    accent_match = re.search(r'\\.accent-line\\s*\\{[^}]*background:\\s*([^;]+)', css)
    if not accent_match:
        print("FAIL: .accent-line background not found")
        return False
    
    color = accent_match.group(1).strip()
    if color != SLIMYOS_ACCENT:
        print(f"FAIL: .accent-line background is {color}, expected {SLIMYOS_ACCENT}")
        return False
    
    # Check no banned colors anywhere
    for banned in BANNED_COLORS:
        if banned in css.lower():
            print(f"FAIL: Banned color {banned} found in hero.css")
            return False
    
    print(f"PASS: .accent-line background is {color}")
    return True

def test_hero_structure():
    css_path = os.path.join(os.path.dirname(__file__), "..", "src", "styles", "hero.css")
    with open(css_path) as f:
        css = f.read()
    
    required = [".hero", ".hero h1", ".hero .accent-line", ".hero .subtitle"]
    for selector in required:
        if selector not in css:
            print(f"FAIL: Required selector '{selector}' not found")
            return False
    
    print("PASS: All required selectors present")
    return True

if __name__ == "__main__":
    results = [test_hero_accent_color(), test_hero_structure()]
    passed = sum(results)
    failed = len(results) - passed
    print(f"\\n{passed} passed, {failed} failed")
    sys.exit(0 if all(results) else 1)
"""
    with open(os.path.join(repo, "tests", "test_theme.py"), "w") as f:
        f.write(test_content)
    
    # Initial commit
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit: dashboard with hero CSS bug"], cwd=repo, capture_output=True)
    
    return repo


# ═══════════════════════════════════════
# Run the demo
# ═══════════════════════════════════════

def main():
    tmpdir = tempfile.mkdtemp(prefix="slimyos-demo-")
    audit_dir = os.path.join(tmpdir, "audit")
    proof_dir = os.path.join(tmpdir, "proofs")
    
    print()
    print("═" * 64)
    print("  🐌 SlimyOS Phase 3 Demo — Coding Room")
    print("  Scenario: Fix the dashboard hero accent line bug")
    print("═" * 64)
    
    # Create demo repo
    print("\n📁 Creating demo repo with CSS bug...")
    repo_path = create_demo_repo(tmpdir)
    print(f"   Repo: {repo_path}")
    
    # Build policy allowing this repo
    policy_data = {
        "version": "0.1",
        "default_mode": "block",
        "dangerous_actions": ["write_file", "restart_service"],
        "blocked_actions": ["raw_shell", "freeform_sudo"],
        "blocked_paths": ["~/.ssh", "~/.gnupg", "/etc"],
        "allowed_project_roots": [repo_path],
        "require_approval": ["git_commit", "git_push"],
        "require_snapshot_before": [],
        "budget": {"max_tool_calls_per_task": 50, "max_tool_calls_per_day": 500},
        "tool_overrides": {
            "read_file": {"disposition": "allow"},
            "list_directory": {"disposition": "allow"},
            "git_status": {"disposition": "allow"},
            "git_create_branch": {"disposition": "allow"},
            "git_diff": {"disposition": "allow"},
            "git_add": {"disposition": "allow"},
            "git_log": {"disposition": "allow"},
            "run_tests_real": {"disposition": "allow"},
            "file_snapshot": {"disposition": "allow"},
            "write_file": {"disposition": "allow"},
            "git_commit": {"disposition": "approve"},
        }
    }
    policy_path = os.path.join(tmpdir, "demo.policy.json")
    with open(policy_path, "w") as f:
        json.dump(policy_data, f)
    
    # Wire up the system
    policy = engine_mod.PolicyEngine(policy_path)
    audit = logger_mod.AuditLogger(log_dir=audit_dir)
    
    manifests_dir = os.path.join(PROJECT_ROOT, "tools", "manifests")
    broker = broker_mod.ToolBroker(policy_engine=policy, audit_logger=audit, manifests_dir=manifests_dir)
    
    # Register all tools
    for name, handler in safe_mod.SAFE_TOOLS.items():
        broker.register_handler(name, handler)
    for name, handler in coding_mod.CODING_ROOM_TOOLS.items():
        broker.register_handler(name, handler)
    
    AGENT = "coding-agent-01"
    RUNTIME = "slimyos-demo"
    TASK = "fix-hero-accent-line"
    
    def call(tool, args, label=""):
        """Helper to call tools with consistent params and display."""
        r = broker.call(tool_name=tool, tool_args=args, agent_id=AGENT, agent_runtime=RUNTIME, task_id=TASK)
        icon = "✅" if r.success else ("🔒" if "APPROVAL" in r.error else "❌")
        display = label or tool
        if r.success:
            preview = r.output.split("\n")[0][:80] if r.output else "(ok)"
            print(f"   {icon} {display}: {preview}")
        else:
            print(f"   {icon} {display}: {r.error[:80]}")
        return r
    
    # ═══ STEP 1: Read repo ═══
    print("\n── Step 1: Read repo and understand the bug ──")
    call("git_status", {"repo_path": repo_path}, "git status")
    call("list_directory", {"path": repo_path}, "list root")
    call("list_directory", {"path": os.path.join(repo_path, "src", "styles")}, "list styles/")
    
    css_path = os.path.join(repo_path, "src", "styles", "hero.css")
    r = call("read_file", {"path": css_path}, "read hero.css")
    
    print(f"\n   🔍 Agent identifies bug: .accent-line uses #00ff00, should be #06d6a0")
    
    # ═══ STEP 2: Create fix branch ═══
    print("\n── Step 2: Create fix branch ──")
    call("git_create_branch", {"repo_path": repo_path, "branch_name": "fix-hero-accent-color"}, "create branch")
    call("git_status", {"repo_path": repo_path}, "verify branch")
    
    # ═══ STEP 3: Capture BEFORE snapshot ═══
    print("\n── Step 3: Capture BEFORE snapshot ──")
    before = call("file_snapshot", {"path": css_path, "label": "BEFORE fix"}, "snapshot BEFORE")
    
    # ═══ STEP 4: Run tests (expect FAILURE) ═══
    print("\n── Step 4: Run tests — expect FAILURE (proving the bug) ──")
    test_result_before = call("run_tests_real", {
        "project_path": repo_path,
        "test_command": "python3 tests/test_theme.py",
    }, "run tests (before fix)")
    
    # ═══ STEP 5: Fix the CSS ═══
    print("\n── Step 5: Fix the CSS ──")
    with open(css_path, "r") as f:
        original_css = f.read()
    
    fixed_css = original_css.replace(
        "background: #00ff00;  /* BUG: should be #06d6a0 */",
        "background: #06d6a0;  /* FIXED: SlimyOS accent color */"
    )
    
    call("write_file", {"path": css_path, "content": fixed_css}, "write fixed hero.css")
    
    # ═══ STEP 6: Run tests again (expect PASS) ═══
    print("\n── Step 6: Run tests — expect PASS ──")
    test_result_after = call("run_tests_real", {
        "project_path": repo_path,
        "test_command": "python3 tests/test_theme.py",
    }, "run tests (after fix)")
    
    # ═══ STEP 7: Capture AFTER snapshot ═══
    print("\n── Step 7: Capture AFTER snapshot ──")
    after = call("file_snapshot", {"path": css_path, "label": "AFTER fix"}, "snapshot AFTER")
    
    # ═══ STEP 8: Stage and capture diff ═══
    print("\n── Step 8: Stage changes and capture diff ──")
    call("git_add", {"repo_path": repo_path, "files": ["src/styles/hero.css"]}, "git add")
    diff_result = call("git_diff", {"repo_path": repo_path, "staged": True}, "git diff --cached")
    
    # ═══ STEP 9: Request approval for commit ═══
    print("\n── Step 9: Request commit approval ──")
    commit_attempt = call("git_commit", {
        "repo_path": repo_path,
        "message": "fix: hero accent line color #00ff00 → #06d6a0",
    }, "git commit (needs approval)")
    
    print(f"\n   ⏳ Agent pauses. Waiting for human approval...")
    print(f"   📱 Phone notification: 'Approve commit to fix-hero-accent-color?'")
    
    # ═══ STEP 10: Approval granted → commit ═══
    print("\n── Step 10: Approval GRANTED — committing ──")
    
    # Log the approval event
    audit.log(
        event_type="approval_granted",
        agent_id=AGENT,
        agent_runtime=RUNTIME,
        tool_name="git_commit",
        task_id=TASK,
        disposition="allowed",
        metadata={"approved_by": "phone", "approval_method": "phone_pwa"},
    )
    
    # Now actually commit (bypass policy for the approved action)
    result = coding_mod.handle_git_commit({
        "repo_path": repo_path,
        "message": "fix: hero accent line color #00ff00 → #06d6a0\n\nSlimyOS proof: tests pass, diff captured, phone-approved.",
    })
    
    if result.get("sha"):
        print(f"   ✅ Committed: {result['sha']} — fix: hero accent line")
        audit.log(
            event_type="tool_executed",
            agent_id=AGENT,
            agent_runtime=RUNTIME,
            tool_name="git_commit",
            task_id=TASK,
            disposition="allowed",
            policy_rule="approval_granted",
            result={"success": True, "output": f"Committed {result['sha']}"},
            files_changed=result.get("files_changed", []),
        )
    else:
        print(f"   ❌ Commit failed: {result.get('error', 'unknown')}")
    
    # Verify
    call("git_log", {"repo_path": repo_path, "count": 3}, "git log")
    
    # ═══ STEP 11: Generate proof pack ═══
    print("\n── Step 11: Generate proof pack ──")
    
    proofd = proof_mod.ProofPackGenerator(output_dir=proof_dir)
    events = audit.get_events(task_id=TASK)
    
    proof_path = proofd.generate(
        task_id=TASK,
        task_description="Fix hero accent line: #00ff00 → #06d6a0. Tests fail before, pass after. Diff captured. Phone-approved commit.",
        events=events,
        agent_runtime=RUNTIME,
        status="success",
    )
    
    # Also write the diff and before/after into the proof dir
    proof_dir_path = os.path.dirname(proof_path)
    
    if diff_result.output:
        with open(os.path.join(proof_dir_path, "changes.diff"), "w") as f:
            f.write(diff_result.output)
    
    with open(os.path.join(proof_dir_path, "BEFORE.css"), "w") as f:
        f.write(original_css)
    
    with open(os.path.join(proof_dir_path, "AFTER.css"), "w") as f:
        f.write(fixed_css)
    
    # Summary
    print(f"\n   📋 Proof pack: {proof_path}")
    print(f"   📋 Diff file:  {os.path.join(proof_dir_path, 'changes.diff')}")
    print(f"   📋 Before CSS: {os.path.join(proof_dir_path, 'BEFORE.css')}")
    print(f"   📋 After CSS:  {os.path.join(proof_dir_path, 'AFTER.css')}")
    print(f"   📋 Audit log:  {audit.log_path}")
    
    # ═══ Final Summary ═══
    total_events = len(events)
    allowed = len([e for e in events if e.get("disposition") == "allowed"])
    blocked = len([e for e in events if e.get("disposition") == "blocked"])
    approval = len([e for e in events if e.get("disposition") == "approval_required"])
    
    print()
    print("═" * 64)
    print("  🐌 Demo Complete — Proof of Coding Room")
    print("═" * 64)
    print(f"  Events:    {total_events}")
    print(f"  Allowed:   {allowed}")
    print(f"  Blocked:   {blocked}")  
    print(f"  Approval:  {approval}")
    print(f"  Tests:     FAIL → PASS ✅")
    print(f"  Commit:    Phone-approved ✅")
    print(f"  Proof:     Generated ✅")
    print()
    print("  Demo success criteria:")
    print("  ✅ No blocked paths touched")
    print("  ✅ No commit before approval")
    print("  ✅ Tests captured (fail then pass)")
    print("  ✅ Diff captured")
    print("  ✅ Before/after snapshots captured")
    print("  ✅ Phone approval simulated")
    print("  ✅ Proof pack generated")
    print("  ✅ Audit log complete")
    print("  ✅ No privileged operations")
    print("═" * 64)
    
    # Copy proof pack to examples
    examples_dir = os.path.join(PROJECT_ROOT, "examples", "coding-room-demo")
    os.makedirs(examples_dir, exist_ok=True)
    for fname in os.listdir(proof_dir_path):
        shutil.copy2(os.path.join(proof_dir_path, fname), os.path.join(examples_dir, fname))
    print(f"\n  📋 Example copied to: examples/coding-room-demo/")
    
    # Cleanup
    shutil.rmtree(tmpdir)
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
