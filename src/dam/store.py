"""Host-owned configuration with atomic writes and per-workspace locking."""

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .errors import DamError
from .model import validate_state, validate_workspace_name


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else Path.home() / ".config" / "dam"

    @property
    def profile_dir(self):
        return self.root / "profile"

    def workspace_dir(self, name):
        validate_workspace_name(name)
        return self.root / "workspaces" / name

    def snapshot_dir(self, name):
        return self.workspace_dir(name) / "settings"

    def _prepare_root(self):
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.root.chmod(0o700)

    def load(self, name):
        path = self.workspace_dir(name) / "workspace.json"
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise DamError(f"Workspace is not registered: {name}") from error
        except (OSError, ValueError) as error:
            raise DamError(f"Cannot read workspace {name}: {error}") from error
        validate_state(state)
        if state["name"] != name:
            raise DamError(f"Workspace name does not match its registry: {name}")
        return state

    def list_names(self):
        parent = self.root / "workspaces"
        if not parent.exists():
            return []
        return sorted(
            path.name
            for path in parent.iterdir()
            if (path / "workspace.json").is_file()
        )

    @contextmanager
    def lock(self, name):
        """Hold one lock across reads, changes, saves, and any recovery work.

        Use the yielded workspace's load/create/save methods inside the scope;
        Store.create and Store.save acquire their own locks.
        """
        if name != "@profiles":
            validate_workspace_name(name)
        self._prepare_root()
        directory = self.root / ".locks"
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        path = directory / f"{name}.lock"
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            workspace = _LockedWorkspace(self, name)
            try:
                yield workspace
            finally:
                workspace._active = False
                fcntl.flock(handle, fcntl.LOCK_UN)

    def create(self, state):
        """Register a new workspace, rejecting an existing registration."""
        validate_state(state)
        with self.lock(state["name"]) as workspace:
            workspace.create(state)

    def save(self, state):
        """Replace the state of an already registered workspace."""
        validate_state(state)
        with self.lock(state["name"]) as workspace:
            workspace.save(state)

    def _save_locked(self, state):
        """Write validated state while the caller holds its workspace lock."""
        self._prepare_root()
        directory = self.workspace_dir(state["name"])
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        path = directory / "workspace.json"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=directory, delete=False
            ) as handle:
                temporary = Path(handle.name)
                json.dump(state, handle, ensure_ascii=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            # Container root reads the bind-mounted registry regardless of host UID.
            temporary.chmod(0o644)
            temporary.replace(path)
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


class _LockedWorkspace:
    """Validated registry access for the lifetime of one workspace lock."""

    def __init__(self, store, name):
        self._store = store
        self._name = name
        self._active = True

    def _check_active(self):
        if not self._active:
            raise DamError(f"Workspace lock is no longer held: {self._name}")

    def _validate(self, state):
        self._check_active()
        validate_state(state)
        if state["name"] != self._name:
            raise DamError(f"Workspace name does not match its lock: {self._name}")

    def load(self):
        self._check_active()
        return self._store.load(self._name)

    def create(self, state):
        self._validate(state)
        path = self._store.workspace_dir(self._name) / "workspace.json"
        if path.exists():
            raise DamError(f"Workspace is already registered: {self._name}")
        self._store._save_locked(state)

    def save(self, state):
        self._validate(state)
        path = self._store.workspace_dir(self._name) / "workspace.json"
        if not path.exists():
            raise DamError(f"Workspace is not registered: {self._name}")
        self._store._save_locked(state)
