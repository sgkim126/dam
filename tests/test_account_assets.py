"""Persistent identities and host-settings isolation in the packaged helpers."""

import os
import runpy
import tempfile
import unittest
from importlib import resources
from pathlib import Path

ASSETS = resources.files("dam").joinpath("resources", "container", "docker")
PREPARE = runpy.run_path(str(ASSETS.joinpath("prepare-settings.py")))


class AccountAssetsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
