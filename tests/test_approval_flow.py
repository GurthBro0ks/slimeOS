import json
import os
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

PolicyEngine = engine_mod.PolicyEngine
AuditLogger = logger_mod.AuditLogger
ToolBroker = broker_mod.ToolBroker


class ApprovalFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = self.tmpdir.name
        self.repo_path = os.path.join(self.root, "repo")
        self.manifests_dir = os.path.join(self.root, "manifests")
        self.audit_dir = os.path.join(self.root, "audit")
        os.makedirs(self.repo_path, exist_ok=True)
        os.makedirs(self.manifests_dir, exist_ok=True)

        policy_path = os.path.join(self.root, "policy.json")
        policy_data = {
            "version": "0.1",
            "default_mode": "block",
            "dangerous_actions": ["restart_service"],
            "blocked_actions": ["raw_shell"],
            "blocked_paths": ["~/.ssh"],
            "allowed_project_roots": [self.repo_path],
            "require_snapshot_before": [],
            "require_approval": ["git_commit"],
            "budget": {
                "max_tool_calls_per_task": 100,
                "max_tool_calls_per_day": 500,
            },
            "tool_overrides": {
                "read_file": {"disposition": "allow"},
            },
        }
        with open(policy_path, "w", encoding="utf-8") as handle:
            json.dump(policy_data, handle)

        manifest_git_commit = {
            "name": "git_commit",
            "version": "0.1.0",
            "description": "Commit staged changes.",
            "risk_level": "medium",
            "action_level": 2,
            "work_room": "code",
            "requires_approval": True,
            "parameters": {
                "type": "object",
                "required": ["repo_path", "message"],
            },
        }
        with open(os.path.join(self.manifests_dir, "git_commit.tool.json"), "w", encoding="utf-8") as handle:
            json.dump(manifest_git_commit, handle)

        self.policy = PolicyEngine(policy_path)
        self.audit = AuditLogger(log_dir=self.audit_dir)
        self.broker = ToolBroker(
            policy_engine=self.policy,
            audit_logger=self.audit,
            manifests_dir=self.manifests_dir,
        )

        self.git_commit_calls = 0

        def fake_git_commit(_args):
            self.git_commit_calls += 1
            return {"output": "should never run", "files_changed": []}

        self.broker.register_handler("git_commit", fake_git_commit)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _gated_call(self):
        return self.broker.call(
            tool_name="git_commit",
            tool_args={
                "repo_path": self.repo_path,
                "message": "checkpoint only",
                "access_token": "example_token_1234567890_abcdefghij",
                "chat_text": "private user conversation text",
            },
            agent_id="mcp-client",
            agent_runtime="mcp-stdio",
            task_id="approval-task",
            client_identity={
                "client_id": "claude_desktop",
                "client_name": "Claude Desktop",
                "transport": "mcp_stdio",
                "request_id": "req-123",
            },
        )

    def test_approval_request_created_and_id_returned(self):
        result = self._gated_call()

        self.assertFalse(result.success)
        self.assertEqual(result.disposition, "approval_required")
        self.assertTrue(result.approval_id)
        self.assertEqual(result.request_id, "req-123")

        approval = self.broker.get_approval(result.approval_id)
        self.assertIsNotNone(approval)
        self.assertEqual(approval.status, "pending")
        self.assertEqual(approval.tool_name, "git_commit")
        self.assertEqual(approval.client_identity.get("client_id"), "claude_desktop")
        self.assertEqual(approval.client_identity.get("client_name"), "Claude Desktop")
        self.assertEqual(approval.client_identity.get("transport"), "mcp_stdio")
        self.assertIn(approval.policy_rule, {"require_approval", "manifest.requires_approval"})

    def test_pending_approval_appears_in_state(self):
        result = self._gated_call()
        state = self.broker.approvals_state()

        pending_ids = [item["approval_id"] for item in state["pending_approvals"]]
        self.assertIn(result.approval_id, pending_ids)
        self.assertGreaterEqual(state["approvals"]["pending_count"], 1)

        pending = [item for item in state["pending_approvals"] if item.get("approval_id") == result.approval_id][0]
        self.assertEqual((pending.get("client_identity") or {}).get("client_id"), "claude_desktop")
        self.assertEqual((pending.get("client_identity") or {}).get("client_name"), "Claude Desktop")
        self.assertEqual((pending.get("client_identity") or {}).get("transport"), "mcp_stdio")

    def test_deny_changes_status_and_never_executes_tool(self):
        result = self._gated_call()
        decision = self.broker.decide_approval(result.approval_id, approved=False, decided_by="tester")

        self.assertIsNotNone(decision)
        self.assertEqual(decision["status"], "denied")
        self.assertEqual(self.git_commit_calls, 0)

        events = self.audit.get_events()
        executed = [e for e in events if e.get("event_type") == "tool_executed" and e.get("tool_name") == "git_commit"]
        self.assertEqual(executed, [])

    def test_approve_records_decision_without_execution(self):
        result = self._gated_call()
        decision = self.broker.decide_approval(result.approval_id, approved=True, decided_by="tester")

        self.assertIsNotNone(decision)
        self.assertEqual(decision["status"], "approved")
        self.assertEqual(decision["decided_by"], "tester")
        self.assertEqual(self.git_commit_calls, 0)

    def test_unknown_approval_id_fails_safely(self):
        decision = self.broker.decide_approval("does-not-exist", approved=True, decided_by="tester")
        self.assertIsNone(decision)

    def test_client_identity_preserved_and_redaction_applied(self):
        result = self._gated_call()
        approval = self.broker.get_approval(result.approval_id)

        self.assertEqual(approval.client_identity.get("client_name"), "Claude Desktop")
        self.assertEqual(approval.requested_args_redacted.get("access_token"), "[REDACTED]")
        self.assertNotIn("chat_text", approval.requested_args_redacted)
        self.assertGreaterEqual(approval.requested_args_redacted.get("private_fields_omitted", 0), 1)
        self.assertIn("access_token=", approval.requested_args_summary)

    def test_no_chat_text_or_secret_values_stored(self):
        result = self._gated_call()
        approval = self.broker.get_approval(result.approval_id)
        events_text = json.dumps(self.audit.get_events()).lower()

        self.assertNotIn("private user conversation text", json.dumps(approval.to_dict()).lower())
        self.assertNotIn("example_token_1234567890_abcdefghij".lower(), events_text)

    def test_raw_shell_remains_blocked(self):
        result = self.broker.call(
            tool_name="raw_shell",
            tool_args={"command": "rm -rf /"},
            agent_id="mcp-client",
            agent_runtime="mcp-stdio",
            task_id="approval-task",
        )
        self.assertFalse(result.success)
        self.assertEqual(result.disposition, "blocked")


if __name__ == "__main__":
    unittest.main()
