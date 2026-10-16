"""Build an sdist/wheel and exercise a non-editable uv tool installation."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(argv, *, check=True, **kwargs):
    return subprocess.run([str(item) for item in argv], check=check, **kwargs)


def main():
    root = Path(__file__).resolve().parents[1]
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is required to verify the distribution")
    with tempfile.TemporaryDirectory(prefix="dam-package-test-") as directory:
        temporary = Path(directory)
        dist = temporary / "dist"
        environment = dict(os.environ)
        for key in (
            "PYTHONPATH",
            "PYTHONHOME",
            "VIRTUAL_ENV",
            "UV_PROJECT",
            "UV_PROJECT_ENVIRONMENT",
            "UV_WORKING_DIR",
        ):
            environment.pop(key, None)
        environment.update(
            {
                "HOME": str(temporary / "home"),
                "UV_TOOL_DIR": str(temporary / "tools"),
                "UV_TOOL_BIN_DIR": str(temporary / "bin"),
                "UV_CACHE_DIR": str(temporary / "cache"),
                "UV_NO_CONFIG": "1",
                "UV_PYTHON_DOWNLOADS": "never",
            }
        )
        Path(environment["HOME"]).mkdir()
        # With neither format flag, uv builds the wheel from the generated sdist.
        run(
            [uv, "build", "--python", sys.executable, "--out-dir", dist, root],
            env=environment,
            cwd=temporary,
        )
        (wheel,) = dist.glob("*.whl")
        run(
            [uv, "tool", "install", "--python", sys.executable, wheel],
            env=environment,
            cwd=temporary,
        )
        try:
            executable = temporary / "bin" / "dam"
            run([executable, "--help"], env=environment, cwd=temporary)
            installed_python = temporary / "tools" / "dam" / "bin" / "python"
            code = (
                "from pathlib import Path\n"
                "import dam\n"
                "installed = Path(dam.__file__).resolve()\n"
                f"if installed.is_relative_to(Path({str(root)!r})):\n"
                "    raise RuntimeError(\n"
                "        f'Installed package references the source checkout: {installed}'\n"
                "    )\n"
            )
            assets = root / "src/dam/resources/container"
            if assets.exists():
                required = [
                    p.relative_to(assets).as_posix()
                    for p in assets.rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts
                ]
                code += (
                    "from dam.assets import build_context\n"
                    f"required = {required!r}\n"
                    "with build_context() as path:\n"
                    "    missing = [item for item in required if not (path / item).is_file()]\n"
                    "    if missing:\n"
                    "        raise RuntimeError(\n"
                    "            f'Installed package is missing resources: {missing}'\n"
                    "        )\n"
                    "if path.exists():\n"
                    "    raise RuntimeError(\n"
                    "        f'Temporary build context was not removed: {path}'\n"
                    "    )\n"
                )
            run([installed_python, "-c", code], env=environment, cwd=temporary)
            configuration = Path(environment["HOME"]) / ".config/dam"
            if configuration.exists():
                raise RuntimeError(
                    f"Package verification created configuration: {configuration}"
                )
        finally:
            # Preserve a validation failure if uninstall also fails.
            run(
                [uv, "tool", "uninstall", "dam"],
                env=environment,
                cwd=temporary,
                check=sys.exc_info()[0] is None,
            )


if __name__ == "__main__":
    main()
