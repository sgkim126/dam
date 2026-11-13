import tempfile
import unittest
from pathlib import Path

from dam.errors import DamError, UsageError
from dam.model import new_map, new_yard, validate_container_path, validate_object
from dam.store import Store


class ObjectStoreTests(unittest.TestCase):
    def test_yard_and_map_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / ".dam")
            yard = new_yard("dev", "coding", 501, 20)
            store.save_object("yard", yard, create=True)
            with self.assertRaises(DamError):
                store.save_object("yard", yard, create=True)
            self.assertEqual(store.load_object("yard", "dev"), yard)
            state = new_map("work")
            state["pins"].append({"name": "dev", "yard": "dev", "path": "/home/dam"})
            store.save_object("map", state, create=True)
            self.assertEqual(store.load_object("map", "work"), state)

    def test_yard_name_must_be_hostname(self):
        with self.assertRaises(UsageError):
            new_yard("dev_1", "coding", 501, 20)

    def test_container_path_reports_each_invalid_kind(self):
        for path, message in (
            (None, "Container path must be a string"),
            ("relative", "Container path must be absolute"),
            ("/home/\0dam", "Container path must not contain NUL bytes"),
        ):
            with self.subTest(path=path), self.assertRaises(UsageError) as error:
                validate_container_path(path)
            self.assertEqual(str(error.exception), message)

    def test_mount_source_reports_each_invalid_kind(self):
        for source, message in (
            (None, "Mount source must be a string: project"),
            ("relative", "Mount source must be absolute: project"),
            ("/home/\0project", "Mount source must not contain NUL bytes: project"),
        ):
            with self.subTest(source=source):
                yard = new_yard("dev", "coding", 501, 20)
                yard["mounts"]["project"] = source
                with self.assertRaises(UsageError) as error:
                    validate_object("yard", yard)
                self.assertEqual(str(error.exception), message)

    def test_map_rejects_duplicate_pins(self):
        state = new_map("work")
        state["pins"] = [
            {"name": "dev", "yard": "dev", "path": "/home/dam"},
            {"name": "dev", "yard": "other", "path": "/tmp"},
        ]
        with self.assertRaises(UsageError):
            validate_object("map", state)
