#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
SlimyOS Phases 4-7 Integration Demo

Proves:
  Phase 4 — Browser Room: search allowed, submit blocked, purchase blocked
  Phase 5 — Sandbox Room: sandbox create/exec/destroy
  Phase 6 — Mission Control: hub state, task tracking, event stream
  Phase 7 — Phone Supervisor: approval flow (approve + deny)
═══════════════════════════════════════════════════════════════
"""

import sys, os, json, tempfile, shutil, importlib.util

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(PROJECT_ROOT, path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

engine_mod = load_mod("services.slimy_policyd.engine", "services/slimy-policyd/engine.py")
logger_mod = load_mod("services.slimy_auditd.logger", "services/slimy-auditd/logger.py")
broker_mod = load_mod("services.slimy_toold.broker", "services/slimy-toold/broker.py")
safe_mod   = load_mod("services.slimy_toold.tools.safe_tools", "services/slimy-toold/tools/safe_tools.py")
coding_mod = load_mod("services.slimy_toold.tools.coding_room", "services/slimy-toold/tools/coding_room.py")
browser_mod= load_mod("services.slimy_toold.tools.browser_room", "services/slimy-toold/tools/browser_room.py")
sandbox_mod= load_mod("services.slimy_toold.tools.sandbox_room", "services/slimy-toold/tools/sandbox_room.py")
proof_mod  = load_mod("services.slimy_proofd.generator", "services/slimy-proofd/generator.py")
hub_mod    = load_mod("services.slimy_hub", "services/slimy-hub/__init__.py")

PASS = 0; FAIL = 0

def test(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  ✅ {name}"); PASS += 1
    else:
        print(f"  ❌ {name} — {detail}"); FAIL += 1

def main():
    global PASS, FAIL
    tmpdir = tempfile.mkdtemp(prefix="slimyos-phase47-")
    audit_dir = os.path.join(tmpdir, "audit")
    proof_dir = os.path.join(tmpdir, "proofs")

    print()
    print("═" * 64)
    print("  🐌 SlimyOS Phases 4-7 Integration Demo")
    print("═" * 64)

    # ═══ Setup ═══
    policy_data = {
        "version": "0.1", "default_mode": "block",
        "dangerous_actions": ["browser_submit", "browser_purchase"],
        "blocked_actions": ["raw_shell", "freeform_sudo"],
        "blocked_paths": ["~/.ssh"], "allowed_project_roots": [tmpdir],
        "require_approval": ["browser_submit", "browser_purchase", "sandbox_exec"],
        "require_snapshot_before": [],
        "budget": {"max_tool_calls_per_task": 100, "max_tool_calls_per_day": 500},
        "tool_overrides": {
            "browser_search": {"disposition": "allow"},
            "browser_read_page": {"disposition": "allow"},
            "browser_screenshot": {"disposition": "allow"},
            "browser_navigate": {"disposition": "allow"},
            "browser_click": {"disposition": "allow"},
            "browser_fill_form": {"disposition": "allow"},
            "browser_submit": {"disposition": "approve"},
            "browser_purchase": {"disposition": "approve"},
            "sandbox_create": {"disposition": "allow"},
            "sandbox_exec": {"disposition": "approve"},
            "sandbox_destroy": {"disposition": "allow"},
            "sandbox_copy_out": {"disposition": "allow"},
            "read_file": {"disposition": "allow"},
            "list_directory": {"disposition": "allow"},
        }
    }
    policy_path = os.path.join(tmpdir, "policy.json")
    with open(policy_path, "w") as f:
        json.dump(policy_data, f)

    policy = engine_mod.PolicyEngine(policy_path)
    audit = logger_mod.AuditLogger(log_dir=audit_dir)
    broker = broker_mod.ToolBroker(policy_engine=policy, audit_logger=audit,
                                   manifests_dir=os.path.join(PROJECT_ROOT, "tools", "manifests"))
    
    for name, handler in {**safe_mod.SAFE_TOOLS, **browser_mod.BROWSER_ROOM_TOOLS, **sandbox_mod.SANDBOX_ROOM_TOOLS}.items():
        broker.register_handler(name, handler)

    hub = hub_mod.Hub()
    AGENT = "research-agent-01"
    TASK = "research-hyprland-compat"

    def call(tool, args, label=""):
        r = broker.call(tool_name=tool, tool_args=args, agent_id=AGENT, agent_runtime="hermes", task_id=TASK)
        icon = "✅" if r.success else ("🔒" if "APPROVAL" in (r.error or "") else "❌")
        print(f"   {icon} {label or tool}: {(r.output or r.error or '(ok)')[:80]}")
        return r

    # ═══ PHASE 4: Browser Room ═══
    print("\n╔══ PHASE 4: Browser Room ══╗")
    
    hub.register_agent(AGENT, "hermes")
    hub.create_task(TASK, "Research Hyprland v0.53 compatibility for SlimyOS", AGENT, "hermes", "browser")

    print("\n── Safe browser ops (allowed) ──")
    r = call("browser_search", {"query": "Hyprland v0.53 breaking changes"})
    test("browser_search allowed", r.success)
    
    r = call("browser_navigate", {"url": "https://github.com/hyprwm/Hyprland/releases"})
    test("browser_navigate allowed", r.success)
    
    r = call("browser_read_page", {"url": "https://wiki.hyprland.org/Configuring/", "extract": "text"})
    test("browser_read_page allowed", r.success)
    
    r = call("browser_screenshot", {"label": "hyprland-releases-page"})
    test("browser_screenshot allowed", r.success)
    
    r = call("browser_fill_form", {"field_name": "search", "value": "ydotool compatibility"})
    test("browser_fill_form allowed (draft only)", r.success)

    print("\n── Dangerous browser ops (approval-gated) ──")
    r = call("browser_submit", {"url": "https://github.com/issues/new", "form_id": "issue-form"})
    test("browser_submit requires approval", not r.success and r.disposition == "approval_required")
    
    r = call("browser_purchase", {"url": "https://amazon.com", "item": "USB hub", "amount": "$29.99"})
    test("browser_purchase requires approval", not r.success and r.disposition == "approval_required")

    # ═══ PHASE 5: Sandbox Room ═══
    print("\n╔══ PHASE 5: Sandbox Room ══╗")
    
    print("\n── Sandbox lifecycle ──")
    r = call("sandbox_create", {"sandbox_id": "test-sandbox", "image": "ubuntu:22.04", "network": "none"})
    test("sandbox_create allowed", r.success)
    
    r = call("sandbox_exec", {"sandbox_id": "test-sandbox", "command": "echo hello from sandbox"})
    test("sandbox_exec requires approval", not r.success and r.disposition == "approval_required")
    
    r = call("sandbox_destroy", {"sandbox_id": "test-sandbox"})
    test("sandbox_destroy allowed (cleanup)", r.success)

    # ═══ PHASE 6: Mission Control Hub ═══
    print("\n╔══ PHASE 6: Mission Control Hub ══╗")
    
    print("\n── Hub state tracking ──")
    snapshot = hub.snapshot()
    test("Hub has agents", snapshot["stats"]["total_agents"] > 0)
    test("Hub has tasks", snapshot["stats"]["total_tasks"] > 0)
    test("Hub tracks running task", snapshot["stats"]["running"] > 0)
    
    hub.update_task(TASK, tool_calls=15, current_tool="browser_read_page")
    task = hub.get_task(TASK)
    test("Task tool_calls tracked", task.tool_calls == 15)
    test("Task current_tool tracked", task.current_tool == "browser_read_page")

    print("\n── Approval queue ──")
    req = hub.request_approval(TASK, AGENT, "browser_submit",
        {"url": "https://github.com/issues/new"}, "Form submit requires approval", "high")
    test("Approval request created", req.status == "pending")
    test("Pending approvals visible", len(hub.get_pending_approvals()) > 0)
    
    snapshot = hub.snapshot()
    test("Snapshot shows pending approvals", snapshot["stats"]["pending_approvals"] > 0)

    print("\n── Event stream ──")
    events = hub.get_recent_events()
    test("Events recorded", len(events) > 0)
    test("Events have timestamps", all("timestamp" in e for e in events))
    test("Events have types", all("type" in e for e in events))

    # ═══ PHASE 7: Phone Approval Flow ═══
    print("\n╔══ PHASE 7: Phone Approval Flow ══╗")
    
    print("\n── Approve from phone ──")
    decided = hub.decide_approval(req.request_id, approved=True, decided_by="phone_pwa")
    test("Approval granted via phone", decided.status == "approved")
    test("Decided_by records phone", decided.decided_by == "phone_pwa")
    test("Task resumed after approval", hub.get_task(TASK).state.value == "running")
    test("No more pending after decision", len(hub.get_pending_approvals()) == 0)

    print("\n── Deny from phone ──")
    req2 = hub.request_approval(TASK, AGENT, "browser_purchase",
        {"item": "USB hub", "amount": "$29.99"}, "Purchase requires approval", "critical")
    denied = hub.decide_approval(req2.request_id, approved=False, decided_by="phone_pwa")
    test("Denial works", denied.status == "denied")

    print("\n── Panic stop from phone ──")
    hub.panic_stop("Phone panic button pressed")
    test("Panic activates", hub.is_panicked)
    test("Tasks panicked", hub.get_task(TASK).state.value == "panicked")
    
    snapshot = hub.snapshot()
    test("Snapshot shows panicked", snapshot["panicked"] is True)
    
    hub.resume()
    test("Resume works", not hub.is_panicked)

    # ═══ Proof Pack ═══
    print("\n╔══ Proof Pack Generation ══╗")
    
    proofd = proof_mod.ProofPackGenerator(output_dir=proof_dir)
    all_events = audit.get_events(task_id=TASK)
    proof_path = proofd.generate(
        task_id=TASK,
        task_description="Research Hyprland v0.53 compatibility. Browser search allowed, form submit gated, purchase denied.",
        events=all_events,
        agent_runtime="hermes",
        status="success",
    )
    test("Proof pack generated", os.path.exists(proof_path))

    # Copy to examples
    examples_dir = os.path.join(PROJECT_ROOT, "examples", "browser-room-demo")
    os.makedirs(examples_dir, exist_ok=True)
    for fname in os.listdir(os.path.dirname(proof_path)):
        shutil.copy2(os.path.join(os.path.dirname(proof_path), fname), os.path.join(examples_dir, fname))

    # ═══ Summary ═══
    print()
    print("═" * 64)
    print(f"  🐌 Phases 4-7 Complete")
    print("═" * 64)
    print(f"  ✅ {PASS} passed  ❌ {FAIL} failed")
    print(f"  Proof: {proof_path}")
    print(f"  Audit: {audit.log_path}")
    print()
    print("  Phase 4 — Browser Room:")
    print("    ✅ Search, navigate, read, screenshot, fill form: allowed")
    print("    ✅ Submit, purchase: approval-gated")
    print()
    print("  Phase 5 — Sandbox Room:")
    print("    ✅ Create/destroy: allowed")
    print("    ✅ Exec inside sandbox: approval-gated")
    print()
    print("  Phase 6 — Mission Control:")
    print("    ✅ Hub tracks agents, tasks, tool calls, current tool")
    print("    ✅ Approval queue with pending/decided states")
    print("    ✅ Event stream with timestamps")
    print("    ✅ Full state snapshot for dashboard rendering")
    print()
    print("  Phase 7 — Phone Supervisor:")
    print("    ✅ Approve from phone → task resumes")
    print("    ✅ Deny from phone → action rejected")
    print("    ✅ Panic from phone → all agents halted")
    print("    ✅ Resume → agents can continue")
    print("═" * 64)

    shutil.rmtree(tmpdir)
    return FAIL == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
