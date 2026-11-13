"""Host-owned configuration with atomic JSON writes and a registry lock."""

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .errors import DamError
from .model import validate_name, validate_object, validate_yard_name


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else Path.home() / ".dam"

    def blueprint_dir(self, name):
        return self.root / "blueprints" / validate_name(name, "blueprint")

    def object_dir(self, kind, name):
        if kind not in {"yard", "map"}:
            raise ValueError(f"Unknown object kind: {kind}")
        (validate_yard_name if kind == "yard" else validate_name)(name)
        return self.root / f"{kind}s" / name

    def object_path(self, kind, name):
        return self.object_dir(kind, name) / f"{kind}.json"

    def list_objects(self, kind):
        if kind not in {"yard", "map"}:
            raise ValueError(f"Unknown object kind: {kind}")
        parent = self.root / f"{kind}s"
        if not parent.exists():
            return []
        return sorted(
            path.name for path in parent.iterdir() if (path / f"{kind}.json").is_file()
        )

    def load_object(self, kind, name):
        try:
            state = json.loads(self.object_path(kind, name).read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise DamError(f"{kind} does not exist: {name}") from error
        validate_object(kind, state)
        if state["name"] != name:
            raise DamError(f"{kind} name does not match its registry: {name}")
        return state

    def save_object(self, kind, state, *, create=False):
        """Caller holds registry_lock for mutating operations."""
        validate_object(kind, state)
        path = self.object_path(kind, state["name"])
        self._prepare_root()
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if create and path.exists():
            raise DamError(f"{kind} already exists: {state['name']}")
        self._atomic_json(path, state)

    def delete_object(self, kind, name):
        """Caller holds registry_lock for mutating operations."""
        path = self.object_path(kind, name)
        if not path.is_file():
            raise DamError(f"{kind} does not exist: {name}")
        path.unlink()
        path.parent.rmdir()

    def _prepare_root(self):
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.root.chmod(0o700)

    def _atomic_json(self, path, state):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
                json.dump(state, handle, ensure_ascii=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o600)
            temporary.replace(path)
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @contextmanager
    def registry_lock(self):
        self._prepare_root()
        path = self.root / ".registry.lock"
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
