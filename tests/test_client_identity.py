import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from adapters import client_identity as cid
from adapters import prove_claude_desktop_client as pcdc


class TestClientIdentityModel(unittest.TestCase):
    def test_default_identity(self):
        identity = cid.ClientIdentity()
        self.assertEqual(identity.client_id, "unknown")
        self.assertEqual(identity.transport, "unknown")
        self.assertEqual(identity.client_name, "Unknown Client")

    def test_to_dict_roundtrip(self):
        original = cid.ClientIdentity(
            client_id="claude_desktop",
            client_name="Claude Desktop",
            client_kind="desktop_app",
            transport="mcp_stdio",
        )
        d = original.to_dict()
        restored = cid.ClientIdentity.from_dict(d)
        self.assertEqual(restored.client_id, "claude_desktop")
        self.assertEqual(restored.client_name, "Claude Desktop")
        self.assertEqual(restored.client_kind, "desktop_app")
        self.assertEqual(restored.transport, "mcp_stdio")

    def test_predefined_identities(self):
        self.assertEqual(cid.CLAUDE_DESKTOP.client_id, "claude_desktop")
        self.assertEqual(cid.CLAUDE_DESKTOP.client_name, "Claude Desktop")
        self.assertEqual(cid.CLAUDE_DESKTOP.client_kind, "desktop_app")
        self.assertEqual(cid.CLAUDE_DESKTOP.transport, "mcp_stdio")

    def test_from_env_reads_env_vars(self):
        env = {
            "SLIMYOS_MCP_AGENT_ID": "test-agent",
            "SLIMYOS_MCP_AGENT_NAME": "Test Agent",
            "SLIMYOS_MCP_TRANSPORT": "test_transport",
        }
        with patch.dict(os.environ, env, clear=False):
            identity = cid.ClientIdentity.from_env()
            self.assertEqual(identity.client_id, "test-agent")
            self.assertEqual(identity.client_name, "Test Agent")
            self.assertEqual(identity.transport, "test_transport")


class TestInferClientIdentityExplicit(unittest.TestCase):
    def test_prefers_client_identity_metadata(self):
        event = {
            "client_identity": {
                "client_id": "claude-desktop",
                "client_name": "Claude Desktop",
                "client_kind": "desktop_app",
                "transport": "mcp_stdio",
            },
            "agent_id": "mcp-client",
            "agent_runtime": "mcp-stdio",
        }
        result = pcdc.infer_client_identity(event)
        self.assertEqual(result["client_identity"], "explicit_claude_desktop")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["client_id"], "claude-desktop")
        self.assertEqual(result["client_name"], "Claude Desktop")
        self.assertEqual(result["source"], "audit_event.client_identity")

    def test_falls_back_to_agent_id(self):
        event = {
            "client_identity": {},
            "agent_id": "claude-desktop",
            "agent_runtime": "claude-desktop",
        }
        result = pcdc.infer_client_identity(event)
        self.assertEqual(result["client_identity"], "explicit_claude_desktop")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["source"], "audit_event.agent_id/agent_runtime")

    def test_returns_inferred_when_no_identity(self):
        event = {
            "client_identity": {},
            "agent_id": "mcp-client",
            "agent_runtime": "mcp-stdio",
        }
        result = pcdc.infer_client_identity(event)
        self.assertEqual(result["client_identity"], "inferred")
        self.assertEqual(result["confidence"], "medium")
        self.assertEqual(result["source"], "inferred")

    def test_does_not_invent_identity(self):
        event = {
            "client_identity": {},
            "agent_id": "",
            "agent_runtime": "",
        }
        result = pcdc.infer_client_identity(event)
        self.assertEqual(result["client_identity"], "inferred")
        self.assertEqual(result["agent_id"], "")
        self.assertIn("inferred", result["note"].lower())


