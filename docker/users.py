#!/usr/bin/env python3
"""Read and write persistent workspace account IDs."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile


HOMES = Path("/home")
REGISTRY_DIR = HOMES / ".dam"
REGISTRY = REGISTRY_DIR / "users.json"
SHARED_GROUP = "users"


def validate_name(name: str) -> None:
    if not isinstance(name, str) or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", name):
        raise ValueError("User names must use 1-32 lowercase letters, digits, underscores or hyphens, starting with a letter or underscore")
    if name in {"root", SHARED_GROUP}:
        raise ValueError(f"User name is reserved: {name}")


def validate_registry(state: dict) -> None:
    if not isinstance(state, dict) or set(state) != {"shared_gid", "accounts"}:
        raise ValueError("Registry must contain shared_gid and accounts")
    if type(state["shared_gid"]) is not int or state["shared_gid"] <= 0:
        raise ValueError("Shared GID must be a positive integer")
    accounts = state["accounts"]
    if not isinstance(accounts, dict) or "node" not in accounts:
        raise ValueError("Registry must contain the node account")
    uids, gids = set(), {state["shared_gid"]}
    for name, record in accounts.items():
        validate_name(name)
        if not isinstance(record, dict) or set(record) != {"uid", "gid"}:
            raise ValueError(f"Account must contain uid and gid: {name}")
        if any(type(value) is not int or value < 1000 for value in record.values()):
            raise ValueError(f"Account IDs must be integers of at least 1000: {name}")
        if record["uid"] in uids or record["gid"] in gids:
            raise ValueError(f"Account ID is already registered: {name}")
        uids.add(record["uid"])
        gids.add(record["gid"])


@contextmanager
def registry_lock():
    REGISTRY_DIR.mkdir(mode=0o700, exist_ok=True)
    if REGISTRY_DIR.is_symlink() or REGISTRY_DIR.stat().st_uid != 0:
        raise ValueError("Registry directory must belong to root")
    REGISTRY_DIR.chmod(0o700)
    with (REGISTRY_DIR / "users.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def load_registry() -> dict | None:
    try:
        state = json.loads(REGISTRY.read_text())
    except FileNotFoundError:
        return None
    validate_registry(state)
    return state


def save_registry(state: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=REGISTRY_DIR, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary.replace(REGISTRY)
            # Persist the replacement before initializing accounts and homes.
            directory_fd = os.open(REGISTRY_DIR, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
