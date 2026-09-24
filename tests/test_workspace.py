"""Workspace preparation changes only the root directory."""

import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "docker/workspace.py"
SPEC = importlib.util.spec_from_file_location("dam_workspace", SOURCE)
workspace_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workspace_module)


class WorkspacePermissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dam-workspace-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def test_cli_rejects_arguments_before_initializing_permissions(self):
        with (
            mock.patch.object(workspace_module.sys, "argv", [str(SOURCE), "--workspace", str(self.root)]),
            mock.patch.object(workspace_module.os, "setgroups") as setgroups,
            mock.patch.object(workspace_module, "prepare_workspace") as prepare,
        ):
            with self.assertRaisesRegex(SystemExit, "Usage: workspace.py"):
                workspace_module.main()
        setgroups.assert_not_called()
        prepare.assert_not_called()

    def test_workspace_preparation_leaves_existing_contents_and_links_untouched(self):
        workspace = self.root / "workspace"
        workspace.mkdir(mode=0o700)
        nested = workspace / "nested"
        nested.mkdir(mode=0o700)
        nested.chmod(0o1700)
        plain = nested / "file"
        plain.write_text("private")
        plain.chmod(0o600)
        executable = workspace / "run"
        executable.write_text("run")
        executable.chmod(0o700)
        outside = self.root / "private"
        outside.mkdir(mode=0o700)
        secret = outside / "secret"
        secret.write_text("private")
        secret.chmod(0o600)
        directory_link = workspace / "outside"
        directory_link.symlink_to(outside)
        file_link = workspace / "secret-link"
        file_link.symlink_to(secret)
        untouched = (nested, plain, executable, outside, secret, directory_link, file_link)
        before = {path: path.lstat() for path in untouched}
        owner = workspace.stat().st_uid
        with (
            mock.patch.object(os, "fchmod", wraps=os.fchmod) as chmod,
            mock.patch.object(os, "open", wraps=os.open) as opened,
            mock.patch.object(os, "listdir", side_effect=AssertionError("Workspace contents must not be listed")),
        ):
            workspace_module.prepare_workspace(workspace, os.getgid())
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(workspace.stat().st_uid, owner)
        self.assertEqual(workspace.stat().st_gid, os.getgid())
        self.assertEqual(stat.S_IMODE(workspace.stat().st_mode) & 0o777, 0o770)
        # Some macOS sandbox filesystems strip setgid bits. This unit test
        # checks the requested mode, not actual group inheritance.
        chmod.assert_called_once_with(mock.ANY, 0o2770)
        for path in untouched:
            with self.subTest(path=path):
                self.assertEqual(path.lstat(), before[path])
        self.assertEqual(plain.read_text(), "private")

    def test_workspace_group_change_preserves_owning_user(self):
        workspace = self.root / "workspace"
        workspace.mkdir(mode=0o700)
        shared_gid = os.getgid() + 1
        with mock.patch.object(os, "fchown") as chown:
            workspace_module.prepare_workspace(workspace, shared_gid)
        chown.assert_called_once_with(mock.ANY, -1, shared_gid)

    def test_symlink_workspace_root_is_rejected(self):
        target = self.root / "target"
        target.mkdir(mode=0o700)
        workspace = self.root / "workspace"
        workspace.symlink_to(target)
        before = target.stat()
        with self.assertRaises(OSError):
            workspace_module.prepare_workspace(workspace, os.getgid())
        self.assertTrue(workspace.is_symlink())
        self.assertEqual(target.stat(), before)


if __name__ == "__main__":
    unittest.main()
