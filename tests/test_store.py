import fcntl
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from unittest import mock

from dam.errors import DamError, UsageError
from dam.model import new_workspace, references_to_user
from dam.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "dam")

    def test_read_only_commands_do_not_create_directories(self):
        self.assertEqual(self.store.list_names(), [])
        with self.assertRaises(DamError):
            self.store.load("dev")
        self.assertFalse(self.store.root.exists())

    def test_create_then_atomic_save_preserves_tombstones(self):
        state = new_workspace("dev")
        state["users"]["alice"] = {
            "uid": 2000,
            "gid": 2000,
            "active": False,
            "profile": "gone.sh",
        }
        self.store.create(state)
        with self.assertRaises(DamError):
            self.store.create(state)
        self.assertEqual(self.store.load("dev"), state)
        self.assertEqual(self.store.list_names(), ["dev"])
        self.assertEqual(self.store.root.stat().st_mode & 0o777, 0o700)

    def test_save_requires_registered_workspace(self):
        with self.assertRaisesRegex(DamError, "^Workspace is not registered: dev$"):
            self.store.save(new_workspace("dev"))
        self.assertFalse(self.store.workspace_dir("dev").exists())
        self.assertEqual(self.store.list_names(), [])

    def test_save_updates_workspace_created_by_another_store(self):
        state = new_workspace("dev")
        self.store.create(state)
        changed = deepcopy(state)
        changed["users"]["node"]["profile"] = "other.sh"

        Store(self.store.root).save(changed)

        self.assertEqual(self.store.load("dev"), changed)

    def test_locked_workspace_validates_registration_and_saved_state(self):
        state = new_workspace("dev")
        invalid = deepcopy(state)
        invalid["shared_gid"] = 0
        changed = deepcopy(state)
        changed["users"]["node"]["profile"] = "other.sh"

        with self.store.lock("dev") as workspace:
            with self.assertRaisesRegex(DamError, "^Workspace is not registered: dev$"):
                workspace.save(state)
            with self.assertRaises(UsageError):
                workspace.create(invalid)
            self.assertFalse(self.store.workspace_dir("dev").exists())

            workspace.create(state)
            with self.assertRaisesRegex(
                DamError, "^Workspace is already registered: dev$"
            ):
                workspace.create(changed)
            self.assertEqual(workspace.load(), state)
            with self.assertRaises(UsageError):
                workspace.save(invalid)
            self.assertEqual(workspace.load(), state)

            workspace.save(changed)
            self.assertEqual(workspace.load(), changed)
        self.assertEqual(self.store.load("dev"), changed)

    def test_locked_workspace_rejects_another_workspace_name(self):
        state = new_workspace("dev")
        other = new_workspace("other")
        self.store.create(state)
        self.store.create(other)
        changed = deepcopy(other)
        changed["users"]["node"]["profile"] = "other.sh"

        with self.store.lock("dev") as workspace:
            for operation in (workspace.create, workspace.save):
                with (
                    self.subTest(operation=operation.__name__),
                    self.assertRaisesRegex(
                        DamError, "^Workspace name does not match its lock: dev$"
                    ),
                ):
                    operation(changed)
            self.assertEqual(workspace.load(), state)
        self.assertEqual(self.store.load("other"), other)

    def test_locked_workspace_cannot_be_used_after_scope_exits(self):
        state = new_workspace("dev")
        self.store.create(state)

        for aborted in (False, True):
            with self.subTest(aborted=aborted):
                expected = (
                    self.assertRaisesRegex(RuntimeError, "^aborted$")
                    if aborted
                    else nullcontext()
                )
                with expected, self.store.lock("dev") as workspace:
                    self.assertEqual(workspace.load(), state)
                    if aborted:
                        raise RuntimeError("aborted")
                for operation, args in (
                    (workspace.load, ()),
                    (workspace.create, (state,)),
                    (workspace.save, (state,)),
                ):
                    with (
                        self.subTest(operation=operation.__name__),
                        self.assertRaisesRegex(
                            DamError, "^Workspace lock is no longer held: dev$"
                        ),
                    ):
                        operation(*args)
                self.assertEqual(self.store.load("dev"), state)

    def test_locked_read_modify_save_preserves_concurrent_changes(self):
        initial = new_workspace("dev")
        self.store.create(initial)
        other_store = Store(self.store.root)
        first_loaded = threading.Event()
        finish_first = threading.Event()
        second_waiting_or_finished = threading.Event()
        second_waiting = threading.Event()
        second_loading = threading.Event()
        flock = fcntl.flock
        lock_owner = None

        def update_first():
            with self.store.lock("dev") as workspace:
                state = workspace.load()
                state["users"]["node"]["profile"] = "other.sh"
                first_loaded.set()
                if not finish_first.wait(timeout=5):
                    raise TimeoutError("First update was not released")
                workspace.save(state)

        def update_second():
            try:
                with other_store.lock("dev") as workspace:
                    second_loading.set()
                    state = workspace.load()
                    state["shared_gid"] = 200
                    workspace.save(state)
            finally:
                second_waiting_or_finished.set()

        def observe_lock_contention(fd, operation):
            nonlocal lock_owner
            if operation != fcntl.LOCK_EX:
                if operation == fcntl.LOCK_UN:
                    lock_owner = None
                return flock(fd, operation)
            if lock_owner == threading.get_ident():
                raise AssertionError("Workspace lock was acquired twice")
            try:
                flock(fd, operation | fcntl.LOCK_NB)
            except BlockingIOError:
                second_waiting.set()
                second_waiting_or_finished.set()
                flock(fd, operation)
            lock_owner = threading.get_ident()

        with (
            mock.patch("dam.store.fcntl.flock", side_effect=observe_lock_contention),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first_result = executor.submit(update_first)
            try:
                self.assertTrue(first_loaded.wait(timeout=5))
                second_result = executor.submit(update_second)
                self.assertTrue(second_waiting_or_finished.wait(timeout=5))
                self.assertTrue(second_waiting.is_set())
                self.assertFalse(second_loading.is_set())
                self.assertFalse(second_result.done())
            finally:
                finish_first.set()
            first_result.result(timeout=5)
            second_result.result(timeout=5)

        expected = deepcopy(initial)
        expected["users"]["node"]["profile"] = "other.sh"
        expected["shared_gid"] = 200
        self.assertTrue(second_loading.is_set())
        self.assertEqual(self.store.load("dev"), expected)

    def test_concurrent_create_does_not_overwrite_registered_state(self):
        first = new_workspace("dev")
        second = deepcopy(first)
        second["users"]["node"]["profile"] = "other.sh"
        other_store = Store(self.store.root)
        first_saving = threading.Event()
        finish_first = threading.Event()
        second_waiting_or_finished = threading.Event()
        save = self.store._save_locked
        flock = fcntl.flock
        lock_owner = None

        def pause_first_save(state):
            first_saving.set()
            if not finish_first.wait(timeout=5):
                raise TimeoutError("First registration was not released")
            save(state)

        def observe_lock_contention(fd, operation):
            nonlocal lock_owner
            if operation != fcntl.LOCK_EX:
                if operation == fcntl.LOCK_UN:
                    lock_owner = None
                return flock(fd, operation)
            if lock_owner == threading.get_ident():
                raise AssertionError("Workspace lock was acquired twice")
            try:
                flock(fd, operation | fcntl.LOCK_NB)
            except BlockingIOError:
                second_waiting_or_finished.set()
                flock(fd, operation)
            lock_owner = threading.get_ident()

        def create_second():
            try:
                other_store.create(second)
            finally:
                second_waiting_or_finished.set()

        with (
            mock.patch.object(self.store, "_save_locked", side_effect=pause_first_save),
            mock.patch("dam.store.fcntl.flock", side_effect=observe_lock_contention),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first_result = executor.submit(self.store.create, first)
            try:
                self.assertTrue(first_saving.wait(timeout=5))
                second_result = executor.submit(create_second)
                self.assertTrue(second_waiting_or_finished.wait(timeout=5))
            finally:
                finish_first.set()
            first_result.result(timeout=5)
            with self.assertRaisesRegex(
                DamError, "^Workspace is already registered: dev$"
            ):
                second_result.result(timeout=5)
        self.assertEqual(self.store.load("dev"), first)

    def test_save_waits_for_create_to_finish_registration(self):
        first = new_workspace("dev")
        changed = deepcopy(first)
        changed["users"]["node"]["profile"] = "other.sh"
        other_store = Store(self.store.root)
        first_saving = threading.Event()
        finish_first = threading.Event()
        second_waiting_or_finished = threading.Event()
        second_waiting = threading.Event()
        save = self.store._save_locked
        flock = fcntl.flock
        lock_owner = None

        def pause_first_save(state):
            first_saving.set()
            if not finish_first.wait(timeout=5):
                raise TimeoutError("First registration was not released")
            save(state)

        def observe_lock_contention(fd, operation):
            nonlocal lock_owner
            if operation != fcntl.LOCK_EX:
                if operation == fcntl.LOCK_UN:
                    lock_owner = None
                return flock(fd, operation)
            if lock_owner == threading.get_ident():
                raise AssertionError("Workspace lock was acquired twice")
            try:
                flock(fd, operation | fcntl.LOCK_NB)
            except BlockingIOError:
                second_waiting.set()
                second_waiting_or_finished.set()
                flock(fd, operation)
            lock_owner = threading.get_ident()

        def save_second():
            try:
                other_store.save(changed)
            finally:
                second_waiting_or_finished.set()

        with (
            mock.patch.object(self.store, "_save_locked", side_effect=pause_first_save),
            mock.patch("dam.store.fcntl.flock", side_effect=observe_lock_contention),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first_result = executor.submit(self.store.create, first)
            try:
                self.assertTrue(first_saving.wait(timeout=5))
                second_result = executor.submit(save_second)
                self.assertTrue(second_waiting_or_finished.wait(timeout=5))
                self.assertTrue(second_waiting.is_set())
                self.assertFalse(second_result.done())
                self.assertFalse(
                    (self.store.workspace_dir("dev") / "workspace.json").exists()
                )
            finally:
                finish_first.set()
            first_result.result(timeout=5)
            second_result.result(timeout=5)
        self.assertEqual(self.store.load("dev"), changed)

    def test_failed_replace_keeps_old_state_and_cleans_temporary(self):
        state = new_workspace("dev")
        self.store.create(state)
        changed = deepcopy(state)
        changed["users"]["node"]["profile"] = "dev.sh"
        with (
            mock.patch.object(Path, "replace", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            self.store.save(changed)
        self.assertEqual(self.store.load("dev"), state)
        self.assertEqual(
            [p.name for p in self.store.workspace_dir("dev").iterdir()],
            ["workspace.json"],
        )

    def test_corrupt_registry_is_not_silently_replaced(self):
        self.store.create(new_workspace("dev"))
        path = self.store.workspace_dir("dev") / "workspace.json"
        path.write_text("not json")
        with self.assertRaises(DamError):
            self.store.load("dev")
        self.assertEqual(path.read_text(), "not json")

    def test_duplicate_ids_include_inactive_accounts(self):
        state = new_workspace("dev")
        state["users"]["alice"] = {
            "uid": 1000,
            "gid": 2000,
            "active": False,
            "profile": None,
        }
        with self.assertRaises(UsageError):
            self.store.create(state)

    def test_invalid_workspace_names_rejected(self):
        for name in ("../dev", "", "한글", "has space", ".hidden"):
            with self.subTest(name=name), self.assertRaises(UsageError):
                new_workspace(name)

    def test_saved_session_user_reference(self):
        state = new_workspace("dev")
        state["sessions"]["work"] = {
            "windows": [
                {
                    "name": "main",
                    "username": "node",
                    "path": "/home/node",
                }
            ]
        }
        self.store.create(state)
        self.assertEqual(references_to_user(state, "node"), ["work"])
        state["sessions"]["work"]["windows"][0]["name"] = "other"
        with self.assertRaises(UsageError):
            self.store.save(state)

    def test_load_rejects_non_string_window_username(self):
        state = new_workspace("dev")
        state["sessions"]["work"] = {
            "windows": [
                {"name": "main", "username": "node", "path": "/home/node"},
                {"name": "editor", "username": "node", "path": "/tmp"},
            ]
        }
        self.store.create(state)
        path = self.store.workspace_dir("dev") / "workspace.json"
        for username in ([], {}, None, 123, True, 1.5):
            with self.subTest(username=username):
                state["sessions"]["work"]["windows"][1]["username"] = username
                path.write_text(json.dumps(state), encoding="utf-8")
                with self.assertRaisesRegex(
                    UsageError, "^Window username must be a string: editor$"
                ):
                    self.store.load("dev")
