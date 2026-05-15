import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adapters import mcp_doctor


class MCPDoctorTests(unittest.TestCase):
    def test_generate_snippets_shape(self):
        snippets = mcp_doctor.generate_snippets("/tmp/slimeOS", "http://localhost:3003")
        self.assertIn("generated_claude_desktop_config.json", snippets)
        desktop = json.loads(snippets["generated_claude_desktop_config.json"])
        self.assertIn("mcpServers", desktop)
        self.assertIn("slimyos", desktop["mcpServers"])
        self.assertIn("generated_claude_code_notes.md", snippets)

    def test_detect_clients_missing_becomes_warn(self):
        with patch("adapters.mcp_doctor.shutil.which", return_value=None), patch(
            "adapters.mcp_doctor.os.path.expanduser", side_effect=lambda p: "/tmp/does-not-exist"
        ):
            clients, warnings = mcp_doctor.detect_clients()

        self.assertFalse(clients["claude"]["installed"])
        self.assertIn("client_missing:claude", warnings)
        self.assertIn("claude_desktop_config_missing", warnings)

    def test_hermes_unreachable_is_warn(self):
        with patch("adapters.mcp_doctor.shutil.which", return_value="/usr/bin/hermes"), patch(
            "adapters.mcp_doctor._http_get_json", side_effect=RuntimeError("down")
        ):
            hermes, warnings = mcp_doctor._check_hermes_state()

        self.assertEqual(hermes["status"], "warn")
        self.assertIn("hermes_auth_required_or_proxy_down", warnings)

    def test_broker_unreachable_results_fail(self):
        def fake_http(url):
            raise RuntimeError("offline")

        with tempfile.TemporaryDirectory() as tmp:
            with patch("adapters.mcp_doctor._http_get_json", side_effect=fake_http), patch(
                "adapters.mcp_doctor._run_mcp_request", side_effect=RuntimeError("cannot run")
            ):
                summary = mcp_doctor.run_mcp_doctor(repo_root=".", proof_dir=tmp)

        self.assertEqual(summary["result"], "FAIL")
        self.assertTrue(any("broker_unreachable" in err for err in summary["errors"]))

    def test_block_evidence_required_for_pass(self):
        def fake_http(url):
            if url.endswith("/health"):
                return {"status": "ok", "tools": 43}
            return {"runtime": {}}

        responses = {
            1: {"result": {"serverInfo": {}}},
            2: {"result": {"tools": [{} for _ in range(43)]}},
            3: {"result": {"content": [{"type": "text", "text": '{"success": true}'}]}},
            4: {"result": {"content": [{"type": "text", "text": '{"disposition": "allowed"}'}]}},
            5: {"result": {"content": [{"type": "text", "text": '{"disposition": "blocked"}'}]}},
        }

        def fake_mcp(repo_root, payload):
            return responses[payload["id"]]

        with tempfile.TemporaryDirectory() as tmp:
            with patch("adapters.mcp_doctor._http_get_json", side_effect=fake_http), patch(
                "adapters.mcp_doctor._run_mcp_request", side_effect=fake_mcp
            ), patch("adapters.mcp_doctor.detect_clients", return_value=({}, [])), patch(
                "adapters.mcp_doctor._check_hermes_state", return_value=({}, [])
            ):
                summary = mcp_doctor.run_mcp_doctor(repo_root=".", proof_dir=tmp)

        self.assertEqual(summary["result"], "FAIL")
        self.assertIn("mcp_raw_shell_not_blocked", summary["errors"])


if __name__ == "__main__":
    unittest.main()
