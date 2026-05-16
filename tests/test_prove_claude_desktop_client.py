import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

from adapters import prove_claude_desktop_client as pcdc


class TestDetectAuditDir(unittest.TestCase):
    def test_finds_jsonl_in_candidate_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit_dir = Path(tmp) / "audit"
            audit_dir.mkdir()
            (audit_dir / "audit-20260515.jsonl").write_text("{}")
            result = pcdc.detect_audit_dir(str(audit_dir))
            self.assertIsNotNone(result)
            self.assertIn("audit", result)

    def test_returns_none_when_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit_dir = Path(tmp) / "audit"
            audit_dir.mkdir()
            with patch.object(pcdc.Path, "home", return_value=Path(tmp)):
                result = pcdc.detect_audit_dir(str(audit_dir))
                self.assertIsNone(result)


class TestReadAuditDir(unittest.TestCase):
    def test_reads_last_n_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit_dir = Path(tmp) / "audit"
            audit_dir.mkdir()
            p = audit_dir / "audit-20260515.jsonl"
            events = [{"i": i} for i in range(20)]
            p.write_text("\n".join(json.dumps(e) for e in events))
            result = pcdc.read_audit_dir(str(audit_dir), n=5)
            self.assertEqual(len(result), 5)
            self.assertEqual(result[-1]["i"], 19)

    def test_skips_malformed_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit_dir = Path(tmp) / "audit"
            audit_dir.mkdir()
            p = audit_dir / "audit-20260515.jsonl"
            p.write_text('{"good":true}\n{bad\n{"good":true}')
            result = pcdc.read_audit_dir(str(audit_dir), n=10)
            self.assertEqual(len(result), 2)


class TestFindMatchingEvent(unittest.TestCase):
    def test_finds_allowed_list_directory(self):
        events = [
            {"tool_name": "read_file", "disposition": "allowed"},
            {"tool_name": "list_directory", "disposition": "allowed", "agent_id": "claude-desktop"},
        ]
        result = pcdc.find_matching_event(events, tool_name="list_directory", agent_id="claude-desktop")
        self.assertIsNotNone(result)
        self.assertEqual(result["agent_id"], "claude-desktop")

    def test_skips_wrong_agent(self):
        events = [
            {"tool_name": "list_directory", "disposition": "allowed", "agent_id": "other"},
        ]
        result = pcdc.find_matching_event(events, tool_name="list_directory", agent_id="claude-desktop")
        self.assertIsNone(result)

    def test_skips_blocked(self):
        events = [
            {"tool_name": "list_directory", "disposition": "blocked", "agent_id": "claude-desktop"},
        ]
        result = pcdc.find_matching_event(events, tool_name="list_directory", agent_id="claude-desktop")
        self.assertIsNone(result)


class TestFindRecentAllowedListDirectory(unittest.TestCase):
    def test_finds_recent_event(self):
        now = datetime.now(timezone.utc).isoformat()
        events = [
            {"tool_name": "list_directory", "disposition": "allowed", "timestamp": now},
        ]
        result = pcdc.find_recent_allowed_list_directory(events, max_age_seconds=3600)
        self.assertIsNotNone(result)

    def test_ignores_old_event(self):
        old = "2020-01-01T00:00:00+00:00"
        events = [
            {"tool_name": "list_directory", "disposition": "allowed", "timestamp": old},
        ]
        result = pcdc.find_recent_allowed_list_directory(events, max_age_seconds=3600)
        self.assertIsNone(result)


class TestCheckSafety(unittest.TestCase):
    def test_safe_event(self):
        event = {
            "tool_name": "list_directory",
            "disposition": "allowed",
            "files_changed": [],
            "policy_rule": "tool_overrides.list_directory.disposition",
        }
        result = pcdc.check_safety(event)
        self.assertTrue(result["no_file_mutations"])
        self.assertTrue(result["no_raw_shell"])
        self.assertTrue(result["no_privileged_restart"])
        self.assertTrue(result["policy_rule_present"])
        self.assertTrue(result["disposition_allowed"])

    def test_raw_shell_is_unsafe(self):
        event = {
            "tool_name": "raw_shell",
            "disposition": "allowed",
            "files_changed": [],
            "policy_rule": "",
        }
        result = pcdc.check_safety(event)
        self.assertFalse(result["no_raw_shell"])

    def test_file_mutations_unsafe(self):
        event = {
            "tool_name": "write_file",
            "disposition": "allowed",
            "files_changed": ["foo.txt"],
            "policy_rule": "",
        }
        result = pcdc.check_safety(event)
        self.assertFalse(result["no_file_mutations"])


