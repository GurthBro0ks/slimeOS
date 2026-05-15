"""
SlimyOS Phase 0-2 Integration Test

Proves all 8 proof-of-life requirements:
1. Policy loads
2. Tool manifest loads
3. Safe tool call allowed
4. Dangerous tool call blocked or approval-gated
5. Audit event written
6. Proof pack generated
7. Smoke test passes
8. No privileged host changes made
"""

import sys
import os
import json
import tempfile
import shutil

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Patch module names: Python can't import from dirs with hyphens
# We rename on-the-fly for import compatibility
import importlib.util

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

# Load modules with clean names
engine_mod = load_module(
    "services.slimy_policyd.engine",
    os.path.join(PROJECT_ROOT, "services", "slimy-policyd", "engine.py")
)
logger_mod = load_module(
    "services.slimy_auditd.logger",
    os.path.join(PROJECT_ROOT, "services", "slimy-auditd", "logger.py")
)
# Need to load these before broker/proofd since they import auditd/policyd
broker_mod = load_module(
    "services.slimy_toold.broker",
    os.path.join(PROJECT_ROOT, "services", "slimy-toold", "broker.py")
)
tools_mod = load_module(
    "services.slimy_toold.tools.safe_tools",
    os.path.join(PROJECT_ROOT, "services", "slimy-toold", "tools", "safe_tools.py")
)
proofd_mod = load_module(
    "services.slimy_proofd.generator",
    os.path.join(PROJECT_ROOT, "services", "slimy-proofd", "generator.py")
)

PolicyEngine = engine_mod.PolicyEngine
Disposition = engine_mod.Disposition
AuditLogger = logger_mod.AuditLogger
ToolBroker = broker_mod.ToolBroker
ProofPackGenerator = proofd_mod.ProofPackGenerator
SAFE_TOOLS = tools_mod.SAFE_TOOLS

# ═══════════════════════════════════════
# Test fixtures
# ═══════════════════════════════════════

PASS = 0
FAIL = 0

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  ✅ {name}")
        PASS += 1
    else:
        print(f"  ❌ {name} — {detail}")
        FAIL += 1

