import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib import error as urlerror

from adapters.client_preflight import PreflightConfig, run_client_preflight, write_preflight_artifacts


class ClientPreflightTests(unittest.TestCase):
    def test_core_checks_pass_with_hermes_warn(self):
        def fake_get(url, timeout=3.0):
            if url.endswith("/health"):
                return {"status": "ok", "tools": 43}
            if url.endswith("/api/runtime"):
                return {"status": "ok"}
            if url.endswith("/v1/models"):
                raise urlerror.URLError("auth required")
            raise AssertionError(f"Unexpected URL: {url}")

        def fake_tool_call(*args, **kwargs):
            tool_name = args[1]
            if tool_name == "read_file":
                return {"success": True, "disposition": "allowed"}
            if tool_name == "raw_shell":
                return {"success": False, "disposition": "blocked", "policy_rule": "unknown_tool"}
            if tool_name == "restart_service":
                return {"success": False, "disposition": "blocked"}
            if tool_name == "git_commit":
                return {"success": False, "disposition": "approval_required"}
            raise AssertionError(f"Unexpected tool: {tool_name}")

        def fake_which(name):
            mapping = {
                "hermes": "/usr/local/bin/hermes",
                "claude": "/usr/local/bin/claude",
                "codex": "/usr/local/bin/codex",
                "opencode": None,
            }
            return mapping.get(name)

        with patch("adapters.client_preflight._http_get_json", side_effect=fake_get), patch(
            "adapters.client_preflight._tool_call", side_effect=fake_tool_call
        ), patch("adapters.client_preflight.shutil.which", side_effect=fake_which):
            result = run_client_preflight(PreflightConfig(repo_path="."))

        self.assertEqual(result["final_result"], "PASS")
        self.assertIn("hermes_auth_required_or_proxy_down", result["warnings"])
        self.assertIn("client_missing:opencode", result["warnings"])
        self.assertEqual(result["errors"], [])

    def test_core_fail_when_broker_down(self):
        def fake_get(url, timeout=3.0):
            if url.endswith("/v1/models"):
                raise urlerror.URLError("down")
            raise urlerror.URLError("broker down")

        def fake_tool_call(*args, **kwargs):
            raise RuntimeError("should not succeed")

        with patch("adapters.client_preflight._http_get_json", side_effect=fake_get), patch(
            "adapters.client_preflight._tool_call", side_effect=fake_tool_call
        ), patch("adapters.client_preflight.shutil.which", return_value=None), patch(
            "adapters.client_preflight.os.path.expanduser", return_value="/nonexistent/hermes"
        ):
            result = run_client_preflight(PreflightConfig(repo_path="."))

        self.assertEqual(result["final_result"], "FAIL")
        self.assertTrue(any(err.startswith("broker_unreachable") for err in result["errors"]))

    def test_write_preflight_artifacts(self):
        sample = {
            "timestamp": "2026-05-15T00:00:00+00:00",
            "repo_path": "/tmp/repo",
            "broker_url": "http://localhost:3003",
            "dashboard_url": "http://localhost:3002",
            "final_result": "PASS",
            "warnings": [],
            "errors": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            write_preflight_artifacts(sample, tmpdir)
            out = Path(tmpdir)
            self.assertTrue((out / "client_preflight.json").exists())
            self.assertTrue((out / "RESULT.txt").exists())
            self.assertTrue((out / "meta.json").exists())

            payload = json.loads((out / "client_preflight.json").read_text())
            self.assertEqual(payload["final_result"], "PASS")


if __name__ == "__main__":
    unittest.main()
