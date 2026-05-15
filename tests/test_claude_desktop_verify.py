import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from adapters import claude_desktop_verify as cdv


class TestLoadConfig(unittest.TestCase):
    def test_parses_valid_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.json"
            cfg.write_text('{"mcpServers": {"a": {"command": "x"}}}')
            result = cdv.load_claude_desktop_config(str(cfg))
            self.assertIn("mcpServers", result)
            self.assertIn("a", result["mcpServers"])

    def test_raises_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.json"
            cfg.write_text("{bad")
            with self.assertRaises(json.JSONDecodeError):
                cdv.load_claude_desktop_config(str(cfg))

    def test_raises_on_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            cdv.load_claude_desktop_config("/nonexistent/path.json")


class TestFindSlimyOS(unittest.TestCase):
    def test_finds_slimyos_entry(self):
        config = {"mcpServers": {"slimyos": {"command": "/path/to/run.sh"}, "other": {}}}
        entry = cdv.find_slimyos_entry(config)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["command"], "/path/to/run.sh")

    def test_returns_none_when_missing(self):
        config = {"mcpServers": {"other": {"command": "x"}}}
        self.assertIsNone(cdv.find_slimyos_entry(config))

    def test_returns_none_empty_config(self):
        self.assertIsNone(cdv.find_slimyos_entry({}))


class TestExistingServers(unittest.TestCase):
    def test_lists_server_names(self):
        config = {"mcpServers": {"google-drive": {}, "gmail": {}, "slimyos": {}}}
        servers = cdv.list_existing_servers(config)
        self.assertEqual(sorted(servers), ["gmail", "google-drive", "slimyos"])

    def test_empty_when_no_servers(self):
        self.assertEqual(cdv.list_existing_servers({}), [])
        self.assertEqual(cdv.list_existing_servers({"mcpServers": {}}), [])


class TestRedaction(unittest.TestCase):
    def test_redacts_secret_keys(self):
        entry = {
            "command": "/run.sh",
            "args": [],
            "env": {
                "API_KEY": "secret123",
                "MY_TOKEN": "tok456",
                "NORMAL_VAR": "visible",
                "db_password": "hunter2",
                "SLIMYOS_TOOLD_URL": "http://localhost:3003",
            },
        }
        redacted = cdv.redact_entry(entry)
        self.assertEqual(redacted["env"]["API_KEY"], "***REDACTED***")
        self.assertEqual(redacted["env"]["MY_TOKEN"], "***REDACTED***")
        self.assertEqual(redacted["env"]["db_password"], "***REDACTED***")
        self.assertEqual(redacted["env"]["NORMAL_VAR"], "visible")
        self.assertEqual(redacted["env"]["SLIMYOS_TOOLD_URL"], "http://localhost:3003")

    def test_no_env_no_crash(self):
        entry = {"command": "/run.sh"}
        redacted = cdv.redact_entry(entry)
        self.assertNotIn("env", redacted)


class TestValidateLauncher(unittest.TestCase):
    def test_valid_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            launcher = Path(tmp) / "run.sh"
            launcher.write_text("#!/bin/bash\nexit 0")
            launcher.chmod(0o755)
            entry = {"command": str(launcher), "args": []}
            result = cdv.validate_launcher(entry)
            self.assertTrue(result["valid"])
            self.assertTrue(result["path_exists"])
            self.assertTrue(result["is_executable"])

    def test_missing_launcher(self):
        entry = {"command": "/nonexistent/run.sh", "args": []}
        result = cdv.validate_launcher(entry)
        self.assertFalse(result["valid"])
        self.assertFalse(result["path_exists"])

    def test_not_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            launcher = Path(tmp) / "run.sh"
            launcher.write_text("not executable")
            launcher.chmod(0o644)
            entry = {"command": str(launcher), "args": []}
            result = cdv.validate_launcher(entry)
            self.assertFalse(result["valid"])
            self.assertFalse(result["is_executable"])


class TestBuildCommand(unittest.TestCase):
    def test_builds_command_with_args(self):
        entry = {"command": "/run.sh", "args": ["--flag", "value"]}
        cmd = cdv.build_exact_command(entry)
        self.assertEqual(cmd, ["/run.sh", "--flag", "value"])

    def test_builds_command_no_args(self):
        entry = {"command": "/run.sh"}
        cmd = cdv.build_exact_command(entry)
        self.assertEqual(cmd, ["/run.sh"])

    def test_build_env(self):
        entry = {"env": {"A": "1", "B": "2"}}
        env = cdv.build_env(entry)
        self.assertEqual(env, {"A": "1", "B": "2"})


class TestFailClosedMissing(unittest.TestCase):
    def test_missing_slimyos_causes_fail(self):
        config = {"mcpServers": {"other": {"command": "x"}}}
        entry = cdv.find_slimyos_entry(config)
        self.assertIsNone(entry)


class TestManualPrompt(unittest.TestCase):
    def test_contains_restart_instruction(self):
        prompt = cdv.build_manual_prompt()
        self.assertIn("Restart Claude Desktop", prompt)
        self.assertIn("SlimyOS", prompt)
        self.assertIn("--rollback", prompt)


if __name__ == "__main__":
    unittest.main()
