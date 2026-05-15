import json
import tempfile
import unittest
from pathlib import Path

from adapters import mcp_configure


class TestDetectConfigPaths(unittest.TestCase):
    def test_detects_claude_desktop_path(self):
        with tempfile.TemporaryDirectory() as home:
            config_dir = Path(home) / ".config" / "Claude"
            config_dir.mkdir(parents=True)
            (config_dir / "claude_desktop_config.json").write_text("{}")
            detected = mcp_configure.detect_config_paths(home_override=home)
            self.assertTrue(detected["claude_desktop"]["exists"])
            self.assertEqual(detected["claude_desktop"]["status"], "found")

    def test_detects_alt_path(self):
        with tempfile.TemporaryDirectory() as home:
            config_dir = Path(home) / ".config" / "claude-desktop"
            config_dir.mkdir(parents=True)
            (config_dir / "claude_desktop_config.json").write_text("{}")
            detected = mcp_configure.detect_config_paths(home_override=home)
            self.assertTrue(detected["claude_desktop"]["exists"])

    def test_missing_claude_desktop_is_not_found(self):
        with tempfile.TemporaryDirectory() as home:
            detected = mcp_configure.detect_config_paths(home_override=home)
            self.assertFalse(detected["claude_desktop"]["exists"])
            self.assertEqual(detected["claude_desktop"]["status"], "not_found")


class TestGenerateClaudeDesktopConfig(unittest.TestCase):
    def test_new_config_shape(self):
        config = mcp_configure.generate_claude_desktop_config("/repo", "http://localhost:3003")
        self.assertIn("mcpServers", config)
        self.assertIn("slimyos", config["mcpServers"])
        self.assertIn("command", config["mcpServers"]["slimyos"])

    def test_merge_preserves_existing_servers(self):
        existing = {
            "mcpServers": {
                "other_server": {"command": "other", "args": []},
            }
        }
        config = mcp_configure.generate_claude_desktop_config(
            "/repo", "http://localhost:3003", existing
        )
        self.assertIn("slimyos", config["mcpServers"])
        self.assertIn("other_server", config["mcpServers"])

    def test_merge_overwrites_slimyos_entry(self):
        existing = {
            "mcpServers": {
                "slimyos": {"command": "old", "args": []},
            }
        }
        config = mcp_configure.generate_claude_desktop_config(
            "/repo", "http://localhost:3003", existing
        )
        self.assertIn("slimyos", config["mcpServers"])
        self.assertNotEqual(config["mcpServers"]["slimyos"]["command"], "old")


class TestBackupManifestShape(unittest.TestCase):
    def test_backup_dir_contains_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "config.json"
            target.write_text('{"test": true}')
            backup_root = Path(tmp) / "backups"
            info = mcp_configure.create_backup(str(target), "test_client", backup_root)
            meta = json.loads((Path(info["backup_dir"]) / "metadata.json").read_text())
            self.assertEqual(meta["client"], "test_client")
            self.assertIn("sha256_before", meta)
            self.assertIn("target_path", meta)
            self.assertIn("restore_instructions", meta)

    def test_backup_dir_contains_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "config.json"
            target.write_text('{"test": true}')
            backup_root = Path(tmp) / "backups"
            info = mcp_configure.create_backup(str(target), "test_client", backup_root)
            original = Path(info["backup_dir"]) / "original"
            self.assertTrue(original.exists())
            self.assertEqual(original.read_text(), '{"test": true}')

    def test_backup_when_file_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nonexistent.json"
            backup_root = Path(tmp) / "backups"
            info = mcp_configure.create_backup(str(target), "test_client", backup_root)
            original_absent = Path(info["backup_dir"]) / "original_absent"
            self.assertTrue(original_absent.exists())


