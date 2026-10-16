import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dam.assets import build_context
from dam.errors import DamError
from dam.process import run


class ProcessTests(unittest.TestCase):
    def test_argument_boundaries_are_preserved(self):
        value = "space ' quote $(exit 1); $HOME"
        result = run(
            [sys.executable, "-c", "import sys; print(sys.argv[1])", value],
            capture=True,
        )
        self.assertEqual(result.stdout.rstrip("\n"), value)

    def test_failure_retains_diagnostic_and_exit_code(self):
        with self.assertRaises(DamError) as error:
            run(
                [
                    sys.executable,
                    "-c",
                    "import sys; print('failed', file=sys.stderr); sys.exit(19)",
                ],
                capture=True,
            )
        self.assertEqual(error.exception.exit_code, 19)
        self.assertEqual(str(error.exception), "failed")

    def test_missing_executable_is_readable_error(self):
        with self.assertRaises(DamError) as error:
            run(["/no/such/dam-executable"])
        self.assertEqual(error.exception.exit_code, 127)

    def test_packaged_context_is_complete_and_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            root = package / "resources/container"
            (root / "docker").mkdir(parents=True)
            (root / "Dockerfile").write_text("FROM scratch\n")
            (root / ".dockerignore").write_text("*.pyc\n")
            (root / "docker/helper.py").write_text("print('ok')\n")
            with patch("dam.assets.files", return_value=package):
                with build_context() as context:
                    self.assertEqual(
                        (context / "docker/helper.py").read_text(), "print('ok')\n"
                    )
                    self.assertTrue((context / ".dockerignore").is_file())
                self.assertFalse(context.exists())
            self.assertTrue((root / "Dockerfile").is_file())
