"""Register and initialize one workspace."""

from pathlib import Path

from ..errors import DamError
from ..model import new_workspace
from ..runtime import Runtime
from ..settings import prepare_settings


def configure(parser):
    pass


def run(args, store):
    state = new_workspace(args.workspace)
    with store.lock(args.workspace) as workspace:
        manifest = store.workspace_dir(args.workspace) / "workspace.json"
        if manifest.exists():
            raise DamError(f"Workspace is already registered: {args.workspace}")
        runtime = Runtime(store, state)
        # Check ownership before registering or copying host settings.
        runtime.inspect()
        workspace.create(state)
        try:
            prepare_settings(Path.home(), store.snapshot_dir(state["name"]))
            runtime.ensure_running()
        except BaseException:
            # Keep any container/home data so a subsequent init can safely retry.
            manifest.unlink(missing_ok=True)
            raise
    print(f"Workspace ready: {state['name']}")
    return 0
