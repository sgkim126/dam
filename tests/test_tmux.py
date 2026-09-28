"""Check session initialization without using a personal tmux server.

Set DAM_TMUX_INTEGRATION=1 to also exercise a disposable real tmux server.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import uuid


SCRIPT = Path(__file__).resolve().parents[1] / "docker/tmux.sh"


class TmuxTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dam-tmux-tests-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.events_path = self.root / "events.jsonl"
        self.events_path.touch()
        self.sessions_path = self.root / "sessions.json"
        self.sessions_path.write_text("[]")
        self.env = dict(os.environ)
        self.env.update(
            HOME=str(self.home),
            PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
            DAM_TEST_EVENTS=str(self.events_path),
            DAM_TEST_SESSIONS=str(self.sessions_path),
        )
        self.executable("tmux", """
            import json
            import os
            from pathlib import Path
            import sys

            arguments = sys.argv[1:]
            with open(os.environ["DAM_TEST_EVENTS"], "a") as events:
                events.write(json.dumps(arguments) + "\\n")
            state = Path(os.environ["DAM_TEST_SESSIONS"])
            sessions = json.loads(state.read_text())
            commands = [[]]
            for argument in arguments:
                if argument == ";":
                    commands.append([])
                else:
                    commands[-1].append(argument)
            for command in commands:
                name = command[0]
                if name == "has-session":
                    target = command[command.index("-t") + 1].removeprefix("=")
                    sys.exit(0 if target in sessions else 1)
                if name == os.environ.get("DAM_TEST_FAIL_COMMAND"):
                    print("requested tmux failure", file=sys.stderr)
                    sys.exit(23)
                if name == "new-session":
                    session = command[command.index("-s") + 1]
                    if session in sessions and "-A" not in command:
                        sys.exit("duplicate session")
                    if session not in sessions:
                        sessions.append(session)
                        state.write_text(json.dumps(sessions))
                elif name == "source-file":
                    if not Path(command[-1]).is_file():
                        sys.exit("configuration path did not survive argument passing")
                elif name != "attach-session":
                    sys.exit("unexpected command: " + name)
        """)

    def executable(self, name, code):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(code))
        path.chmod(0o755)

    def config(self, session="a", content="# session configuration\n"):
        path = self.home / f"{session}.tmux.conf"
        path.write_text(content)
        return path

    def run_session(self, session="a", extra_env=None):
        return subprocess.run(
            ["bash", str(SCRIPT), session], cwd=self.root,
            env=dict(self.env, **(extra_env or {})),
            capture_output=True, text=True, timeout=10,
        )

    def events(self):
        return [json.loads(line) for line in self.events_path.read_text().splitlines()]

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class TmuxInitializationTests(TmuxTestCase):
    def test_missing_config_keeps_normal_create_or_attach_command(self):
        self.assert_success(self.run_session())
        self.assertEqual(self.events(), [["new-session", "-A", "-s", "a"]])

    def test_new_session_sources_config_before_attach_in_same_command_queue(self):
        config = self.config()
        self.assert_success(self.run_session())
        self.assertEqual(self.events(), [
            ["has-session", "-t", "=a"],
            ["new-session", "-d", "-s", "a", ";",
             "source-file", "-t", "=a:", str(config)],
            ["attach-session", "-t", "=a"],
        ])

    def test_existing_session_does_not_source_config_again(self):
        self.config()
        self.sessions_path.write_text('["a"]')
        self.assert_success(self.run_session())
        self.assertEqual(self.events(), [
            ["has-session", "-t", "=a"],
            ["attach-session", "-t", "=a"],
        ])

    def test_session_prefix_does_not_attach_to_another_session(self):
        self.config()
        self.sessions_path.write_text('["alpha"]')
        self.assert_success(self.run_session())
        self.assertEqual(json.loads(self.sessions_path.read_text()), ["alpha", "a"])
        self.assertEqual(self.events()[-1], ["attach-session", "-t", "=a"])

    def test_allowed_session_name_selects_matching_config(self):
        session = "Review_2026-1"
        config = self.config(session)
        self.assert_success(self.run_session(session))
        self.assertEqual(self.events(), [
            ["has-session", "-t", "=" + session],
            ["new-session", "-d", "-s", session, ";",
             "source-file", "-t", "=" + session + ":", str(config)],
            ["attach-session", "-t", "=" + session],
        ])

    def test_missing_config_passes_allowed_session_name_unchanged(self):
        session = "-Review_2026-1"
        self.assert_success(self.run_session(session))
        self.assertEqual(self.events(), [["new-session", "-A", "-s", session]])
        self.assertEqual(json.loads(self.sessions_path.read_text()), [session])

    def test_tmux_failure_is_returned_without_attaching(self):
        self.config()
        for command in ("new-session", "source-file"):
            with self.subTest(command=command):
                self.sessions_path.write_text("[]")
                self.events_path.write_text("")
                result = self.run_session(extra_env={"DAM_TEST_FAIL_COMMAND": command})
                self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
                self.assertIn("requested tmux failure", result.stderr)
                self.assertFalse(any(event[0] == "attach-session" for event in self.events()))


@unittest.skipUnless(os.environ.get("DAM_TMUX_INTEGRATION") == "1", "set DAM_TMUX_INTEGRATION=1 for real tmux")
class RealTmuxInitializationTests(TmuxTestCase):
    def setUp(self):
        real_tmux = shutil.which("tmux")
        if not real_tmux:
            self.skipTest("tmux is not installed")
        super().setUp()
        self.real_tmux = real_tmux
        self.socket = "dam-test-" + uuid.uuid4().hex[:12]
        self.env.pop("TMUX", None)
        self.env.pop("TMUX_PANE", None)
        self.env.update(DAM_TEST_TMUX=real_tmux, DAM_TEST_SOCKET=self.socket, SHELL="/bin/sh")
        self.executable("tmux", """
            import os
            import sys

            if sys.argv[1] == "attach-session":
                sys.exit(0)
            os.execv(os.environ["DAM_TEST_TMUX"], [
                os.environ["DAM_TEST_TMUX"], "-L", os.environ["DAM_TEST_SOCKET"],
                "-f", "/dev/null", *sys.argv[1:],
            ])
        """)
        self.addCleanup(lambda: self.tmux("kill-server"))

    def tmux(self, *arguments):
        return subprocess.run(
            [self.real_tmux, "-L", self.socket, "-f", "/dev/null", *arguments],
            env=self.env, capture_output=True, text=True, timeout=10,
        )

    def test_real_config_targets_new_session_and_runs_only_once(self):
        self.assert_success(self.tmux("new-session", "-d", "-s", "other", "sleep 60"))
        self.assert_success(self.tmux("set-option", "-g", "base-index", "1"))
        session = "Review_2026-1"
        self.config(session, content=(
            "set-option base-index 0\nmove-window -r\nrename-window -t :0 first\n"
            "new-window -t :1 -n x -c /tmp 'sleep 60'\nselect-window -t :0\n"
        ))
        self.assert_success(self.run_session(session))
        target = "=" + session
        windows = self.tmux("list-windows", "-t", target, "-F", "#{window_index}:#{window_name}")
        self.assert_success(windows)
        self.assertEqual(windows.stdout.splitlines(), ["0:first", "1:x"])
        self.assert_success(self.run_session(session))
        self.assertEqual(self.tmux(
            "list-windows", "-t", target, "-F", "#{window_index}:#{window_name}",
        ).stdout, windows.stdout)
        self.assertEqual(self.tmux("list-windows", "-t", "=other", "-F", "#{window_index}").stdout, "0\n")

    def test_real_parse_error_is_returned_and_created_session_remains(self):
        self.config(content="dam-not-a-tmux-command\n")
        result = self.run_session()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dam-not-a-tmux-command", result.stdout + result.stderr)
        self.assert_success(self.tmux("has-session", "-t", "=a"))
        # Reattaching must not attempt the still-invalid configuration again.
        self.assert_success(self.run_session())


if __name__ == "__main__":
    unittest.main()
