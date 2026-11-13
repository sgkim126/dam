"""Validated persisted yard and map records."""

import os
import re

from .errors import UsageError


def _name(value, pattern, kind):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise UsageError(f"Invalid {kind} name: {value!r}")
    return value


def validate_name(value, kind="object"):
    return _name(value, r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", kind)


def validate_yard_name(value):
    """Yard names are also unmodified container hostnames."""
    return _name(value, r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", "yard")


def validate_container_path(value):
    if not isinstance(value, str):
        raise UsageError("Container path must be a string")
    if not value.startswith("/"):
        raise UsageError("Container path must be absolute")
    if "\0" in value:
        raise UsageError("Container path must not contain NUL bytes")
    return value


def new_yard(name, blueprint, uid, gid):
    validate_yard_name(name)
    validate_name(blueprint, "blueprint")
    return {
        "name": name,
        "blueprint": blueprint,
        "uid": uid,
        "gid": gid,
        "mounts": {},
    }


def new_map(name):
    validate_name(name, "map")
    return {"name": name, "pins": []}


def validate_object(kind, state):
    if not isinstance(state, dict):
        raise UsageError(f"Invalid {kind} state")
    name = state.get("name")
    (validate_yard_name if kind == "yard" else validate_name)(name)
    if kind == "yard":
        if set(state) != {"name", "blueprint", "uid", "gid", "mounts"}:
            raise UsageError("Invalid yard state")
        validate_name(state["blueprint"], "blueprint")
        if any(
            type(state[key]) is not int or state[key] <= 0 for key in ("uid", "gid")
        ):
            raise UsageError("Invalid yard account IDs")
        if not isinstance(state["mounts"], dict):
            raise UsageError("Invalid yard mounts")
        for mount, source in state["mounts"].items():
            validate_name(mount, "mount")
            if not isinstance(source, str):
                raise UsageError(f"Mount source must be a string: {mount}")
            if not os.path.isabs(source):
                raise UsageError(f"Mount source must be absolute: {mount}")
            if "\0" in source:
                raise UsageError(f"Mount source must not contain NUL bytes: {mount}")
    elif kind == "map":
        if set(state) != {"name", "pins"} or not isinstance(state["pins"], list):
            raise UsageError("Invalid map state")
        names = set()
        for pin in state["pins"]:
            if not isinstance(pin, dict) or set(pin) != {"name", "yard", "path"}:
                raise UsageError("Invalid map pin")
            validate_name(pin["name"], "pin")
            validate_yard_name(pin["yard"])
            validate_container_path(pin["path"])
            if pin["name"] in names:
                raise UsageError("Duplicate map pin")
            names.add(pin["name"])
    else:
        raise UsageError(f"Unknown state kind: {kind}")
    return state
