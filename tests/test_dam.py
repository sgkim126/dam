"""Exercise workspace selection without starting Docker or importing host settings.

Run with: python3 -m unittest discover -s tests -v
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[1]


class DamLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dam-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.launcher_root = self.root / "launcher"
        self.launcher_root.mkdir()
        self.workspaces_root = self.launcher_root / "workspaces"
        self.launcher = self.launcher_root / "dam"
        shutil.copy2(SOURCE_ROOT / "dam", self.launcher)
        shutil.copy2(SOURCE_ROOT / "compose.yaml", self.launcher_root / "compose.yaml")
        docker_directory = self.launcher_root / "docker"
        docker_directory.mkdir()
        (docker_directory / "prepare-settings.py").write_text(
            textwrap.dedent(
                """\
                import json
                import os
                from pathlib import Path

                with open(os.environ["DAM_TEST_EVENTS"], "a") as events:
                    events.write(json.dumps({"kind": "prepare"}) + "\\n")
                (Path(__file__).resolve().parents[1] / ".host-settings").mkdir(exist_ok=True)
                """
            )
        )
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fake_docker = self.bin / "docker"
        fake_docker.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys

                args = sys.argv[1:]
                event = {
                    "kind": "docker",
                    "args": args,
                    "workspace": os.environ.get("DAM_WORKSPACE_PATH"),
                }
                with open(os.environ["DAM_TEST_EVENTS"], "a") as events:
                    events.write(json.dumps(event) + "\\n")
                actions = {"up", "exec", "build", "config", "ps", "stop", "down", "logs"}
                action = next((arg for arg in args if arg in actions), None)
                if action == os.environ.get("DAM_TEST_FAIL_ACTION"):
                    sys.exit(19)
                if action == "ps" and os.environ.get("DAM_TEST_RUNNING") == "1":
                    print("fake-running-container")
                """
            )
        )
        fake_docker.chmod(0o755)
        self.events_path = self.root / "events.jsonl"
        self.env = dict(os.environ)
        self.env.update(
            PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
            DAM_TEST_EVENTS=str(self.events_path),
            HOME=str(self.root / "home"),
        )
        (self.root / "home").mkdir()
        # Never inherit settings from a manually configured launcher session.
        self.env.pop("DAM_WORKSPACE_PATH", None)

    def run_dam(self, *args, cwd=None, extra_env=None):
        self.events_path.write_text("")
        env = dict(self.env)
        env.update(extra_env or {})
        result = subprocess.run(
            [str(self.launcher), *map(str, args)],
            cwd=cwd or self.launcher_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.events = [json.loads(line) for line in self.events_path.read_text().splitlines()]
        self.docker_calls = [event for event in self.events if event["kind"] == "docker"]
        return result

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def project(self, event):
        args = event["args"]
        for index, argument in enumerate(args):
            if argument in ("--project-name", "-p"):
                return args[index + 1]
            if argument.startswith("--project-name="):
                return argument.partition("=")[2]
        self.fail("Docker Compose invocation must explicitly select its workspace project")

    def command(self, event):
        args = iter(event["args"])
        self.assertEqual(next(args), "compose")
        for argument in args:
            if argument in ("--project-name", "-p", "--project-directory", "-f", "--file"):
                next(args)
            elif argument.startswith("--project-name="):
                continue
            else:
                return [argument, *args]
        self.fail("Docker Compose invocation is missing its command")

    def assert_selected_workspace(self, expected):
        self.assertTrue(self.docker_calls)
        for event in self.docker_calls:
            self.assertEqual(event["workspace"], str(expected.resolve()))
        projects = {self.project(event) for event in self.docker_calls}
        self.assertEqual(len(projects), 1)
        return projects.pop()

    def test_invalid_arguments_do_not_prepare_settings_or_call_docker(self):
        for args in (
            (),
            ("", "tmux"),
            ("unused-workspace", "unknown-action"),
            ("unused-workspace", "exec"),
            ("unused-workspace", "shell", "extra"),
            ("unused-workspace", "tmux"),
            ("unused-workspace", "tmux", "first", "second"),
            ("unused-workspace", "tmux", ""),
            ("unused-workspace", "tmux", "review.notes"),
            ("unused-workspace", "tmux", "review:notes"),
            ("unused-workspace", "tmux", "review\nnotes"),
            ("unused-workspace", "tmux", "review\rnotes"),
            ("unused-workspace", "sync", "extra"),
            ("unused-workspace", "config", "extra"),
            ("unused-workspace", "stop", "extra"),
            ("unused-workspace", "ps", "extra"),
        ):
            with self.subTest(args=args):
                result = self.run_dam(*args)
                self.assertEqual(result.returncode, 2)
                self.assertTrue(result.stderr)
                self.assertEqual(self.events, [])
                self.assertFalse((self.workspaces_root / "unused-workspace").exists())

    def test_workspace_defaults_to_shell(self):
        result = self.run_dam("work")
        self.assert_success(result)
        self.assert_selected_workspace(self.workspaces_root / "work")
        self.assertEqual(self.command(self.docker_calls[-1]), ["exec", "dev", "bash", "-l"])

    def test_workspace_paths_are_rejected_before_side_effects(self):
        for argument in (
            ".",
            "..",
            "./ws2",
            "../ws2",
            "ws2/nested",
            "ws2/../ws2",
            "ws2/",
            r".\ws2",
            r"ws2\nested",
            "~/ws2",
            self.root / "absolute" / "workspace",
        ):
            with self.subTest(argument=argument):
                result = self.run_dam(argument, "build")
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr)
                self.assertEqual(self.events, [])
                self.assertFalse(self.workspaces_root.exists())
                self.assertFalse((self.launcher_root / ".host-settings").exists())
                self.assertFalse((self.launcher_root / "ws2").exists())
                self.assertFalse((self.root / "absolute").exists())
                self.assertFalse((self.root / "home" / "ws2").exists())

    def test_workspace_symlinks_are_rejected_before_side_effects(self):
        self.workspaces_root.mkdir()
        for exists in (False, True):
            with self.subTest(target_exists=exists):
                target = self.root / f"target-{exists}"
                if exists:
                    target.mkdir()
                alias = self.workspaces_root / f"alias-{exists}"
                alias.symlink_to(target, target_is_directory=True)
                result = self.run_dam(alias.name, "build")
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr)
                self.assertEqual(self.events, [])
                self.assertFalse((self.launcher_root / ".host-settings").exists())
                self.assertEqual(target.exists(), exists)
                if exists:
                    self.assertEqual(list(target.iterdir()), [])

    def test_workspace_selects_dedicated_project_and_home_volume(self):
        workspace = self.workspaces_root / "ws2"
        result = self.run_dam("ws2", "ps")
        self.assert_success(result)
        project = self.assert_selected_workspace(workspace)
        digest = hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()[:12]
        self.assertEqual(project, "dam-ws2-" + digest)
        compose_text = (self.launcher_root / "compose.yaml").read_text()
        self.assertIn("source: dev-home", compose_text)

    def test_distinct_names_with_same_slug_select_different_projects(self):
        projects = set()
        for name in ("my.workspace", "my-workspace", "my workspace"):
            workspace = self.workspaces_root / name
            result = self.run_dam(name, "ps")
            self.assert_success(result)
            project = self.assert_selected_workspace(workspace)
            self.assertRegex(project, r"^dam-my-workspace-[a-f0-9]{12}$")
            projects.add(project)
        self.assertEqual(len(projects), 3)

    def test_named_workspace_uses_launcher_workspaces_regardless_of_cwd(self):
        caller = self.root / "caller"
        caller.mkdir()
        projects = set()
        for cwd in (self.launcher_root, caller):
            with self.subTest(cwd=cwd):
                result = self.run_dam("ws2", "config", cwd=cwd)
                self.assert_success(result)
                projects.add(self.assert_selected_workspace(self.workspaces_root / "ws2"))
        self.assertEqual(len(projects), 1)
        self.assertTrue((self.workspaces_root / "ws2").is_dir())
        self.assertFalse((caller / "ws2").exists())
        self.assertFalse((self.launcher_root / "ws2").exists())

    def test_workspace_names_preserve_spaces_unicode_dots_and_case(self):
        for name in ("Project With Spaces", "작업공간", "project.v2", ".hidden", "MixedCase"):
            with self.subTest(name=name):
                workspace = self.workspaces_root / name
                result = self.run_dam(name, "config")
                self.assert_success(result)
                project = self.assert_selected_workspace(workspace)
                self.assertRegex(project, r"^dam-[a-z0-9][a-z0-9_-]*-[a-f0-9]{12}$")
                self.assertTrue(workspace.is_dir())

    def test_build_starts_selected_container_and_imports_settings(self):
        result = self.run_dam("a", "build", "--no-cache")
        self.assert_success(result)
        self.assert_selected_workspace(self.workspaces_root / "a")
        self.assertTrue((self.workspaces_root / "a").is_dir())
        commands = [self.command(event) for event in self.docker_calls]
        self.assertEqual(commands, [
            ["build", "--pull", "--no-cache"],
            ["up", "-d", "--wait", "dev"],
            ["exec", "-T", "dev", "python3", "/usr/local/lib/dam/import-settings.py"],
        ])
        self.assertEqual(sum(event["kind"] == "prepare" for event in self.events), 1)
        self.assertEqual(self.events[0]["kind"], "prepare")

    def test_build_failure_does_not_start_container(self):
        result = self.run_dam("ws2", "build", extra_env={"DAM_TEST_FAIL_ACTION": "build"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([self.command(event)[0] for event in self.docker_calls], ["build"])

    def test_tmux_attaches_to_existing_named_session(self):
        result = self.run_dam("ws2", "tmux", "coding")
        self.assert_success(result)
        self.assert_selected_workspace(self.workspaces_root / "ws2")
        self.assertEqual(self.command(self.docker_calls[-1]), [
            "exec", "dev", "tmux", "new-session", "-A", "-s", "coding",
        ])

    def test_named_tmux_sessions_share_workspace_and_preserve_arguments(self):
        workspace = self.workspaces_root / "personal"
        workspace.mkdir(parents=True)
        projects = set()
        for session in (
            "first",
            "second",
            "review notes; $(printf injected) `printf injected` * [a]",
        ):
            with self.subTest(session=session):
                result = self.run_dam("personal", "tmux", session)
                self.assert_success(result)
                projects.add(self.assert_selected_workspace(workspace))
                self.assertEqual(self.command(self.docker_calls[-1]), [
                    "exec", "dev", "tmux", "new-session", "-A", "-s", session,
                ])
        self.assertEqual(len(projects), 1)

    def test_exec_preserves_command_arguments(self):
        result = self.run_dam("ws2", "exec", "printf", "%s", "argument with spaces", "$literal")
        self.assert_success(result)
        self.assert_selected_workspace(self.workspaces_root / "ws2")
        self.assertEqual(self.command(self.docker_calls[-1]), [
            "exec", "-T", "dev", "printf", "%s", "argument with spaces", "$literal",
        ])

    def test_down_targets_only_selected_project_without_preparing_settings(self):
        result = self.run_dam("ws2", "down", "--remove-orphans")
        self.assert_success(result)
        self.assert_selected_workspace(self.workspaces_root / "ws2")
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.command(self.docker_calls[0]), ["down", "--remove-orphans"])

    def test_logs_flags_are_passed_through(self):
        result = self.run_dam("ws2", "logs", "--tail", "25")
        self.assert_success(result)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.command(self.docker_calls[0]), ["logs", "--tail", "25"])

    def test_config_receives_workspace_environment_and_uses_dynamic_bind(self):
        result = self.run_dam("ws2", "config")
        self.assert_success(result)
        self.assert_selected_workspace(self.workspaces_root / "ws2")
        self.assertEqual([self.command(event)[0] for event in self.docker_calls], ["config"])
        compose_text = (self.launcher_root / "compose.yaml").read_text()
        self.assertRegex(compose_text, r"source:\s*['\"]?\$\{DAM_WORKSPACE_PATH(?:[}:])")

    def test_sync_imports_settings_only_for_running_selected_project(self):
        for running, expected in (("0", ["ps"]), ("1", ["ps", "exec"])):
            with self.subTest(running=running):
                result = self.run_dam("ws2", "sync", extra_env={"DAM_TEST_RUNNING": running})
                self.assert_success(result)
                self.assert_selected_workspace(self.workspaces_root / "ws2")
                self.assertEqual([self.command(event)[0] for event in self.docker_calls], expected)


if __name__ == "__main__":
    unittest.main()
