import csv

from runtime_test_support import RuntimeTestCase

from dam.errors import DamError


class RuntimeTests(RuntimeTestCase):
    def test_initial_start_preserves_named_home_and_mounts_directories(self):
        host = self.root / "path, with spaces"
        host.mkdir()
        self.state["mounts"]["work"] = {
            "path": str(host),
            "shared": False,
        }
        self.store.save(self.state)
        self.runtime.ensure_running()
        create = next(
            call for call in self.docker.calls if call[1:3] == ["container", "create"]
        )
        mounts = [
            next(csv.reader([create[index + 1]]))
            for index, value in enumerate(create)
            if value == "--mount"
        ]
        self.assertIn(
            ["type=volume", f"source={self.runtime.volume}", "target=/home"], mounts
        )
        self.assertIn(["type=bind", f"source={host}", "target=/mnt/work"], mounts)
        self.assertTrue(
            any(
                "target=/etc/dam/profile" in mount and "readonly" in mount
                for mount in mounts
            )
        )
        self.assertTrue(
            any(
                f"source={self.store.workspace_dir('dev')}" in mount for mount in mounts
            )
        )
        self.assertTrue(self.runtime.is_running())
        self.assertNotIn("--privileged", create)

    def test_stopped_container_starts_without_rebuild_or_recreation(self):
        before = self.running()
        self.runtime.stop()
        self.docker.calls.clear()
        self.runtime.ensure_running()
        self.assertEqual(self.runtime.inspect()["Id"], before["Id"])
        self.assertFalse(
            any(
                call[1] == "build" or call[1:3] == ["container", "create"]
                for call in self.docker.calls
            )
        )

    def test_missing_source_fails_before_stopping_container(self):
        before = self.running()
        self.state["mounts"]["missing"] = {
            "path": str(self.root / "absent"),
            "shared": False,
        }
        with self.assertRaisesRegex(DamError, "Bind mount source does not exist"):
            self.runtime.recreate()
        self.assertEqual(self.docker.calls, [])
        self.assertTrue(self.docker.containers["dev"]["State"]["Running"])
        self.assertEqual(self.docker.containers["dev"]["Id"], before["Id"])

    def test_unowned_container_is_never_modified(self):
        self.running()
        self.docker.containers["dev"]["Config"]["Labels"] = {}
        with self.assertRaisesRegex(DamError, "not owned"):
            self.runtime.down()
        self.assertEqual([call[2] for call in self.docker.calls], ["inspect"])
        self.assertIn("dev", self.docker.containers)

    def test_daemon_failure_is_not_treated_as_absent_image_or_container(self):
        self.docker.daemon_error = True
        with self.assertRaisesRegex(DamError, "Docker daemon"):
            self.runtime.ensure_running()
        self.assertEqual(len(self.docker.calls), 1)
        self.assertEqual(self.docker.images, set())

    def test_failed_recreation_restores_old_container_and_running_state(self):
        before = self.running()
        self.docker.fail = ("container", "create")
        with self.assertRaisesRegex(DamError, "injected"):
            self.runtime.recreate()
        self.assertEqual(set(self.docker.containers), {"dev"})
        self.assertEqual(self.runtime.inspect()["Id"], before["Id"])
        self.assertTrue(self.runtime.is_running())
        self.assertIn(self.runtime.volume, self.docker.volumes)

    def test_exec_preserves_arguments_and_does_not_implicitly_start(self):
        self.runtime.exec(
            ["printf", "%s", "$(literal) with spaces"], user="alice", capture=True
        )
        self.assertEqual(
            self.docker.calls,
            [
                [
                    "docker",
                    "container",
                    "exec",
                    "--user",
                    "alice",
                    "dev",
                    "dam-user-env",
                    "printf",
                    "%s",
                    "$(literal) with spaces",
                ]
            ],
        )

    def test_regular_file_mount_is_supported(self):
        host = self.root / "tool.conf"
        host.write_text("host config")
        self.state["mounts"]["tool.conf"] = {
            "path": str(host),
            "shared": False,
        }
        self.store.save(self.state)
        self.runtime.ensure_running()
        create = next(
            call for call in self.docker.calls if call[1:3] == ["container", "create"]
        )
        self.assertTrue(
            any(
                f"source={host}" in argument and "target=/mnt/tool.conf" in argument
                for argument in create
            )
        )

    def test_failed_container_rename_restores_running_state(self):
        before = self.running()
        self.docker.fail = ("container", "rename")
        with self.assertRaisesRegex(DamError, "injected"):
            self.runtime.recreate()
        self.assertEqual(set(self.docker.containers), {"dev"})
        self.assertEqual(self.runtime.inspect()["Id"], before["Id"])
        self.assertTrue(self.runtime.is_running())

    def test_stopped_mount_configuration_changes_apply_on_next_start(self):
        before = self.running()
        self.runtime.stop()
        host = self.root / "new-source"
        host.mkdir()
        self.state["mounts"]["work"] = {
            "path": str(host),
            "shared": False,
        }
        self.store.save(self.state)
        self.docker.calls.clear()
        self.runtime.ensure_running()
        self.assertNotEqual(self.runtime.inspect()["Id"], before["Id"])
        self.assertTrue(self.runtime.is_running())
        create = next(
            call for call in self.docker.calls if call[1:3] == ["container", "create"]
        )
        self.assertTrue(
            any(
                f"source={host}" in argument and "target=/mnt/work" in argument
                for argument in create
            )
        )
        self.assertEqual(set(self.docker.volumes), {self.runtime.volume})
        self.assertEqual(set(self.docker.containers), {"dev"})

    def test_sharing_only_change_does_not_recreate_container_on_start(self):
        host = self.root / "shared"
        host.mkdir()
        self.state["mounts"]["work"] = {
            "path": str(host),
            "shared": False,
        }
        self.store.save(self.state)
        before = self.running()
        self.runtime.stop()
        self.state["mounts"]["work"]["shared"] = True
        self.store.save(self.state)
        self.docker.calls.clear()
        self.runtime.ensure_running()
        self.assertEqual(self.runtime.inspect()["Id"], before["Id"])
        self.assertFalse(
            any(call[1:3] == ["container", "create"] for call in self.docker.calls)
        )

    def test_running_mount_configuration_mismatch_never_recreates_implicitly(self):
        before = self.running()
        host = self.root / "different"
        host.mkdir()
        self.state["mounts"]["work"] = {
            "path": str(host),
            "shared": False,
        }
        self.store.save(self.state)
        with self.assertRaisesRegex(DamError, "different mount configuration"):
            self.runtime.ensure_running()
        self.assertEqual(self.docker.containers["dev"]["Id"], before["Id"])
        self.assertTrue(all(call[2] == "inspect" for call in self.docker.calls))

    def test_host_settings_is_available_as_a_user_mount_name(self):
        host = self.root / "own-settings"
        host.mkdir()
        self.state["mounts"]["host-settings"] = {
            "path": str(host),
            "shared": False,
        }
        self.store.save(self.state)
        self.runtime.ensure_running()
        create = next(
            call for call in self.docker.calls if call[1:3] == ["container", "create"]
        )
        mounts = [
            next(csv.reader([create[index + 1]]))
            for index, value in enumerate(create)
            if value == "--mount"
        ]
        self.assertIn(
            ["type=bind", f"source={host}", "target=/mnt/host-settings"], mounts
        )
        self.assertIn(
            [
                "type=bind",
                f"source={self.store.snapshot_dir('dev')}",
                "target=/etc/dam/host-settings",
                "readonly",
            ],
            mounts,
        )
