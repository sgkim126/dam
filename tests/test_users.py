"""Validate account data without creating system users or homes."""

from contextlib import nullcontext
import errno
import json
import os
from pathlib import Path
import runpy
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


users = runpy.run_path(str(Path(__file__).resolve().parents[1] / "docker/users.py"))


class RegistryValidationTests(unittest.TestCase):
    def test_duplicate_ids_and_missing_fields_are_rejected(self):
        for state in (
            {"accounts": {"node": {"uid": 1000, "gid": 1000}}},
            {"shared_gid": 100, "accounts": {
                "node": {"uid": 1000, "gid": 1000},
                "alice": {"uid": 2000, "gid": 2000},
                "bob": {"uid": 2000, "gid": 2001},
            }},
        ):
            with self.subTest(state=state), self.assertRaises(ValueError):
                users["validate_registry"](state)

    def test_shared_group_id_must_be_positive(self):
        for gid in (0, -1, True):
            state = {"shared_gid": gid, "accounts": {"node": {"uid": 1000, "gid": 1000}}}
            with self.subTest(gid=gid), self.assertRaises(ValueError):
                users["validate_registry"](state)


class RegistryDurabilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dam-registry-tests-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.registry = self.root / "users.json"
        self.state = {"shared_gid": 100, "accounts": {"node": {"uid": 1000, "gid": 1000}}}
        self.globals = users["save_registry"].__globals__
        patcher = mock.patch.dict(self.globals, REGISTRY_DIR=self.root, REGISTRY=self.registry)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_registry_is_replaced_between_file_and_directory_sync(self):
        real_fsync = os.fsync
        for previous in (None, {"previous": "registry"}):
            with self.subTest(previous=previous):
                if previous is None:
                    self.registry.unlink(missing_ok=True)
                else:
                    self.registry.write_text(json.dumps(previous))
                observed = []

                def fsync(fd):
                    kind = "directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
                    state = json.loads(self.registry.read_text()) if self.registry.exists() else None
                    observed.append((kind, state))
                    real_fsync(fd)

                with mock.patch.object(os, "fsync", side_effect=fsync):
                    users["save_registry"](self.state)

                self.assertEqual(observed, [("file", previous), ("directory", self.state)])
                self.assertEqual(json.loads(self.registry.read_text()), self.state)

    def test_directory_sync_failure_stops_account_initialization_and_closes_descriptor(self):
        real_fsync = os.fsync
        directory_fds = []

        def fsync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                directory_fds.append(fd)
                raise OSError(errno.EIO, "Directory sync failed")
            real_fsync(fd)

        ensure_account = mock.Mock()
        with (
            mock.patch.dict(self.globals, registry_lock=nullcontext,
                            initial_registry=lambda: self.state, ensure_account=ensure_account),
            mock.patch.object(self.globals["grp"], "getgrnam", return_value=SimpleNamespace(gr_gid=100)),
            mock.patch.object(self.globals["subprocess"], "run") as run,
            mock.patch.object(os, "fsync", side_effect=fsync),
        ):
            with self.assertRaisesRegex(OSError, "Directory sync failed"):
                users["synchronize"]()

        ensure_account.assert_not_called()
        run.assert_not_called()
        self.assertEqual(len(directory_fds), 1)
        with self.assertRaises(OSError) as caught:
            os.fstat(directory_fds[0])
        self.assertEqual(caught.exception.errno, errno.EBADF)
        self.assertEqual(list(self.root.iterdir()), [self.registry])


if __name__ == "__main__":
    unittest.main()
