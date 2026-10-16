import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from dam.cli import main


class CliTests(unittest.TestCase):
    def test_help_does_not_create_configuration_or_need_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ, HOME=directory, PATH="")
            result = subprocess.run(
                [sys.executable, "-m", "dam", "--help"],
                check=False,
                cwd=directory,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("usage: dam", result.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_no_arguments_displays_help(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main([]), 0)
        self.assertIn("usage: dam", output.getvalue())

    def test_unknown_argument_is_usage_error(self):
        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as error,
        ):
            main(["--not-a-dam-option"])
        self.assertEqual(error.exception.code, 2)
