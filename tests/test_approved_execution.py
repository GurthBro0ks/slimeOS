import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import importlib.util


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def _load_module(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(PROJECT_ROOT, relpath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


engine_mod = _load_module("services.slimy_policyd.engine", "services/slimy-policyd/engine.py")
logger_mod = _load_module("services.slimy_auditd.logger", "services/slimy-auditd/logger.py")
broker_mod = _load_module("services.slimy_toold.broker", "services/slimy-toold/broker.py")
coding_mod = _load_module("services.slimy_toold.tools.coding_room", "services/slimy-toold/tools/coding_room.py")

PolicyEngine = engine_mod.PolicyEngine
AuditLogger = logger_mod.AuditLogger
ToolBroker = broker_mod.ToolBroker


class ApprovedExecutionTests(unittest.TestCase):
    def setUp(self):
        self.lane_tmp = tempfile.TemporaryDirectory(prefix="proof_slimyos_approved_execution_test_")
        self.lane_root = self.lane_tmp.name
        self.repo_path = os.path.join(self.lane_root, "demo_repo")
        self.audit_dir = os.path.join(self.lane_root, "audit")
        self.manifests_dir = os.path.join(self.lane_root, "manifests")
        self.outside_root = tempfile.mkdtemp(prefix="outside_exec_repo_")
        self.outside_repo = os.path.join(self.outside_root, "repo")

        os.makedirs(self.manifests_dir, exist_ok=True)

        self._init_git_repo(self.repo_path)
        self._init_git_repo(self.outside_repo)

        policy_path = os.path.join(self.lane_root, "policy.json")
        policy_data = {
            "version": "0.1",
            "default_mode": "block",
            "dangerous_actions": ["restart_service"],
            "blocked_actions": ["raw_shell"],
            "blocked_paths": ["~/.ssh"],
            "allowed_project_roots": [self.lane_root, self.outside_root],
            "require_snapshot_before": [],
            "require_approval": ["git_commit", "restart_service"],
            "budget": {
                "max_tool_calls_per_task": 100,
                "max_tool_calls_per_day": 500,
            },
            "tool_overrides": {},
        }
        with open(policy_path, "w", encoding="utf-8") as handle:
            json.dump(policy_data, handle)

        manifests = {
            "git_commit": {
                "name": "git_commit",
                "version": "0.1.0",
                "description": "Commit staged changes.",
                "risk_level": "medium",
                "action_level": 2,
                "work_room": "code",
                "requires_approval": True,
                "parameters": {"type": "object", "required": ["repo_path", "message"]},
            },
            "restart_service": {
                "name": "restart_service",
                "version": "0.1.0",
                "description": "Restart service.",
                "risk_level": "high",
                "action_level": 7,
                "work_room": "ops",
                "requires_approval": True,
                "parameters": {"type": "object", "required": ["service_name"]},
            },
        }
        for name, payload in manifests.items():
            with open(os.path.join(self.manifests_dir, f"{name}.tool.json"), "w", encoding="utf-8") as handle:
                json.dump(payload, handle)

        self.policy = PolicyEngine(policy_path)
        self.audit = AuditLogger(log_dir=self.audit_dir)
        self.broker = ToolBroker(
            policy_engine=self.policy,
            audit_logger=self.audit,
            manifests_dir=self.manifests_dir,
        )
        self.broker.register_handler("git_commit", coding_mod.handle_git_commit)
        self.broker.register_handler("restart_service", lambda _args: {"output": "should_not_run"})

    def tearDown(self):
        self.lane_tmp.cleanup()
        shutil.rmtree(self.outside_root, ignore_errors=True)

    @staticmethod
    def _run(command: list[str], cwd: str):
        return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)

    def _init_git_repo(self, path: str):
        os.makedirs(path, exist_ok=True)
        self._run(["git", "init"], cwd=path)
        self._run(["git", "config", "user.email", "slimyos-test@example.local"], cwd=path)
        self._run(["git", "config", "user.name", "SlimyOS Test"], cwd=path)
        with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as handle:
            handle.write("demo\n")
        self._run(["git", "add", "README.md"], cwd=path)
        self._run(["git", "commit", "-m", "initial"], cwd=path)

    def _stage_change(self, repo_path: str, filename: str = "demo.txt"):
        with open(os.path.join(repo_path, filename), "a", encoding="utf-8") as handle:
            handle.write("change\n")
        self._run(["git", "add", filename], cwd=repo_path)

    def _request_approval(self, tool_name: str, tool_args: dict, request_id: str = "req-1") -> str:
        result = self.broker.call(
            tool_name=tool_name,
            tool_args=tool_args,
            agent_id="claude_desktop",
            agent_runtime="mcp-stdio",
            task_id="approved-exec-task",
            client_identity={
                "client_id": "claude_desktop",
                "client_name": "Claude Desktop",
                "transport": "mcp_stdio",
                "request_id": request_id,
            },
        )
        self.assertEqual(result.disposition, "approval_required")
        self.assertTrue(result.approval_id)
        return result.approval_id

    def _approve(self, approval_id: str):
        decision = self.broker.decide_approval(approval_id, approved=True, decided_by="tester")
        self.assertIsNotNone(decision)
        self.assertEqual(decision["status"], "approved")

    def _head(self, repo_path: str) -> str:
        return self._run(["git", "rev-parse", "HEAD"], cwd=repo_path).stdout.strip()

    def test_refuses_missing_approval_id(self):
        result = self.broker.execute_approved("", confirm="execute-approved-test-lane")
        self.assertFalse(result["ok"])
        self.assertIn("missing_approval_id", result["error"])

    def test_refuses_unknown_approval_id(self):
        result = self.broker.execute_approved("missing", confirm="execute-approved-test-lane")
        self.assertFalse(result["ok"])
        self.assertIn("unknown_approval_id", result["error"])

    def test_refuses_denied_approval(self):
        self._stage_change(self.repo_path)
        approval_id = self._request_approval("git_commit", {"repo_path": self.repo_path, "message": "demo commit"})
        deny = self.broker.decide_approval(approval_id, approved=False, decided_by="tester")
        self.assertEqual(deny["status"], "denied")

        result = self.broker.execute_approved(approval_id, confirm="execute-approved-test-lane")
        self.assertFalse(result["ok"])
        self.assertIn("approval_not_executable_status:denied", result["error"])

    def test_refuses_already_executed_approval(self):
        self._stage_change(self.repo_path)
        approval_id = self._request_approval("git_commit", {"repo_path": self.repo_path, "message": "demo commit"})
        self._approve(approval_id)

        first = self.broker.execute_approved(approval_id, confirm="execute-approved-test-lane")
        self.assertTrue(first["ok"])

        second = self.broker.execute_approved(approval_id, confirm="execute-approved-test-lane")
        self.assertFalse(second["ok"])
        self.assertIn("already_used", second["error"])

    def test_refuses_unsafe_tool(self):
        approval_id = self._request_approval("restart_service", {"service_name": "sshd"}, request_id="req-unsafe")
        self._approve(approval_id)
        result = self.broker.execute_approved(approval_id, confirm="execute-approved-test-lane")
        self.assertFalse(result["ok"])
        self.assertIn("tool_not_in_approved_execution_allowlist", result["error"])

    def test_refuses_path_outside_test_lane(self):
        self._stage_change(self.outside_repo)
        approval_id = self._request_approval("git_commit", {"repo_path": self.outside_repo, "message": "outside"}, request_id="req-outside")
        self._approve(approval_id)

        result = self.broker.execute_approved(approval_id, confirm="execute-approved-test-lane")
        self.assertFalse(result["ok"])
        self.assertIn("repo_outside_test_lane", result["error"])

    def test_refuses_args_mismatch(self):
        self._stage_change(self.repo_path)
        approval_id = self._request_approval("git_commit", {"repo_path": self.repo_path, "message": "expected"}, request_id="req-args")
        self._approve(approval_id)

        mismatch_args = {"repo_path": self.repo_path, "message": "different"}
        result = self.broker.execute_approved(
            approval_id,
            confirm="execute-approved-test-lane",
            caller_args=mismatch_args,
        )
        self.assertFalse(result["ok"])
        self.assertIn("args_mismatch", result["error"])

    def test_executes_git_commit_only_in_demo_lane(self):
        self._stage_change(self.repo_path)
        head_before = self._head(self.repo_path)
        approval_id = self._request_approval(
            "git_commit",
            {
                "repo_path": self.repo_path,
                "message": "approved demo commit",
                "chat_text": "do not store this",
            },
            request_id="req-exec",
        )
        self._approve(approval_id)

        result = self.broker.execute_approved(approval_id, confirm="execute-approved-test-lane")
        self.assertTrue(result["ok"], result)

        head_after = self._head(self.repo_path)
        self.assertNotEqual(head_before, head_after)

        approval = result["approval"]
        self.assertEqual(approval["execution_status"], "executed")
        self.assertTrue(approval["used"])
        self.assertTrue(approval["execution_audit_event_id"])
        self.assertTrue(approval["execution_proof_ref"])

    def test_records_execution_audit_events(self):
        self._stage_change(self.repo_path)
        approval_id = self._request_approval("git_commit", {"repo_path": self.repo_path, "message": "audit"}, request_id="req-audit")
        self._approve(approval_id)

        self.broker.execute_approved(approval_id, confirm="execute-approved-test-lane")
        events = self.audit.get_events()
        event_types = [e.get("event_type") for e in events]
        self.assertIn("approval_execution_start", event_types)
        self.assertIn("approval_execution_finish", event_types)

    def test_no_chat_text_stored_and_raw_shell_blocked(self):
        self._stage_change(self.repo_path)
        approval_id = self._request_approval(
            "git_commit",
            {
                "repo_path": self.repo_path,
                "message": "privacy",
                "chat_text": "private chat content",
            },
            request_id="req-privacy",
        )
        self._approve(approval_id)
        self.broker.execute_approved(approval_id, confirm="execute-approved-test-lane")

        events_blob = json.dumps(self.audit.get_events()).lower()
        self.assertNotIn("private chat content", events_blob)

        blocked = self.broker.call(
            tool_name="raw_shell",
            tool_args={"command": "rm -rf /"},
            agent_id="claude_desktop",
            agent_runtime="mcp-stdio",
            task_id="approved-exec-task",
        )
        self.assertFalse(blocked.success)
        self.assertEqual(blocked.disposition, "blocked")


if __name__ == "__main__":
    unittest.main()
