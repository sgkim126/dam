"""Validate account data without creating system users or homes."""

from pathlib import Path
import runpy
import unittest


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


if __name__ == "__main__":
    unittest.main()
