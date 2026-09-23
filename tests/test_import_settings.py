"""Check shared and per-user preference imports without touching real homes."""

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock


SOURCE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SOURCE_ROOT / "docker/import-settings.py"
SPEC = importlib.util.spec_from_file_location("dam_import_settings", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)


class ImportSettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dam-import-tests-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "host-settings"
        (self.source / "codex").mkdir(parents=True)
        self.home = self.root / "home/alice"
        self.system_config = self.root / "etc/codex/config.toml"
        self.write(
            self.source / "codex/config.toml",
            '''model = "shared-model"
[skills]
config = [
  { path = "/Users/host/.codex/skills/review", enabled = true },
  { path = "/Users/host/.agents/skills/testing", enabled = true },
  { path = "/Applications/private/SKILL.md", enabled = true }
]
[agents.reviewer]
config_file = "/Users/host/.codex/agents/reviewer.toml"
[agents.host_only]
config_file = "/Users/host/private/reviewer.toml"
''',
        )

    def write(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def run_import(self, home=None, *, system_only):
        with contextlib.redirect_stdout(io.StringIO()):
            settings.import_settings(
                self.source, home or self.home, self.system_config, system_only=system_only,
            )

    def test_common_config_references_shared_mount_assets(self):
        config, skipped = settings.portable_codex_config(
            self.source / "codex/config.toml", Path("/mnt/host-settings"),
        )
        parsed = tomllib.loads(config)
        self.assertEqual(
            [skill["path"] for skill in parsed["skills"]["config"]],
            ["/mnt/host-settings/codex/skills/review", "/mnt/host-settings/agents/skills/testing"],
        )
        self.assertEqual(
            parsed["agents"]["reviewer"]["config_file"],
            "/mnt/host-settings/codex/agents/reviewer.toml",
        )
        self.assertNotIn("host_only", parsed["agents"])
        self.assertNotIn("/Users/", config)
        self.assertIn("skills.config[2].path", skipped)

    def test_shared_asset_paths_cover_linux_homes_and_reject_traversal(self):
        common = Path("/mnt/host-settings")
        self.assertEqual(
            settings.shared_asset_path("/home/alice/.codex/rules/default.rules", common),
            "/mnt/host-settings/codex/rules/default.rules",
        )
        self.assertEqual(
            settings.shared_asset_path("/root/.agents/skills/review", common),
            "/mnt/host-settings/agents/skills/review",
        )
        self.assertIsNone(settings.shared_asset_path("/Users/a/.codex/skills/../auth.json", common))

    def test_system_only_never_creates_home_or_takes_user_lock(self):
        with mock.patch.object(settings.fcntl, "flock", side_effect=AssertionError("Unexpected home lock")):
            self.run_import(system_only=True)
        self.assertFalse(self.home.exists())
        self.assertTrue(self.system_config.is_file())

    def test_system_only_does_not_inspect_existing_home(self):
        # A non-directory home makes any home initialization fail immediately.
        self.write(self.home, "untouched root home marker")
        self.run_import(system_only=True)
        self.assertEqual(self.home.read_text(), "untouched root home marker")

    def test_user_only_preserves_local_state_and_never_writes_system(self):
        local_files = {
            ".codex/config.toml": 'model = "alice-model"\n',
            ".codex/auth.json": '{"token": "alice-only"}\n',
            ".codex/history.jsonl": '{"history": "alice"}\n',
            ".codex/skills/.system/local/SKILL.md": "system skill",
            ".codex/skills/custom/SKILL.md": "local skill",
            ".config/gh/hosts.yml": "local GitHub login",
            ".config/glab-cli/config.yml": "local GitLab login",
            ".bash_history": "private history\n",
        }
        for relative, content in local_files.items():
            self.write(self.home / relative, content)
        self.write(self.source / "codex/skills/review/SKILL.md", "shared skill")
        self.write(self.source / "nvim/init.lua", "vim.opt.number = true\n")
        self.write(self.system_config, "shared config sentinel")
        os.utime(self.system_config, ns=(1, 1))

        self.run_import(system_only=False)

        for relative, content in local_files.items():
            self.assertEqual((self.home / relative).read_text(), content, relative)
        self.assertEqual(self.system_config.read_text(), "shared config sentinel")
        self.assertEqual(self.system_config.stat().st_mtime_ns, 1)
        self.assertEqual((self.home / ".codex/skills/review/SKILL.md").read_text(), "shared skill")
        self.assertTrue((self.home / ".codex/skills/review").is_symlink())
        self.assertEqual((self.home / ".config/nvim/init.lua").read_text(), "vim.opt.number = true\n")
        self.assertTrue((self.home / ".local/state/dam-settings/import.lock").exists())

    def test_different_user_imports_leave_common_config_unchanged(self):
        self.run_import(system_only=True)
        expected = self.system_config.read_bytes()
        os.utime(self.system_config, ns=(1, 1))
        for name in ("alice", "bob"):
            home = self.root / "home" / name
            self.write(home / ".codex/config.toml", f'model = "{name}"\n')
            self.run_import(home=home, system_only=False)
            self.assertEqual((home / ".codex/config.toml").read_text(), f'model = "{name}"\n')
            self.assertEqual(self.system_config.read_bytes(), expected)
            self.assertEqual(self.system_config.stat().st_mtime_ns, 1)
        self.assertNotIn(str(self.root / "home"), expected.decode())

    def test_cli_modes_are_mutually_exclusive(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--system-only", "--user-only"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("not allowed with argument", result.stderr)

    def test_cli_requires_mode_before_importing_settings(self):
        with (
            mock.patch.object(sys, "argv", [str(SCRIPT)]),
            mock.patch.object(settings, "import_settings") as importer,
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            with self.assertRaises(SystemExit) as error:
                settings.main()
        self.assertEqual(error.exception.code, 2)
        self.assertIn("required", stderr.getvalue())
        importer.assert_not_called()

    def test_cli_uses_fixed_paths_for_each_mode(self):
        for flag, system_only in (("--system-only", True), ("--user-only", False)):
            with (
                self.subTest(flag=flag),
                mock.patch.object(sys, "argv", [str(SCRIPT), flag]),
                mock.patch.object(Path, "home", return_value=self.home),
                mock.patch.object(settings, "import_settings") as importer,
            ):
                settings.main()
                importer.assert_called_once_with(
                    Path("/mnt/host-settings"), self.home, Path("/etc/codex/config.toml"),
                    system_only=system_only,
                )

    def test_cli_rejects_path_overrides_before_importing_settings(self):
        for option in ("--source", "--home", "--system-config"):
            with (
                self.subTest(option=option),
                mock.patch.object(sys, "argv", [str(SCRIPT), "--user-only", option, str(self.root)]),
                mock.patch.object(settings, "import_settings") as importer,
                contextlib.redirect_stderr(io.StringIO()) as stderr,
            ):
                with self.assertRaises(SystemExit) as error:
                    settings.main()
                self.assertEqual(error.exception.code, 2)
                self.assertIn("unrecognized arguments", stderr.getvalue())
                importer.assert_not_called()

    def test_host_staging_rejects_arguments_before_copying(self):
        for option in ("--host-home", "--destination"):
            with (
                self.subTest(option=option),
                mock.patch.object(sys, "argv", ["prepare-settings.py", option, str(self.root)]),
                mock.patch.object(settings._shared, "prepare") as prepare,
            ):
                with self.assertRaisesRegex(SystemExit, "Usage: prepare-settings.py"):
                    settings._shared.main()
                prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
