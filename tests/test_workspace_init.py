from argparse import Namespace
from unittest.mock import patch

from runtime_test_support import RuntimeTestCase

from dam.commands import workspace_init
from dam.errors import DamError


class InitTests(RuntimeTestCase):
    def test_initializes_named_workspace_and_prepares_snapshot_once(self):
        args = Namespace(workspace="new")
        with patch.object(workspace_init, "prepare_settings") as prepare:
            workspace_init.run(args, self.store)
        prepare.assert_called_once()
        self.assertEqual(prepare.call_args.args[1], self.store.snapshot_dir("new"))
        self.assertEqual(self.store.load("new")["users"]["node"]["uid"], 1000)
        self.assertTrue(self.docker.containers["new"]["State"]["Running"])

    def test_existing_workspace_is_not_reset_or_resynchronized(self):
        before = self.store.load("dev")
        with (
            patch.object(workspace_init, "prepare_settings") as prepare,
            self.assertRaisesRegex(DamError, "already registered"),
        ):
            workspace_init.run(Namespace(workspace="dev"), self.store)
        prepare.assert_not_called()
        self.assertEqual(self.store.load("dev"), before)
        self.assertEqual(self.docker.calls, [])

    def test_failed_initialization_keeps_home_data_but_allows_retry(self):
        self.docker.fail = ("container", "create")
        args = Namespace(workspace="new")
        with patch.object(workspace_init, "prepare_settings"):
            with self.assertRaisesRegex(DamError, "injected"):
                workspace_init.run(args, self.store)
            self.assertNotIn("new", self.store.list_names())
            self.assertEqual(len(self.docker.volumes), 1)
            volume = next(iter(self.docker.volumes))
            workspace_init.run(args, self.store)
        self.assertIn("new", self.store.list_names())
        self.assertEqual(set(self.docker.volumes), {volume})

    def test_unowned_container_collision_does_not_register_or_copy_settings(self):
        self.docker.containers["new"] = {
            "Config": {
                "Labels": {},
            },
            "State": {
                "Running": True,
            },
        }
        with (
            patch.object(workspace_init, "prepare_settings") as prepare,
            self.assertRaisesRegex(DamError, "not owned"),
        ):
            workspace_init.run(Namespace(workspace="new"), self.store)
        self.assertNotIn("new", self.store.list_names())
        prepare.assert_not_called()
