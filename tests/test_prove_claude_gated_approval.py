import unittest

from adapters import prove_claude_gated_approval as pcga


def _base_event() -> dict:
    return {
        "event_id": "evt-1",
        "event_type": "approval_requested",
        "tool_name": "git_commit",
        "disposition": "approval_required",
        "tool_args": {
            "repo_path": "/tmp/demo",
            "message": "harmless test",
            "access_token": "[REDACTED]",
            "private_fields_omitted": 1,
        },
        "metadata": {"approval_id": "apr-1"},
        "client_identity": {
            "client_id": "claude_desktop",
            "client_name": "Claude Desktop",
            "transport": "mcp_stdio",
        },
    }


def _base_approval() -> dict:
    return {
        "approval_id": "apr-1",
        "tool_name": "git_commit",
        "disposition": "approval_required",
        "status": "pending",
        "execution_status": "not_executed",
        "requested_args_redacted": {
            "repo_path": "/tmp/demo",
            "message": "harmless test",
            "access_token": "[REDACTED]",
            "private_fields_omitted": 1,
        },
        "client_identity": {
            "client_id": "claude_desktop",
            "client_name": "Claude Desktop",
            "transport": "mcp_stdio",
        },
    }


def _base_state() -> dict:
    return {
        "pending_approvals": [
            {
                "approval_id": "apr-1",
                "tool_name": "git_commit",
                "status": "pending",
            }
        ]
    }


class TestProveClaudeGatedApproval(unittest.TestCase):
    def test_detects_claude_desktop_approval_required_event(self):
        result = pcga.evaluate_approval_observation(
            approval=_base_approval(),
            event=_base_event(),
            dashboard_state=_base_state(),
            repo_unchanged_ok=True,
            gated_tool="git_commit",
        )
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["approval_id"], "apr-1")

    def test_requires_approval_id(self):
        event = _base_event()
        approval = _base_approval()
        event["metadata"] = {}
        approval["approval_id"] = ""
        result = pcga.evaluate_approval_observation(
            approval=approval,
            event=event,
            dashboard_state=_base_state(),
            repo_unchanged_ok=True,
            gated_tool="git_commit",
        )
        self.assertEqual(result["result"], "FAIL")
        self.assertIn("missing_approval_id", result["errors"])

    def test_requires_pending_status(self):
        approval = _base_approval()
        approval["status"] = "approved"
        result = pcga.evaluate_approval_observation(
            approval=approval,
            event=_base_event(),
            dashboard_state=_base_state(),
            repo_unchanged_ok=True,
            gated_tool="git_commit",
        )
        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(any("approval_status_not_pending" in e for e in result["errors"]))

    def test_fails_when_identity_missing(self):
        approval = _base_approval()
        approval["client_identity"] = {}
        event = _base_event()
        event["client_identity"] = {}
        result = pcga.evaluate_approval_observation(
            approval=approval,
            event=event,
            dashboard_state=_base_state(),
            repo_unchanged_ok=True,
            gated_tool="git_commit",
        )
        self.assertEqual(result["result"], "FAIL")
        self.assertIn("client_identity_not_claude_desktop", result["errors"])

    def test_fails_when_identity_unknown(self):
        approval = _base_approval()
        approval["client_identity"] = {
            "client_id": "unknown",
            "client_name": "Unknown Client",
            "transport": "mcp_stdio",
        }
        result = pcga.evaluate_approval_observation(
            approval=approval,
            event=_base_event(),
            dashboard_state={"pending_approvals": [{"approval_id": "apr-1"}]},
            repo_unchanged_ok=True,
            gated_tool="git_commit",
        )
        self.assertEqual(result["result"], "FAIL")
        self.assertIn("client_identity_not_claude_desktop", result["errors"])

    def test_requires_dashboard_pending_card(self):
        result = pcga.evaluate_approval_observation(
            approval=_base_approval(),
            event=_base_event(),
            dashboard_state={"pending_approvals": []},
            repo_unchanged_ok=True,
            gated_tool="git_commit",
        )
        self.assertEqual(result["result"], "FAIL")
        self.assertIn("dashboard_pending_approval_missing", result["errors"])

    def test_refuses_pass_when_execution_already_happened(self):
        approval = _base_approval()
        approval["execution_status"] = "executed"
        result = pcga.evaluate_approval_observation(
            approval=approval,
            event=_base_event(),
            dashboard_state=_base_state(),
            repo_unchanged_ok=True,
            gated_tool="git_commit",
        )
        self.assertEqual(result["result"], "FAIL")
        self.assertIn("execution_already_happened", result["errors"])

    def test_refuses_pass_if_real_repo_changed(self):
        result = pcga.evaluate_approval_observation(
            approval=_base_approval(),
            event=_base_event(),
            dashboard_state=_base_state(),
            repo_unchanged_ok=False,
            gated_tool="git_commit",
        )
        self.assertEqual(result["result"], "FAIL")
        self.assertIn("real_repo_changed", result["errors"])

    def test_pending_manual_if_no_event(self):
        result = pcga.evaluate_approval_observation(
            approval=None,
            event=None,
            dashboard_state=_base_state(),
            repo_unchanged_ok=True,
            gated_tool="git_commit",
        )
        self.assertEqual(result["result"], "PENDING_MANUAL")

    def test_redacts_secret_like_args(self):
        redacted = pcga.redact_secret_like_args(
            {
                "api_key": "super-secret-1234567890",
                "nested": {"token": "abc1234567890"},
            }
        )
        self.assertEqual(redacted["api_key"], "[REDACTED]")
        self.assertEqual(redacted["nested"]["token"], "[REDACTED]")

    def test_confirms_no_chat_text_stored(self):
        self.assertFalse(pcga.contains_chat_text({"message": "safe"}))
        self.assertTrue(pcga.contains_chat_text({"chat_text": "private conversation"}))


if __name__ == "__main__":
    unittest.main()