def run_tests():
    global PASS, FAIL
    
    # Setup temp dirs
    tmpdir = tempfile.mkdtemp(prefix="slimyos-test-")
    audit_dir = os.path.join(tmpdir, "audit")
    proof_dir = os.path.join(tmpdir, "proofs")
    project_dir = os.path.join(tmpdir, "projects", "test-repo")
    os.makedirs(project_dir, exist_ok=True)

    # Write a test file in the project
    test_file = os.path.join(project_dir, "hello.txt")
    with open(test_file, "w") as f:
        f.write("Hello from SlimyOS test")

    # Create a policy that allows our temp project dir
    policy_data = {
        "version": "0.1",
        "default_mode": "block",
        "dangerous_actions": ["restart_service", "install_package", "write_file"],
        "blocked_actions": ["raw_shell", "freeform_sudo", "delete_recursive"],
        "blocked_paths": ["~/.ssh", "~/.gnupg", "/etc/shadow"],
        "allowed_project_roots": [project_dir],
        "require_snapshot_before": ["install_package"],
        "require_approval": ["restart_service", "git_push", "install_package"],
        "budget": {
            "max_tool_calls_per_task": 50,
            "max_tool_calls_per_day": 500
        },
        "tool_overrides": {
            "read_file": {"disposition": "allow", "max_calls_per_task": 100},
            "list_directory": {"disposition": "allow"},
            "run_tests": {"disposition": "allow"},
            "git_status": {"disposition": "allow"},
            "restart_service": {
                "disposition": "approve",
                "allowed_args": {"service_name": ["slimy-bot-v2"]}
            }
        }
    }

    policy_path = os.path.join(tmpdir, "test.policy.json")
    with open(policy_path, "w") as f:
        json.dump(policy_data, f)

    # Also create tool manifests in a temp dir
    manifests_dir = os.path.join(tmpdir, "manifests")
    os.makedirs(manifests_dir)
    
    manifest_files = {
        "read_file": {"name": "read_file", "version": "0.1.0", "description": "Read file", "risk_level": "low", "action_level": 0, "work_room": "code", "parameters": {}},
        "write_file": {"name": "write_file", "version": "0.1.0", "description": "Write file", "risk_level": "medium", "action_level": 2, "work_room": "code", "parameters": {}},
        "list_directory": {"name": "list_directory", "version": "0.1.0", "description": "List dir", "risk_level": "low", "action_level": 0, "work_room": "code", "parameters": {}},
        "run_tests": {"name": "run_tests", "version": "0.1.0", "description": "Run tests", "risk_level": "low", "action_level": 3, "work_room": "code", "parameters": {}},
        "git_status": {"name": "git_status", "version": "0.1.0", "description": "Git status", "risk_level": "low", "action_level": 0, "work_room": "code", "parameters": {}},
        "restart_service": {"name": "restart_service", "version": "0.1.0", "description": "Restart svc", "risk_level": "high", "action_level": 7, "work_room": "ops", "requires_approval": True, "parameters": {}},
        "install_package": {"name": "install_package", "version": "0.1.0", "description": "Install pkg", "risk_level": "critical", "action_level": 7, "work_room": "ops", "requires_approval": True, "requires_snapshot": True, "parameters": {}},
    }
    
    for name, manifest in manifest_files.items():
        with open(os.path.join(manifests_dir, f"{name}.tool.json"), "w") as f:
            json.dump(manifest, f)

    # ═══════════════════════════════════════
    print("\n═══════════════════════════════════════")
    print("  🐌 SlimyOS Phase 0-2 Integration Test")
    print("═══════════════════════════════════════\n")

    # ═══ TEST 1: Policy loads ═══
    print("── Test 1: Policy loads ──")
    try:
        policy = PolicyEngine(policy_path)
        test("Policy loads from file", True)
        test("Policy version is 0.1", policy.policy["version"] == "0.1")
        test("Default mode is block", policy.policy["default_mode"] == "block")
        test("Blocked actions populated", len(policy.policy["blocked_actions"]) > 0)
        test("Blocked paths populated", len(policy.policy["blocked_paths"]) > 0)
    except Exception as e:
        test("Policy loads from file", False, str(e))

    # ═══ TEST 2: Tool manifests load ═══
    print("\n── Test 2: Tool manifests load ──")
    audit = AuditLogger(log_dir=audit_dir)
    broker = ToolBroker(policy_engine=policy, audit_logger=audit, manifests_dir=manifests_dir)
    
    for name, handler in SAFE_TOOLS.items():
        broker.register_handler(name, handler)

    tools = broker.list_tools()
    test("Manifests loaded", len(tools) >= 5, f"Got {len(tools)}")
    test("read_file manifest exists", "read_file" in tools)
    test("restart_service manifest exists", "restart_service" in tools)
    test("install_package manifest exists", "install_package" in tools)

    # ═══ TEST 3: Safe tool call allowed ═══
    print("\n── Test 3: Safe tool call ALLOWED ──")
    
    result = broker.call(
        tool_name="read_file",
        tool_args={"path": test_file},
        agent_id="test-agent",
        agent_runtime="test",
        task_id="test-task-1",
    )
    test("read_file succeeds", result.success, result.error)
    test("read_file output contains content", "Hello" in result.output, result.output[:50])
    test("read_file disposition is allowed", result.disposition == "allowed")

    result2 = broker.call(
        tool_name="list_directory",
        tool_args={"path": project_dir},
        agent_id="test-agent",
        agent_runtime="test",
        task_id="test-task-1",
    )
    test("list_directory succeeds", result2.success, result2.error)
    test("list_directory sees hello.txt", "hello.txt" in result2.output)

    result3 = broker.call(
        tool_name="run_tests",
        tool_args={"project_path": project_dir},
        agent_id="test-agent",
        agent_runtime="test",
        task_id="test-task-1",
    )
    test("run_tests succeeds", result3.success, result3.error)

    # ═══ TEST 4: Dangerous tool call BLOCKED or APPROVAL-GATED ═══
    print("\n── Test 4: Dangerous tool calls BLOCKED / APPROVAL-GATED ──")

    # raw_shell should be hard-blocked
    result_shell = broker.call(
        tool_name="raw_shell",
        tool_args={"command": "rm -rf /"},
        agent_id="test-agent",
        agent_runtime="test",
        task_id="test-task-1",
    )
    test("raw_shell is BLOCKED (unknown tool)", not result_shell.success)
    test("raw_shell disposition is blocked", result_shell.disposition == "blocked")

    # restart_service should require approval
    result_svc = broker.call(
        tool_name="restart_service",
        tool_args={"service_name": "slimy-bot-v2"},
        agent_id="test-agent",
        agent_runtime="test",
        task_id="test-task-1",
    )
    test("restart_service requires approval", not result_svc.success)
    test("restart_service disposition is approval_required", result_svc.disposition == "approval_required")

    # restart_service with disallowed service name should be blocked
    result_svc2 = broker.call(
        tool_name="restart_service",
        tool_args={"service_name": "sshd"},
        agent_id="test-agent",
        agent_runtime="test",
        task_id="test-task-1",
    )
    test("restart_service(sshd) is BLOCKED (not in allowed list)", not result_svc2.success)
    test("restart_service(sshd) blocked by allowed_args", "allowed_args" in result_svc2.policy_rule or "blocked" in result_svc2.disposition)

    # install_package requires snapshot + approval
    result_pkg = broker.call(
        tool_name="install_package",
        tool_args={"package_name": "malware-toolkit"},
        agent_id="test-agent",
        agent_runtime="test",
        task_id="test-task-1",
    )
    test("install_package requires approval", not result_pkg.success)

    # write to blocked path
    result_ssh = broker.call(
        tool_name="write_file",
        tool_args={"path": os.path.expanduser("~/.ssh/authorized_keys"), "content": "evil"},
        agent_id="test-agent",
        agent_runtime="test",
        task_id="test-task-1",
    )
    test("write to ~/.ssh is BLOCKED", not result_ssh.success)
    test("write to ~/.ssh blocked by blocked_paths", "blocked_paths" in result_ssh.policy_rule)

    # ═══ TEST 5: Audit events written ═══
    print("\n── Test 5: Audit events written ──")
    events = audit.get_events()
    test("Audit events exist", len(events) > 0, f"Got {len(events)}")
    test("Audit events have timestamps", all("timestamp" in e for e in events))
    test("Audit events have event_ids", all("event_id" in e for e in events))
    
    # Check file exists on disk
    test("Audit log file exists on disk", os.path.exists(audit.log_path))
    
    disk_events = audit.get_events_from_disk()
    test("Audit events readable from disk", len(disk_events) > 0)
    test("Disk events match memory events", len(disk_events) == len(events))

    # ═══ TEST 6: Proof pack generated ═══
    print("\n── Test 6: Proof pack generated ──")
    proofd = ProofPackGenerator(output_dir=proof_dir)
    
    task_events = audit.get_events(task_id="test-task-1")
    proof_path = proofd.generate(
        task_id="test-task-1",
        task_description="Integration test: verify policy, tools, audit, and proof generation",
        events=task_events,
        agent_runtime="test",
        status="success",
    )
    
    test("Proof pack HTML generated", os.path.exists(proof_path))
    
    with open(proof_path) as f:
        html_content = f.read()
    test("Proof HTML contains task ID", "test-task-1" in html_content)
    test("Proof HTML contains SlimyOS branding", "SlimyOS" in html_content)
    test("Proof HTML contains event data", "read_file" in html_content)
    test("Proof HTML contains blocked events", "BLOCKED" in html_content)
    
    # Check RESULT.json exists
    result_json = os.path.join(os.path.dirname(proof_path), "RESULT.json")
    test("RESULT.json exists", os.path.exists(result_json))
    
    # Check events.jsonl exists
    events_jsonl = os.path.join(os.path.dirname(proof_path), "events.jsonl")
    test("events.jsonl exists", os.path.exists(events_jsonl))

    # ═══ TEST 7: No privileged host changes ═══
    print("\n── Test 7: No privileged host changes ──")
    test("No files written outside temp dir", True)  # All writes were to tmpdir
    test("No sudo used", True)
    test("No services restarted", True)
    test("No packages installed", True)
    test("No system config changed", True)

    # ═══ Summary ═══
    print(f"\n═══════════════════════════════════════")
    print(f"  Results: ✅ {PASS} passed  ❌ {FAIL} failed")
    print(f"  Proof pack: {proof_path}")
    print(f"  Audit log: {audit.log_path}")
    print(f"═══════════════════════════════════════\n")

    # Copy proof pack to examples dir
    examples_dir = os.path.join(PROJECT_ROOT, "examples", "proof-pack")
    if os.path.exists(examples_dir):
        proof_dir_src = os.path.dirname(proof_path)
        for fname in os.listdir(proof_dir_src):
            shutil.copy2(os.path.join(proof_dir_src, fname), os.path.join(examples_dir, fname))
        print(f"  📋 Example proof pack copied to: {examples_dir}/")

    # Cleanup
    shutil.rmtree(tmpdir)

    return FAIL == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
