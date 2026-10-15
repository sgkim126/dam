"""Restore Linux accounts from the host-owned workspace configuration."""

import argparse
import fcntl
import grp
import json
import os
import pwd
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path

STATE = Path("/etc/dam/workspace/workspace.json")
HOMES = Path("/home")
SHARED_GROUP = "users"
DEFAULT_USER = "node"
IMPORTER = "/usr/local/lib/dam/import-settings.py"
USER_ENV = "/usr/local/bin/dam-user-env"
LOCK = Path("/run/dam-users.lock")


def validate_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", name):
        raise ValueError("Invalid user name")
    if name in {"root", SHARED_GROUP}:
        raise ValueError(f"Reserved user name: {name}")


def validate_state(state):
    if not isinstance(state, dict) or state.get("version") != 1:
        raise ValueError("Unsupported workspace configuration")
    gid = state.get("shared_gid")
    if type(gid) is not int or gid <= 0:
        raise ValueError("Shared GID must be a positive integer")
    accounts = state.get("users")
    if not isinstance(accounts, dict) or DEFAULT_USER not in accounts:
        raise ValueError("Workspace configuration must contain node")
    uids, gids = set(), {gid}
    for name, record in accounts.items():
        validate_name(name)
        if not isinstance(record, dict) or set(record) != {
            "uid",
            "gid",
            "active",
            "profile",
        }:
            raise ValueError(f"Invalid account record: {name}")
        if type(record["uid"]) is not int or record["uid"] < 1000:
            raise ValueError(f"Invalid account UID: {name}")
        if type(record["gid"]) is not int or record["gid"] < 1000:
            raise ValueError(f"Invalid account GID: {name}")
        if type(record["active"]) is not bool:
            raise ValueError(f"Invalid account status: {name}")
        profile = record["profile"]
        if profile is not None and (
            not isinstance(profile, str)
            or profile.startswith(".")
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", profile)
        ):
            raise ValueError(f"Invalid account profile: {name}")
        if record["uid"] in uids:
            raise ValueError(
                "Account UIDs must remain unique, including deleted accounts"
            )
        if record["gid"] in gids:
            raise ValueError(
                "Account GIDs must remain unique, including deleted accounts"
            )
        uids.add(record["uid"])
        gids.add(record["gid"])
    if not accounts[DEFAULT_USER]["active"]:
        raise ValueError("The default account cannot be deleted")


def load_state():
    if STATE.is_symlink():
        raise ValueError("Workspace configuration must not be a symlink")
    state = json.loads(STATE.read_text())
    validate_state(state)
    return state


@contextmanager
def account_lock():
    descriptor = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def ensure_account(name, record):
    uid, gid = record["uid"], record["gid"]
    home = HOMES / name
    try:
        group = grp.getgrnam(name)
    except KeyError:
        subprocess.run(["groupadd", "--gid", str(gid), name], check=True)
    else:
        if group.gr_gid != gid:
            raise ValueError(
                f"Group ID differs from the workspace configuration: {name}"
            )
    try:
        user = pwd.getpwnam(name)
    except KeyError:
        subprocess.run(
            [
                "useradd",
                "--no-create-home",
                "--no-user-group",
                "--uid",
                str(uid),
                "--gid",
                str(gid),
                "--groups",
                SHARED_GROUP,
                "--home-dir",
                str(home),
                "--shell",
                "/bin/bash",
                "--password",
                "!",
                name,
            ],
            check=True,
        )
    else:
        if (user.pw_uid, user.pw_gid, user.pw_dir, user.pw_shell) != (
            uid,
            gid,
            str(home),
            "/bin/bash",
        ):
            raise ValueError(
                f"Account differs from the workspace configuration: {name}"
            )
        subprocess.run(
            ["usermod", "--append", "--groups", SHARED_GROUP, "--lock", name],
            check=True,
        )
    if home.is_symlink():
        raise ValueError(f"Home must not be a symlink: {home}")
    home.mkdir(mode=0o700, exist_ok=True)
    owner = home.stat().st_uid
    if owner != uid and (owner != 0 or any(home.iterdir())):
        raise ValueError(f"Home belongs to another user: {home}")
    home.chmod(0o700)
    os.chown(home, uid, gid)


def import_user(name, record, mode):
    command = [
        "setpriv",
        "--reuid",
        name,
        "--regid",
        str(record["gid"]),
        "--init-groups",
        USER_ENV,
        "python3",
        IMPORTER,
        mode,
    ]
    if record["profile"] is not None:
        command.append("--profile=" + record["profile"])
    subprocess.run(command, check=True)


def restore(state, *, sync=False):
    if grp.getgrnam(SHARED_GROUP).gr_gid != state["shared_gid"]:
        raise ValueError("Shared group ID differs from the workspace configuration")
    active = {
        name: record for name, record in state["users"].items() if record["active"]
    }
    for name, record in active.items():
        ensure_account(name, record)
    if sync:
        subprocess.run(["python3", IMPORTER, "--system-only"], check=True)
    for name, record in active.items():
        import_user(name, record, "--user-only" if sync else "--shell-only")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("restore", "sync"))
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise ValueError("Account administration must run as root")
        os.umask(0o077)
        with account_lock():
            restore(load_state(), sync=args.action == "sync")
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Account administration failed: {error}\n")


if __name__ == "__main__":
    main()
