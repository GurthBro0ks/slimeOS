import tempfile
import unittest
from pathlib import Path
from urllib import error as urlerror

from dashboard.runtime_status import RuntimeStatusCollector


class RuntimeStatusCollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmpdir.name) / "repo"
        self.slimy_home = Path(self.tmpdir.name) / "slimy"
        (self.repo / "policies").mkdir(parents=True)
        (self.slimy_home / "config").mkdir(parents=True)
        (self.slimy_home / "audit").mkdir(parents=True)
        (self.slimy_home / "proofs").mkdir(parents=True)
        (self.repo / "policies" / "default.policy.json").write_text("{}")
        (self.slimy_home / "config" / "policy.json").write_text("{}")
        (self.slimy_home / "audit" / "audit-20260101.jsonl").write_text("{}\n")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_hermes_unreachable_is_warn_not_fail(self):
        def fake_runner(command):
            if command[-1] in {"slimyos-toold", "slimyos-dashboard"}:
                return True, "active" if "is-active" in command else "enabled", ""
            return False, "", ""

        def fake_getter(url):
            if url.endswith("/health"):
                return {"status": "ok", "tools": 43}
            if url.endswith("/tools"):
                return {"count": 43, "tools": []}
            if url.endswith("/state"):
                return {"panicked": False, "pending_approvals": [], "tasks": [], "agents": [], "stats": {}}
            if url.endswith("/audit/recent"):
                return {"events": [], "count": 0}
            if url.endswith("/v1/models"):
                raise urlerror.URLError("down")
            raise AssertionError(f"Unexpected URL: {url}")

        collector = RuntimeStatusCollector(
            repo_path=str(self.repo),
            slimyos_home=str(self.slimy_home),
            command_runner=fake_runner,
            http_get_json=fake_getter,
        )
        runtime = collector.collect()

        self.assertEqual(runtime["broker"]["status"], "pass")
        self.assertEqual(runtime["hermes"]["status"], "warn")
        self.assertIn("auth_required_or_proxy_down", runtime["warnings"])

    def test_broker_unreachable_sets_fail_and_error(self):
        def fake_runner(command):
            if command[-1] in {"slimyos-toold", "slimyos-dashboard"}:
                return True, "active" if "is-active" in command else "enabled", ""
            return False, "", ""

        def fake_getter(url):
            if url.endswith("/v1/models"):
                return {"data": [{"id": "hermes-agent"}]}
            raise urlerror.URLError("broker down")

        collector = RuntimeStatusCollector(
            repo_path=str(self.repo),
            slimyos_home=str(self.slimy_home),
            command_runner=fake_runner,
            http_get_json=fake_getter,
        )
        runtime = collector.collect()

        self.assertEqual(runtime["broker"]["status"], "fail")
        self.assertTrue(runtime["errors"])

    def test_service_failure_records_runtime_error(self):
        def fake_runner(command):
            service_name = command[-1]
            if service_name == "slimyos-toold" and "is-active" in command:
                return False, "", "inactive"
            if service_name == "slimyos-toold" and "is-enabled" in command:
                return True, "enabled", ""
            if service_name == "slimyos-dashboard" and "is-active" in command:
                return True, "active", ""
            if service_name == "slimyos-dashboard" and "is-enabled" in command:
                return True, "enabled", ""
            return False, "", ""

        def fake_getter(url):
            if url.endswith("/health"):
                return {"status": "ok", "tools": 43}
            if url.endswith("/tools"):
                return {"count": 43, "tools": []}
            if url.endswith("/state"):
                return {"panicked": False, "pending_approvals": [], "tasks": [], "agents": [], "stats": {}}
            if url.endswith("/audit/recent"):
                return {"events": [], "count": 0}
            if url.endswith("/v1/models"):
                raise urlerror.URLError("down")
            raise AssertionError(f"Unexpected URL: {url}")

        collector = RuntimeStatusCollector(
            repo_path=str(self.repo),
            slimyos_home=str(self.slimy_home),
            command_runner=fake_runner,
            http_get_json=fake_getter,
        )
        runtime = collector.collect()

        self.assertEqual(runtime["services"]["slimyos-toold"]["status"], "fail")
        self.assertIn("service_slimyos-toold_not_active", runtime["errors"])


if __name__ == "__main__":
    unittest.main()
