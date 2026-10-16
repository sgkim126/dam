"""Materialize installed package resources for Docker's build context."""

import tempfile
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path

from .errors import DamError


def _copy(source, target):
    if source.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            _copy(child, target / child.name)
    else:
        target.write_bytes(source.read_bytes())


@contextmanager
def build_context():
    source = files("dam").joinpath("resources", "container")
    if not source.joinpath("Dockerfile").is_file():
        raise DamError("Installed package does not contain a container Dockerfile")
    with tempfile.TemporaryDirectory(prefix="dam-build-") as directory:
        target = Path(directory)
        _copy(source, target)
        yield target