class TestRollbackManifestShape(unittest.TestCase):
    def test_rollback_restores_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "config.json"
            target.write_text('{"original": true}')
            backup_root = Path(tmp) / "backups"
            mcp_configure.create_backup(str(target), "test_client", backup_root)
            target.write_text('{"modified": true}')
            result = mcp_configure.rollback_latest(backup_root)
            self.assertEqual(result["status"], "OK")
            self.assertEqual(json.loads(target.read_text()), {"original": True})

    def test_rollback_removes_created_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "config.json"
            backup_root = Path(tmp) / "backups"
            mcp_configure.create_backup(str(target), "test_client", backup_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('{"created": true}')
            result = mcp_configure.rollback_latest(backup_root)
            self.assertEqual(result["status"], "OK")
            self.assertFalse(target.exists())

    def test_rollback_no_backups_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup_root = Path(tmp) / "backups"
            backup_root.mkdir()
            result = mcp_configure.rollback_latest(backup_root)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("no_backups_found", result["errors"])


class TestMissingClientIsWarn(unittest.TestCase):
    def test_missing_binary_is_warn(self):
        with tempfile.TemporaryDirectory() as home:
            from unittest.mock import patch
            with patch("adapters.mcp_configure.shutil.which", return_value=None):
                detected = mcp_configure.detect_config_paths(home_override=home)
            self.assertEqual(detected["claude_code"]["status"], "warn")
            self.assertEqual(detected["opencode"]["status"], "warn")
            self.assertEqual(detected["codex"]["status"], "warn")

    def test_missing_binary_not_fail(self):
        with tempfile.TemporaryDirectory() as home:
            from unittest.mock import patch
            with patch("adapters.mcp_configure.shutil.which", return_value=None):
                detected = mcp_configure.detect_config_paths(home_override=home)
            for key in ("claude_code", "opencode", "codex"):
                self.assertIn(detected[key]["status"], ("warn", "not_found"))


class TestUnknownConfigPathIsManualRequired(unittest.TestCase):
    def test_unknown_path_gives_manual_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = mcp_configure.run_configure(
                repo_root=".",
                proof_dir=tmp,
                mode="dry-run",
                home_override=tmp,
            )
            for client_key in ("claude_code", "opencode", "codex"):
                planned = json.loads((Path(tmp) / "planned_changes.json").read_text())
                self.assertEqual(
                    planned["clients"][client_key]["status"], "MANUAL_REQUIRED"
                )


class TestInvalidJSONNotOverwritten(unittest.TestCase):
    def test_invalid_existing_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".config" / "Claude" / "claude_desktop_config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("{invalid json")
            backup_root = Path(tmp) / "backups"
            result = mcp_configure.apply_claude_desktop_config(
                str(config_path), "/repo", "http://localhost:3003", backup_root
            )
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any("invalid_json" in e for e in result["errors"]))


class TestDryRunNoMutation(unittest.TestCase):
    def test_dry_run_does_not_modify_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".config" / "Claude" / "claude_desktop_config.json"
            config_path.parent.mkdir(parents=True)
            original_content = '{"mcpServers": {"existing": {"command": "test"}}}'
            config_path.write_text(original_content)
            result = mcp_configure.run_configure(
                repo_root=".",
                proof_dir=(tmp + "/proof"),
                mode="dry-run",
                home_override=tmp,
            )
            self.assertEqual(result["result"], "PASS")
            self.assertEqual(config_path.read_text(), original_content)


class TestApplyRequiresExplicitFlag(unittest.TestCase):
    def test_default_mode_is_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".config" / "Claude" / "claude_desktop_config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("{}")
            result = mcp_configure.run_configure(
                repo_root=".",
                proof_dir=(tmp + "/proof"),
                mode="dry-run",
                home_override=tmp,
            )
            self.assertEqual(result["mode"], "dry-run")
            self.assertEqual(config_path.read_text(), "{}")


class TestStatusMode(unittest.TestCase):
    def test_status_no_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".config" / "Claude" / "claude_desktop_config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text('{"mcpServers": {}}')
            result = mcp_configure.run_configure(
                repo_root=".",
                proof_dir=(tmp + "/proof"),
                mode="status",
                home_override=tmp,
            )
            self.assertEqual(result["result"], "PASS")
            self.assertEqual(config_path.read_text(), '{"mcpServers": {}}')
            self.assertIsNotNone(result["status_result"])
            sr = result["status_result"]
            self.assertEqual(sr["clients"]["claude_desktop"]["config_exists"], True)
            self.assertEqual(sr["clients"]["claude_desktop"]["slimyos_installed"], False)

    def test_status_detects_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".config" / "Claude" / "claude_desktop_config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps({
                "mcpServers": {
                    "slimyos": {"command": "/some/path", "args": [], "env": {}}
                }
            }))
            result = mcp_configure.run_configure(
                repo_root=".",
                proof_dir=(tmp + "/proof"),
                mode="status",
                home_override=tmp,
            )
            sr = result["status_result"]
            self.assertEqual(sr["clients"]["claude_desktop"]["slimyos_installed"], True)
            self.assertEqual(sr["clients"]["claude_desktop"]["status"], "installed")


class TestApplyAndRollbackRoundTrip(unittest.TestCase):
    def test_apply_creates_slimyos_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".config" / "Claude" / "claude_desktop_config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text('{"mcpServers": {"other": {"command": "x"}}}')
            backup_root = Path(tmp) / "backups"
            result = mcp_configure.apply_claude_desktop_config(
                str(config_path), "/repo", "http://localhost:3003", backup_root
            )
            self.assertEqual(result["status"], "OK")
            written = json.loads(config_path.read_text())
            self.assertIn("slimyos", written["mcpServers"])
            self.assertIn("other", written["mcpServers"])

    def test_apply_rollback_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".config" / "Claude" / "claude_desktop_config.json"
            config_path.parent.mkdir(parents=True)
            original = '{"mcpServers": {"old": {"command": "old"}}}'
            config_path.write_text(original)
            backup_root = Path(tmp) / "backups"
            apply_result = mcp_configure.apply_claude_desktop_config(
                str(config_path), "/repo", "http://localhost:3003", backup_root
            )
            self.assertEqual(apply_result["status"], "OK")
            rollback_result = mcp_configure.rollback_latest(backup_root)
            self.assertEqual(rollback_result["status"], "OK")
            self.assertEqual(config_path.read_text(), original)


class TestClientNotes(unittest.TestCase):
    def test_generate_client_notes(self):
        notes = mcp_configure.generate_client_notes("/repo", "http://localhost:3003")
        self.assertIn("generated_claude_code_notes.md", notes)
        self.assertIn("generated_opencode_notes.md", notes)
        self.assertIn("generated_codex_notes.md", notes)
        for content in notes.values():
            self.assertIn("MANUAL_REQUIRED", content)


class TestValidateJSON(unittest.TestCase):
    def test_valid_json(self):
        valid, err = mcp_configure.validate_json_string('{"a": 1}')
        self.assertTrue(valid)
        self.assertEqual(err, "")

    def test_invalid_json(self):
        valid, err = mcp_configure.validate_json_string("{bad")
        self.assertFalse(valid)
        self.assertNotEqual(err, "")


if __name__ == "__main__":
    unittest.main()
