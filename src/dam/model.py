"""Versioned workspace contracts shared by all commands."""

import os
import re

from .errors import UsageError


def _name(value, pattern, kind):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise UsageError(f"Invalid {kind} name: {value!r}")
    if value in {".", ".."}:
        raise UsageError(f"Reserved {kind} name: {value!r}")
    return value


def validate_workspace_name(value):
    return _name(value, r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", "workspace")


def validate_username(value):
    _name(value, r"[a-z_][a-z0-9_-]{0,31}", "user")
    if value in {"root", "users", "daemon", "bin", "sys", "nobody"}:
        raise UsageError(f"Reserved user name: {value}")
    return value


def validate_profile_name(value):
    return _name(value, r"[A-Za-z0-9_.-]+", "profile")


def validate_mount_name(value):
    return _name(value, r"[A-Za-z0-9_.-]+", "mount")


def validate_session_name(value):
    return _name(value, r"[A-Za-z0-9_-]+", "session")


def validate_window_name(value):
    return _name(value, r"[A-Za-z0-9_-]+", "window")


def validate_container_path(value):
    if not isinstance(value, str) or not value.startswith("/") or "\0" in value:
        raise UsageError("Container paths must be absolute and contain no NUL bytes")
    return value


def new_workspace(name):
    validate_workspace_name(name)
    return {
        "version": 1,
        "name": name,
        "shared_gid": 100,
        "users": {
            "node": {
                "uid": 1000,
                "gid": 1000,
                "active": True,
                "profile": None,
            }
        },
        "mounts": {},
        "sessions": {},
    }


def references_to_user(state, username):
    return [
        name
        for name, session in state["sessions"].items()
        if any(window["username"] == username for window in session["windows"])
    ]


def validate_state(state):
    if not isinstance(state, dict):
        raise UsageError("Workspace state must be an object")
    if type(state.get("version")) is not int:
        raise UsageError("Workspace state version must be an integer")
    if state["version"] != 1:
        raise UsageError("Unsupported workspace state version")
    validate_workspace_name(state.get("name"))
    if type(state.get("shared_gid")) is not int:
        raise UsageError("Shared group ID must be an integer")
    if state["shared_gid"] <= 0:
        raise UsageError("Shared group ID must be positive")
    users = state.get("users")
    if not isinstance(users, dict):
        raise UsageError("Workspace users must be an object")
    if "node" not in users:
        raise UsageError("Workspace must include the node account")
    uids, gids = set(), {state["shared_gid"]}
    for name, user in users.items():
        validate_username(name)
        if not isinstance(user, dict) or set(user) != {
            "uid",
            "gid",
            "active",
            "profile",
        }:
            raise UsageError(f"Invalid account record: {name}")
        for key in ("uid", "gid"):
            if type(user[key]) is not int:
                raise UsageError(f"Account {key.upper()} must be an integer: {name}")
            if user[key] < 1000:
                raise UsageError(f"Account {key.upper()} must be at least 1000: {name}")
        if user["uid"] in uids or user["gid"] in gids:
            raise UsageError(f"Duplicate account IDs: {name}")
        uids.add(user["uid"])
        gids.add(user["gid"])
        if type(user["active"]) is not bool:
            raise UsageError(f"Invalid account status: {name}")
        if user["profile"] is not None:
            validate_profile_name(user["profile"])
    if not users["node"]["active"]:
        raise UsageError("The default account must remain active")
    mounts = state.get("mounts")
    if not isinstance(mounts, dict):
        raise UsageError("Invalid mount registry")
    for name, mount in mounts.items():
        validate_mount_name(name)
        if not isinstance(mount, dict) or set(mount) != {"path", "shared"}:
            raise UsageError(f"Invalid mount record: {name}")
        if not isinstance(mount["path"], str) or not os.path.isabs(mount["path"]):
            raise UsageError(f"Invalid host mount path: {name}")
        if "\0" in mount["path"]:
            raise UsageError(f"Host mount path must not contain NUL bytes: {name}")
        if type(mount["shared"]) is not bool:
            raise UsageError(f"Invalid mount sharing status: {name}")
    sessions = state.get("sessions")
    if not isinstance(sessions, dict):
        raise UsageError("Invalid session registry")
    main = {"name": "main", "username": "node", "path": "/home/node"}
    for name, session in sessions.items():
        validate_session_name(name)
        if not isinstance(session, dict) or set(session) != {"windows"}:
            raise UsageError(f"Invalid session record: {name}")
        windows = session["windows"]
        if not isinstance(windows, list) or not windows or windows[0] != main:
            raise UsageError(f"Session must start with the fixed main window: {name}")
        names = set()
        for window in windows:
            if not isinstance(window, dict) or set(window) != {
                "name",
                "username",
                "path",
            }:
                raise UsageError(f"Invalid window in session: {name}")
            validate_window_name(window["name"])
            validate_container_path(window["path"])
            if window["name"] in names:
                raise UsageError(f"Duplicate window name: {window['name']}")
            names.add(window["name"])
            if not isinstance(window["username"], str):
                raise UsageError(f"Window username must be a string: {window['name']}")
            if window["username"] not in users:
                raise UsageError(
                    f"Window references an unknown user: {window['username']}"
                )
            if not users[window["username"]]["active"]:
                raise UsageError(
                    f"Window references an inactive user: {window['username']}"
                )
