"""Shared command lookups and JSON output."""

import json

from ..errors import DamError
from ..model import validate_name
from ..runtime import Runtime


def blueprint(store, name):
    validate_name(name, "blueprint")
    path = store.blueprint_dir(name)
    if not path.is_dir():
        raise DamError(f"Blueprint does not exist: {name}")
    if not (path / "Dockerfile").is_file():
        raise DamError(f"Blueprint Dockerfile is missing: {name}")
    if not (path / "home").is_dir():
        raise DamError(f"Blueprint home directory is missing: {name}")
    return path


def yard(store, name):
    state = store.load_object("yard", name)
    return state, Runtime(store, state)


def show(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def reject_referenced_blueprint(store, name):
    for yard_name in store.list_objects("yard"):
        if store.load_object("yard", yard_name)["blueprint"] == name:
            raise DamError(f"Blueprint is used by yard: {yard_name}")


def reject_referenced_yard(store, name):
    for map_name in store.list_objects("map"):
        if any(
            pin["yard"] == name for pin in store.load_object("map", map_name)["pins"]
        ):
            raise DamError(f"Yard is used by map: {map_name}")
