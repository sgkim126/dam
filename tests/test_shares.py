import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dam

ASSET = Path(dam.__file__).parent / "resources/container/docker/shares.py"
spec = importlib.util.spec_from_file_location("dam_test_shares", ASSET)
shares = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shares)


class ShareRootTests(unittest.TestCase):
    def test_sharing_keeps_existing_mode_bits_and_does_not_visit_children(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child = root / "private"
            child.write_text("keep")
            child.chmod(0o600)
            root.chmod(0o1700)
            with (
                patch.object(shares.os, "fchown") as chown,
                patch.object(shares.os, "fchmod") as chmod,
                patch.object(shares.os, "getgroups", return_value=[0]),
                patch.object(shares.os, "setgroups") as setgroups,
            ):
                shares.apply(root, 100)
            setgroups.assert_called_once_with([0, 100])
            self.assertEqual(chown.call_args.args[1:], (-1, 100))
            self.assertEqual(chmod.call_args.args[1], 0o3770)
            self.assertEqual(stat.S_IMODE(child.stat().st_mode), 0o600)

    def test_symbolic_link_mount_root_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            alias = root / "alias"
            alias.symlink_to(target)
            with self.assertRaises(OSError):
                shares.apply(alias, os.getgid())