class TestBrokerClientIdentity(unittest.TestCase):
    def test_audit_log_includes_client_identity(self):
        import importlib.util
        import sys
        PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, PROJECT_ROOT)

        spec = importlib.util.spec_from_file_location(
            "services.slimy_auditd.logger",
            os.path.join(PROJECT_ROOT, "services", "slimy-auditd", "logger.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["services.slimy_auditd.logger"] = mod
        spec.loader.exec_module(mod)
        AuditLogger = mod.AuditLogger

        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditLogger(log_dir=tmp)
            event = audit.log(
                event_type="tool_request",
                agent_id="test-agent",
                tool_name="list_directory",
                client_identity={
                    "client_id": "claude_desktop",
                    "client_name": "Claude Desktop",
                    "transport": "mcp_stdio",
                },
            )
            self.assertIn("client_identity", event)
            self.assertEqual(event["client_identity"]["client_id"], "claude_desktop")
            self.assertEqual(event["client_identity"]["client_name"], "Claude Desktop")
            self.assertEqual(event["client_identity"]["transport"], "mcp_stdio")

    def test_audit_log_backward_compatible_no_identity(self):
        import importlib.util
        import sys
        PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, PROJECT_ROOT)

        spec = importlib.util.spec_from_file_location(
            "services.slimy_auditd.logger",
            os.path.join(PROJECT_ROOT, "services", "slimy-auditd", "logger.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["services.slimy_auditd.logger"] = mod
        spec.loader.exec_module(mod)
        AuditLogger = mod.AuditLogger

        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditLogger(log_dir=tmp)
            event = audit.log(
                event_type="tool_request",
                agent_id="test-agent",
                tool_name="list_directory",
            )
            self.assertIn("client_identity", event)
            self.assertEqual(event["client_identity"], {})


class TestNoPrivateChatText(unittest.TestCase):
    def test_identity_never_includes_chat_text(self):
        identity = cid.ClientIdentity()
        d = identity.to_dict()
        for key in d:
            self.assertNotIn("chat", key.lower())
            self.assertNotIn("message", key.lower())
            self.assertNotIn("conversation", key.lower())

    def test_audit_event_no_chat_text(self):
        import importlib.util
        import sys
        PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, PROJECT_ROOT)

        spec = importlib.util.spec_from_file_location(
            "services.slimy_auditd.logger",
            os.path.join(PROJECT_ROOT, "services", "slimy-auditd", "logger.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["services.slimy_auditd.logger"] = mod
        spec.loader.exec_module(mod)
        AuditLogger = mod.AuditLogger

        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditLogger(log_dir=tmp)
            event = audit.log(
                event_type="tool_request",
                agent_id="test-agent",
                tool_name="list_directory",
                client_identity={"client_id": "test"},
            )
            event_str = json.dumps(event)
            self.assertNotIn("chat", event_str.lower())
            self.assertNotIn("conversation", event_str.lower())


class TestRuntimeStatusClientActivity(unittest.TestCase):
    def test_extract_client_activity(self):
        events = [
            {
                "event_type": "tool_executed",
                "timestamp": "2026-05-16T10:00:00+00:00",
                "tool_name": "list_directory",
                "disposition": "allowed",
                "policy_rule": "tool_overrides.list_directory.disposition",
                "files_changed": [],
                "client_identity": {
                    "client_id": "claude_desktop",
                    "client_name": "Claude Desktop",
                    "transport": "mcp_stdio",
                },
                "result": {"output": "file1\nfile2"},
            }
        ]
        import sys
        PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, PROJECT_ROOT)

        from dashboard.runtime_status import RuntimeStatusCollector
        collector = RuntimeStatusCollector(repo_path=PROJECT_ROOT)
        activity = collector._extract_client_activity(events)
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity[0]["client_name"], "Claude Desktop")
        self.assertEqual(activity[0]["transport"], "mcp_stdio")
        self.assertEqual(activity[0]["tool_name"], "list_directory")
        self.assertEqual(activity[0]["disposition"], "allowed")
        self.assertFalse(activity[0]["files_modified"])
        self.assertFalse(activity[0]["unsafe_action"])

    def test_extract_clients_seen(self):
        events = [
            {
                "event_type": "tool_executed",
                "timestamp": "2026-05-16T10:00:00+00:00",
                "tool_name": "list_directory",
                "client_identity": {
                    "client_id": "claude_desktop",
                    "client_name": "Claude Desktop",
                    "transport": "mcp_stdio",
                },
            },
            {
                "event_type": "tool_executed",
                "timestamp": "2026-05-16T10:01:00+00:00",
                "tool_name": "read_file",
                "client_identity": {
                    "client_id": "claude_desktop",
                    "client_name": "Claude Desktop",
                    "transport": "mcp_stdio",
                },
            },
        ]
        import sys
        PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, PROJECT_ROOT)

        from dashboard.runtime_status import RuntimeStatusCollector
        collector = RuntimeStatusCollector(repo_path=PROJECT_ROOT)
        clients = collector._extract_clients_seen(events)
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0]["client_id"], "claude_desktop")
        self.assertEqual(clients[0]["call_count"], 2)

    def test_find_last_claude_desktop_event(self):
        events = [
            {
                "event_type": "tool_executed",
                "timestamp": "2026-05-16T10:00:00+00:00",
                "tool_name": "list_directory",
                "disposition": "allowed",
                "policy_rule": "tool_overrides.list_directory.disposition",
                "client_identity": {"client_id": "claude-desktop"},
            }
        ]
        import sys
        PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, PROJECT_ROOT)

        from dashboard.runtime_status import RuntimeStatusCollector
        collector = RuntimeStatusCollector(repo_path=PROJECT_ROOT)
        event = collector._find_last_claude_desktop_event(events)
        self.assertIsNotNone(event)
        self.assertEqual(event["tool_name"], "list_directory")


if __name__ == "__main__":
    unittest.main()