class TestInferClientIdentity(unittest.TestCase):
    def test_explicit_claude_desktop(self):
        event = {"agent_id": "claude-desktop", "agent_runtime": "claude-desktop"}
        result = pcdc.infer_client_identity(event)
        self.assertEqual(result["client_identity"], "explicit_claude_desktop")
        self.assertEqual(result["confidence"], "high")

    def test_inferred_when_not_explicit(self):
        event = {"agent_id": "mcp-client", "agent_runtime": "mcp-stdio"}
        result = pcdc.infer_client_identity(event)
        self.assertEqual(result["client_identity"], "inferred")
        self.assertEqual(result["confidence"], "medium")
        self.assertIn("inferred", result["note"])

    def test_does_not_invent_identity(self):
        event = {"agent_id": "", "agent_runtime": ""}
        result = pcdc.infer_client_identity(event)
        self.assertEqual(result["client_identity"], "inferred")
        self.assertEqual(result["agent_id"], "")


class TestRunHealthChecks(unittest.TestCase):
    @patch("adapters.prove_claude_desktop_client._http_get_json")
    def test_broker_ok(self, mock_get):
        mock_get.return_value = {"status": "ok", "tools": 43}
        result = pcdc.run_health_checks()
        self.assertEqual(result["broker_health"]["status"], "ok")
        self.assertEqual(len(result["errors"]), 0)

    @patch("adapters.prove_claude_desktop_client._http_get_json")
    def test_broker_fail(self, mock_get):
        mock_get.side_effect = Exception("connection refused")
        result = pcdc.run_health_checks()
        self.assertTrue(any("broker_health_failed" in e for e in result["errors"]))


class TestRunProofIntegration(unittest.TestCase):
    @patch("adapters.prove_claude_desktop_client.run_health_checks")
    @patch("adapters.prove_claude_desktop_client.detect_audit_dir")
    @patch("adapters.prove_claude_desktop_client.read_audit_dir")
    def test_pass_with_explicit_claude_event(self, mock_tail, mock_audit, mock_health):
        mock_audit.return_value = "/fake/audit"
        now = datetime.now(timezone.utc).isoformat()
        mock_tail.return_value = [
            {
                "tool_name": "list_directory",
                "disposition": "allowed",
                "agent_id": "claude-desktop",
                "agent_runtime": "claude-desktop",
                "policy_rule": "tool_overrides.list_directory.disposition",
                "files_changed": [],
                "timestamp": now,
            }
        ]
        mock_health.return_value = {
            "broker_health": {"status": "ok"},
            "dashboard_runtime": {},
            "mcp_healthline": "PASS",
            "mcp_doctor": {},
            "errors": [],
            "warnings": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            proof_dir = Path(tmp) / "proof"
            meta = pcdc.run_proof(
                repo_root=tmp,
                proof_dir=str(proof_dir),
                broker_url="http://localhost:3003",
                dashboard_url="http://localhost:3002",
            )
            self.assertEqual(meta["result"], "PASS")
            self.assertTrue(meta["matching_audit_event_found"])
            self.assertEqual(meta["matching_policy_rule"], "tool_overrides.list_directory.disposition")
            self.assertFalse(meta["files_modified"])
            self.assertFalse(meta["unsafe_actions_detected"])

    @patch("adapters.prove_claude_desktop_client.run_health_checks")
    @patch("adapters.prove_claude_desktop_client.detect_audit_dir")
    @patch("adapters.prove_claude_desktop_client.read_audit_dir")
    def test_pending_manual_when_no_event(self, mock_tail, mock_audit, mock_health):
        mock_audit.return_value = "/fake/audit"
        mock_tail.return_value = []
        mock_health.return_value = {
            "broker_health": {"status": "ok"},
            "dashboard_runtime": {},
            "mcp_healthline": "PASS",
            "mcp_doctor": {},
            "errors": [],
            "warnings": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            proof_dir = Path(tmp) / "proof"
            meta = pcdc.run_proof(
                repo_root=tmp,
                proof_dir=str(proof_dir),
            )
            self.assertEqual(meta["result"], "PENDING_MANUAL")
            self.assertFalse(meta["matching_audit_event_found"])

    @patch("adapters.prove_claude_desktop_client.run_health_checks")
    @patch("adapters.prove_claude_desktop_client.detect_audit_dir")
    @patch("adapters.prove_claude_desktop_client.read_audit_dir")
    def test_fail_when_file_mutations_detected(self, mock_tail, mock_audit, mock_health):
        mock_audit.return_value = "/fake/audit"
        now = datetime.now(timezone.utc).isoformat()
        mock_tail.return_value = [
            {
                "tool_name": "list_directory",
                "disposition": "allowed",
                "agent_id": "claude-desktop",
                "agent_runtime": "claude-desktop",
                "policy_rule": "tool_overrides.list_directory.disposition",
                "files_changed": ["foo.txt"],
                "timestamp": now,
            }
        ]
        mock_health.return_value = {
            "broker_health": {"status": "ok"},
            "dashboard_runtime": {},
            "mcp_healthline": "PASS",
            "mcp_doctor": {},
            "errors": [],
            "warnings": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            proof_dir = Path(tmp) / "proof"
            meta = pcdc.run_proof(
                repo_root=tmp,
                proof_dir=str(proof_dir),
            )
            self.assertEqual(meta["result"], "FAIL")
            self.assertTrue(any("file_mutations" in e for e in meta["errors"]))


if __name__ == "__main__":
    unittest.main()
