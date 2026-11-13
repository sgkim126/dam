import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from dam.errors import DamError
from dam.model import new_yard
from dam.runtime import Runtime
from dam.store import Store


class RuntimeTests(unittest.TestCase):
    def test_blueprint_image_fingerprint_includes_copied_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / ".dam")
            root = store.blueprint_dir("coding")
            image = root / "image"
            image.mkdir(parents=True)
            (root / "Dockerfile").write_text("FROM $DAM_BASE_IMAGE\n")
            tool = image / "tool.sh"
            tool.write_text("#!/bin/sh\n")
            tool.chmod(0o644)
            runtime = Runtime(store, new_yard("dev", "coding", 501, 20))
            copied_modes = []

            def capture(argv, **kwargs):
                copied = Path(argv[-1]) / "image"
                copied_modes.append(
                    (
                        copied.stat().st_mode & 0o777,
                        (copied / "tool.sh").stat().st_mode & 0o777,
                    )
                )
                return SimpleNamespace(returncode=0)

            with (
                mock.patch("dam.runtime._inspect", return_value=None),
                mock.patch("dam.runtime.run", side_effect=capture),
            ):
                first = runtime._blueprint_image("base")
                tool.chmod(0o755)
                second = runtime._blueprint_image("base")
                image.chmod(0o700)
                third = runtime._blueprint_image("base")

            self.assertEqual(len({first, second, third}), 3)
            self.assertEqual(
                copied_modes, [(0o755, 0o644), (0o755, 0o755), (0o700, 0o755)]
            )

    def test_blueprint_image_fingerprint_follows_copied_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / ".dam")
            blueprint = store.blueprint_dir("coding")
            image = blueprint / "image"
            image.mkdir(parents=True)
            (blueprint / "Dockerfile").write_text("FROM $DAM_BASE_IMAGE\n")
            shared_file = root / "shared-config"
            shared_file.write_text("first")
            (image / "config").symlink_to(shared_file)
            shared_dir = root / "shared-assets"
            shared_dir.mkdir()
            (shared_dir / "data").write_text("one")
            (image / "assets").symlink_to(shared_dir, target_is_directory=True)
            runtime = Runtime(store, new_yard("dev", "coding", 501, 20))
            copied = []

            def capture(argv, **kwargs):
                staged = Path(argv[-1]) / "image"
                copied.append(
                    (
                        (staged / "config").read_text(),
                        (staged / "assets" / "data").read_text(),
                        (staged / "config").is_symlink(),
                        (staged / "assets").is_symlink(),
                    )
                )
                return SimpleNamespace(returncode=0)

            with (
                mock.patch("dam.runtime._inspect", return_value=None),
                mock.patch("dam.runtime.run", side_effect=capture),
            ):
                first = runtime._blueprint_image("base")
                shared_file.write_text("second")
                second = runtime._blueprint_image("base")
                (shared_dir / "data").write_text("two")
                third = runtime._blueprint_image("base")

            self.assertEqual(len({first, second, third}), 3)
            self.assertEqual(
                copied,
                [
                    ("first", "one", False, False),
                    ("second", "one", False, False),
                    ("second", "two", False, False),
                ],
            )

    def test_ownership_reports_which_label_mismatches(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / ".dam")
            runtime = Runtime(store, new_yard("dev", "coding", 501, 20))
            labels = {"io.dam.root": runtime.owner, "io.dam.yard": runtime.name}
            for kind in ("container", "volume"):
                for key, label in (
                    ("io.dam.root", "root"),
                    ("io.dam.yard", "yard"),
                ):
                    mismatched = {**labels, key: "other"}
                    data = (
                        {"Config": {"Labels": mismatched}}
                        if kind == "container"
                        else {"Labels": mismatched}
                    )
                    with self.subTest(kind=kind, label=label):
                        with self.assertRaises(DamError) as error:
                            runtime._owned(data, kind)
                        self.assertEqual(
                            str(error.exception),
                            f"Docker {kind} {label} label mismatch: dev",
                        )

    def test_create_container_uses_hostname_dam_and_mounts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "project"
            source.mkdir()
            state = new_yard("dev", "coding", 501, 20)
            state["mounts"]["project"] = str(source)
            runtime = Runtime(Store(root / ".dam"), state)
            with mock.patch("dam.runtime.run") as run:
                runtime._create_container("example:image")
            args = run.call_args.args[0]
            self.assertIn(
                ["--hostname", "dev"], [args[i : i + 2] for i in range(len(args))]
            )
            self.assertIn(
                ["--user", "dam"], [args[i : i + 2] for i in range(len(args))]
            )
            self.assertIn(
                f"type=bind,source={source},target=/mnt/project",
                args,
            )
            self.assertIn(
                f"type=volume,source={runtime.volume},target=/home/dam,volume-nocopy",
                args,
            )

    def test_distinct_yards_have_distinct_volumes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / ".dam")
            first = Runtime(store, new_yard("dev", "coding", 501, 20))
            second = Runtime(store, new_yard("test", "coding", 501, 20))
            self.assertNotEqual(first.volume, second.volume)

    def test_image_home_paths_are_read_without_mounting_the_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(
                Store(Path(directory) / ".dam"),
                new_yard("dev", "coding", 501, 20),
            )
            output = "/home/dam/tool\0/home/dam/.config/app\0"
            with mock.patch(
                "dam.runtime.run", return_value=SimpleNamespace(stdout=output)
            ) as execute:
                paths = runtime._image_home_paths("blueprint:image")
            self.assertEqual(paths, [".config/app", "tool"])
            command = execute.call_args.args[0]
            self.assertIn("blueprint:image", command)
            self.assertNotIn("--mount", command)

    def test_image_home_changes_sync_before_blueprint_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / ".dam")
            home = store.blueprint_dir("coding") / "home"
            (home / "config").mkdir(parents=True)
            (home / "config" / "key").write_text("blueprint")
            yard_dir = store.object_dir("yard", "dev")
            yard_dir.mkdir(parents=True)
            runtime = Runtime(store, new_yard("dev", "coding", 501, 20))
            scripts = []
            commands = []

            def capture(argv, **kwargs):
                commands.append(argv)
                spec = next(item for item in argv if "target=/sync.sh" in item)
                path = spec.split("source=", 1)[1].split(",target=", 1)[0]
                scripts.append(Path(path).read_text())
                return SimpleNamespace(returncode=0)

            with (
                mock.patch.object(
                    runtime,
                    "_image_home_paths",
                    side_effect=[["config", "tool"], ["config", "new-tool"]],
                ),
                mock.patch("dam.runtime.run", side_effect=capture),
            ):
                runtime._sync_home("image:first")
                runtime._sync_home("image:second")

            self.assertIn("cp -R -- /home/dam/tool /dam-home/tool", scripts[0])
            self.assertNotIn("cp -R -- /home/dam/config", scripts[0])
            self.assertIn(
                "cp -R -- /source/config/key /dam-home/config/key", scripts[0]
            )
            self.assertIn("rm -rf -- /dam-home/tool", scripts[1])
            self.assertIn("cp -R -- /home/dam/new-tool /dam-home/new-tool", scripts[1])
            self.assertTrue(
                any("target=/dam-home,volume-nocopy" in arg for arg in commands[0])
            )
            self.assertEqual(commands[1][-2:], ["image:second", "/sync.sh"])
            self.assertEqual(
                json.loads((yard_dir / "managed.json").read_text()),
                {"paths": ["config/key"], "image_paths": ["new-tool"]},
            )

    def test_failed_recreation_restores_stopped_container(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / ".dam")
            runtime = Runtime(store, new_yard("dev", "coding", 501, 20))
            old = {
                "State": {"Running": False},
                "Config": {"Image": "old", "Labels": {}},
            }
            calls = []

            def execute(argv, **kwargs):
                calls.append(argv)
                if argv[:3] == ["docker", "container", "start"]:
                    raise RuntimeError("start failed")
                return SimpleNamespace(returncode=0)

            with (
                mock.patch.object(runtime, "inspect", return_value=old),
                mock.patch.object(runtime, "_base_image", return_value="base"),
                mock.patch.object(runtime, "_blueprint_image", return_value="new"),
                mock.patch.object(runtime, "_ensure_volume"),
                mock.patch.object(runtime, "_sync_home") as sync_home,
                mock.patch.object(runtime, "_create_container"),
                mock.patch("dam.runtime.run", side_effect=execute),
                self.assertRaisesRegex(RuntimeError, "start failed"),
            ):
                runtime.ensure_running()
            sync_home.assert_called_once_with("new")
            renames = [
                call for call in calls if call[:3] == ["docker", "container", "rename"]
            ]
            self.assertEqual(len(renames), 2)
            self.assertEqual(renames[-1][-1], runtime.container)

    def test_home_sync_deletes_only_previously_managed_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / ".dam")
            state = new_yard("dev", "coding", 501, 20)
            root = store.blueprint_dir("coding")
            home = root / "home"
            home.mkdir(parents=True)
            (home / "new.txt").write_text("new")
            yard_dir = store.object_dir("yard", "dev")
            yard_dir.mkdir(parents=True)
            (yard_dir / "managed.json").write_text(json.dumps({"paths": ["old.txt"]}))
            runtime = Runtime(store, state)
            scripts = []

            def capture(argv, **kwargs):
                spec = next(item for item in argv if "target=/sync.sh" in item)
                path = spec.split("source=", 1)[1].split(",target=", 1)[0]
                scripts.append(Path(path).read_text())
                return SimpleNamespace(returncode=0)

            with (
                mock.patch.object(runtime, "_image_home_paths", return_value=[]),
                mock.patch("dam.runtime.run", side_effect=capture),
            ):
                runtime._sync_home("base")
            self.assertIn("rm -rf -- /dam-home/old.txt", scripts[0])
            self.assertIn("new.txt", scripts[0])
            self.assertEqual(
                json.loads((yard_dir / "managed.json").read_text())["paths"],
                ["new.txt"],
            )

    def test_home_sync_recovers_file_when_final_record_write_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / ".dam")
            home = store.blueprint_dir("coding") / "home"
            home.mkdir(parents=True)
            (home / "a").write_text("new")
            yard_dir = store.object_dir("yard", "dev")
            yard_dir.mkdir(parents=True)
            manifest = yard_dir / "managed.json"
            runtime = Runtime(store, new_yard("dev", "coding", 501, 20))
            write = store._atomic_json
            writes = 0

            def fail_final_write(path, state):
                nonlocal writes
                writes += 1
                if writes == 2:
                    raise OSError("record write failed")
                write(path, state)

            def check_pending(argv, **kwargs):
                self.assertEqual(
                    json.loads(manifest.read_text()),
                    {"paths": ["a"], "image_paths": ["tool"]},
                )
                return SimpleNamespace(returncode=0)

            with (
                mock.patch.object(runtime, "_image_home_paths", return_value=["tool"]),
                mock.patch.object(store, "_atomic_json", side_effect=fail_final_write),
                mock.patch("dam.runtime.run", side_effect=check_pending),
                self.assertRaisesRegex(OSError, "record write failed"),
            ):
                runtime._sync_home("base")

            (home / "a").unlink()
            scripts = []

            def capture(argv, **kwargs):
                spec = next(item for item in argv if "target=/sync.sh" in item)
                path = spec.split("source=", 1)[1].split(",target=", 1)[0]
                scripts.append(Path(path).read_text())
                return SimpleNamespace(returncode=0)

            with (
                mock.patch.object(runtime, "_image_home_paths", return_value=[]),
                mock.patch("dam.runtime.run", side_effect=capture),
            ):
                runtime._sync_home("base")
            self.assertIn("rm -rf -- /dam-home/a", scripts[0])
            self.assertIn("rm -rf -- /dam-home/tool", scripts[0])
            self.assertEqual(
                json.loads(manifest.read_text()),
                {"paths": [], "image_paths": []},
            )

    def test_corrupt_managed_paths_cannot_escape_home(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / ".dam")
            home = store.blueprint_dir("coding") / "home"
            home.mkdir(parents=True)
            yard_dir = store.object_dir("yard", "dev")
            yard_dir.mkdir(parents=True)
            (yard_dir / "managed.json").write_text(json.dumps({"paths": ["../other"]}))
            runtime = Runtime(store, new_yard("dev", "coding", 501, 20))
            with (
                mock.patch("dam.runtime.run") as run,
                self.assertRaises(DamError),
            ):
                runtime._sync_home("base")
            run.assert_not_called()
