#!/usr/bin/env python3
"""Restore persistent workspace accounts and synchronize their settings."""

import argparse
from contextlib import contextmanager
import fcntl
import grp
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import tempfile


HOMES = Path("/home")
REGISTRY_DIR = HOMES / ".dam"
REGISTRY = REGISTRY_DIR / "users.json"
SHARED_GROUP = "users"
FIRST_ID = 2000
IMPORTER = "/usr/local/lib/dam/import-settings.py"
USER_ENV = "/usr/local/bin/dam-user-env"


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


def initial_registry() -> dict:
    if any(path.name not in {".dam", "node"} for path in HOMES.iterdir()):
        raise ValueError("User homes exist without an account registry")
    node = pwd.getpwnam("node")
    return {
        "shared_gid": grp.getgrnam(SHARED_GROUP).gr_gid,
        "accounts": {"node": {"uid": node.pw_uid, "gid": node.pw_gid}},
    }


def reserve_user(state: dict, name: str) -> None:
    if name in state["accounts"]:
        return
    users, groups = pwd.getpwall(), grp.getgrall()
    if any(user.pw_name == name for user in users) or any(group.gr_name == name for group in groups):
        raise ValueError(f"User or group already exists outside dam: {name}")
    if (HOMES / name).exists() or (HOMES / name).is_symlink():
        raise ValueError(f"Home already exists outside dam: {name}")
    used = {user.pw_uid for user in users} | {group.gr_gid for group in groups}
    for record in state["accounts"].values():
        used.update(record.values())
    identity = FIRST_ID
    while identity in used:
        identity += 1
    state["accounts"][name] = {"uid": identity, "gid": identity}


def ensure_account(name: str, record: dict) -> None:
    uid, gid = record["uid"], record["gid"]
    home = HOMES / name
    try:
        group = grp.getgrnam(name)
    except KeyError:
        subprocess.run(["groupadd", "--gid", str(gid), name], check=True)
    else:
        if group.gr_gid != gid:
            raise ValueError(f"Group ID differs from the registry: {name}")
    try:
        user = pwd.getpwnam(name)
    except KeyError:
        subprocess.run([
            "useradd", "--no-create-home", "--no-user-group",
            "--uid", str(uid), "--gid", str(gid), "--groups", SHARED_GROUP,
            "--home-dir", str(home), "--shell", "/bin/bash", "--password", "!", name,
        ], check=True)
    else:
        if (user.pw_uid, user.pw_gid, user.pw_dir, user.pw_shell) != (uid, gid, str(home), "/bin/bash"):
            raise ValueError(f"Account differs from the registry: {name}")
        subprocess.run(["usermod", "--append", "--groups", SHARED_GROUP, "--lock", name], check=True)

    if home.is_symlink():
        raise ValueError(f"Home must be a directory: {home}")
    home.mkdir(mode=0o700, exist_ok=True)
    owner = home.stat().st_uid
    if owner != uid and (owner != 0 or any(home.iterdir())):
        raise ValueError(f"Home belongs to another user: {home}")
    home.chmod(0o700)
    os.chown(home, uid, gid)


def synchronize(new_user: str | None = None) -> None:
    if new_user is not None:
        validate_name(new_user)
    with registry_lock():
        state = load_registry()
        if state is None:
            state = initial_registry()
        if new_user is not None:
            reserve_user(state, new_user)
        validate_registry(state)
        if state["shared_gid"] != grp.getgrnam(SHARED_GROUP).gr_gid:
            raise ValueError("Shared group ID differs from the registry")
        # Keep allocated IDs even if account or settings initialization fails.
        save_registry(state)
        for name, record in state["accounts"].items():
            ensure_account(name, record)
        subprocess.run(["python3", IMPORTER, "--system-only"], check=True)
        for name, record in state["accounts"].items():
            subprocess.run([
                "setpriv", "--reuid", name, "--regid", str(record["gid"]), "--init-groups",
                USER_ENV, "python3", IMPORTER, "--user-only",
            ], check=True)
    if new_user is not None:
        print(f"Account ready: {new_user}. Switch with: su - {new_user}")
    else:
        print("Accounts and settings synchronized.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("sync")
    commands.add_parser("add").add_argument("user")
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise ValueError("Account administration must run as root")
        os.umask(0o077)
        synchronize(getattr(args, "user", None))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Account administration failed: {error}\n")


if __name__ == "__main__":
    main()
