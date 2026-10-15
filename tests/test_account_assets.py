"""Persistent identities and host-settings isolation in the packaged helpers."""

import os
import runpy
import tempfile
import unittest
from importlib import resources
from pathlib import Path

ASSETS = resources.files("dam").joinpath("resources", "container", "docker")
IMPORT = runpy.run_path(str(ASSETS.joinpath("import-settings.py")))
PREPARE = runpy.run_path(str(ASSETS.joinpath("prepare-settings.py")))


class AccountAssetsTests(unittest.TestCase):
    def test_profile_switch_changes_only_the_managed_block(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            bashrc = home / ".bashrc"
            bashrc.write_text("export MY_SETTING=keep\n")
            login = home / ".bash_profile"
            login.write_text("# keep existing login configuration\n")
            IMPORT["initialize_shell"](home, "alpha.sh")
            IMPORT["initialize_shell"](home, "beta.sh")
            text = bashrc.read_text()
            self.assertIn("export MY_SETTING=keep", text)
            self.assertNotIn("alpha.sh", text)
            self.assertIn("/etc/dam/profile/beta.sh", text)
            self.assertEqual(text.count("# >>> dam profile >>>"), 1)
            self.assertEqual(text.count("# >>> dam environment >>>"), 1)
            self.assertIn("[ -r /etc/dam/profile/beta.sh ]", text)
            self.assertEqual(login.read_text(), "# keep existing login configuration\n")
            IMPORT["initialize_shell"](home, None)
            self.assertNotIn("/etc/dam/profile/", bashrc.read_text())

    def test_shell_import_refuses_a_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            outside = home / "outside"
            outside.write_text("preserved")
            (home / ".bashrc").symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "symlink"):
                IMPORT["initialize_shell"](home, "work")
            self.assertEqual(outside.read_text(), "preserved")

    def test_snapshot_remains_bound_and_omits_authentication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            home = root / "host"
            codex = home / ".codex"
            codex.mkdir(parents=True)
            (codex / "auth.json").write_text('{"token":"keep-private"}')
            (codex / "history.jsonl").write_text("private-history")
            (codex / "config.toml").write_text(
                '[mcp_servers.example.env]\nAPI_KEY="private"\nOTHER="portable"\n'
            )
            destination = root / "settings"
            PREPARE["prepare"](home, destination)
            identity = destination.stat().st_ino
            (home / ".tmux.conf").write_text("set -g mouse on\n")
            PREPARE["prepare"](home, destination)
            self.assertEqual(destination.stat().st_ino, identity)
            self.assertFalse((destination / "codex/auth.json").exists())
            self.assertFalse((destination / "codex/history.jsonl").exists())
            config = (destination / "codex/config.toml").read_text()
            self.assertNotIn("private", config)
            self.assertIn("portable", config)
            self.assertEqual(
                (destination / "tmux.conf").read_text(), "set -g mouse on\n"
            )

    def test_settings_symlinks_cannot_copy_known_private_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            home = root / "host"
            codex = home / ".codex"
            codex.mkdir(parents=True)
            auth = codex / "auth.json"
            auth.write_text("secret-auth")
            sessions = codex / "sessions"
            sessions.mkdir()
            (sessions / "private.jsonl").write_text("private-history")
            external = root / "shared-skill"
            external.mkdir()
            (external / "SKILL.md").write_text("portable skill")
            skills = codex / "skills"
            skills.mkdir()
            (skills / "safe").symlink_to(external, target_is_directory=True)
            (skills / "unsafe").symlink_to(auth)
            os.link(auth, skills / "hardlink")
            (skills / "history").symlink_to(sessions / "private.jsonl")
            destination = root / "settings"
            PREPARE["prepare"](home, destination)
            self.assertEqual(
                (destination / "codex/skills/safe/SKILL.md").read_text(),
                "portable skill",
            )
            for name in ("unsafe", "hardlink", "history"):
                self.assertFalse((destination / "codex/skills" / name).exists())

    def test_user_sync_keeps_authentication_and_personal_codex_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = root / "settings"
            snapshot.mkdir()
            home = root / "user"
            codex = home / ".codex"
            codex.mkdir(parents=True)
            (codex / "auth.json").write_text("private-token")
            (codex / "config.toml").write_text('model="personal"\n')
            (codex / "history.jsonl").write_text("personal-history")
            IMPORT["import_user_settings"](snapshot, home, "work")
            self.assertEqual((codex / "auth.json").read_text(), "private-token")
            self.assertEqual((codex / "config.toml").read_text(), 'model="personal"\n')
            self.assertEqual((codex / "history.jsonl").read_text(), "personal-history")


if __name__ == "__main__":
    unittest.main()
