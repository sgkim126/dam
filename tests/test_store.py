import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from dam.errors import DamError, UsageError
from dam.model import new_map, new_yard
from dam.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name) / ".dam")

    def test_reads_do_not_create_configuration(self):
        self.assertEqual(self.store.list_objects("yard"), [])
        with self.assertRaises(DamError):
            self.store.load_object("yard", "dev")
        self.assertFalse(self.store.root.exists())

    def test_atomic_update_keeps_previous_state_on_replace_failure(self):
        state = new_yard("dev", "coding", 501, 20)
        with self.store.registry_lock():
            self.store.save_object("yard", state, create=True)
        changed = new_yard("dev", "other", 501, 20)
        with (
            mock.patch.object(Path, "replace", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
            self.store.registry_lock(),
        ):
            self.store.save_object("yard", changed)
        self.assertEqual(self.store.load_object("yard", "dev"), state)
        self.assertEqual(
            [path.name for path in self.store.object_dir("yard", "dev").iterdir()],
            ["yard.json"],
        )

    def test_lock_serializes_updates(self):
        first = threading.Event()
        release = threading.Event()
        second = threading.Event()

        def hold():
            with self.store.registry_lock():
                first.set()
                self.assertTrue(release.wait(3))

        def wait():
            self.assertTrue(first.wait(3))
            with Store(self.store.root).registry_lock():
                second.set()

        with ThreadPoolExecutor(max_workers=2) as workers:
            a = workers.submit(hold)
            b = workers.submit(wait)
            self.assertTrue(first.wait(3))
            self.assertFalse(second.wait(0.1))
            release.set()
            a.result(timeout=3)
            b.result(timeout=3)
        self.assertTrue(second.is_set())

    def test_invalid_map_file_is_rejected(self):
        state = new_map("work")
        with self.store.registry_lock():
            self.store.save_object("map", state, create=True)
        path = self.store.object_path("map", "work")
        state["pins"] = [{"name": "bad", "yard": "dev", "path": "relative"}]
        path.write_text(json.dumps(state))
        with self.assertRaises(UsageError):
            self.store.load_object("map", "work")
