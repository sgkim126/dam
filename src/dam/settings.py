"""Prepare one workspace's portable host settings snapshot."""

import runpy
from importlib import resources
from pathlib import Path


def prepare_settings(host_home: Path, snapshot_dir: Path) -> None:
    """Refresh the snapshot in place so an existing directory bind remains valid."""
    resource = resources.files("dam").joinpath(
        "resources", "container", "docker", "prepare-settings.py"
    )
    with resources.as_file(resource) as source:
        prepare = runpy.run_path(str(source))["prepare"]
        prepare(host_home, snapshot_dir)
