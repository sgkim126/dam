"""Docker resources and stopped-yard reconciliation."""

import csv
import hashlib
import io
import json
import os
import shlex
import shutil
import stat
import tempfile
import uuid
from pathlib import Path, PurePosixPath

from .assets import build_context
from .errors import DamError
from .process import run


def _digest(*parts):
    value = hashlib.sha256()
    for part in parts:
        value.update(str(part).encode())
        value.update(b"\0")
    return value.hexdigest()[:16]


def _mount_spec(*fields):
    output = io.StringIO()
    csv.writer(output, lineterminator="").writerow(fields)
    return output.getvalue()


def _tree_digest(path):
    parts = []
    for entry in sorted(path.rglob("*")):
        relative = entry.relative_to(path).as_posix()
        mode = stat.S_IMODE(entry.lstat().st_mode)
        if entry.is_symlink():
            parts.extend((relative, "link", mode, os.readlink(entry)))
        elif entry.is_dir():
            parts.extend((relative, "directory", mode))
        elif entry.is_file():
            parts.extend((relative, "file", mode, entry.read_bytes().hex()))
    return _digest(*parts)


def _valid_managed_paths(paths):
    if not isinstance(paths, list):
        return False
    return all(
        isinstance(item, str)
        and item
        and not item.startswith("/")
        and "\0" not in item
        and ".." not in PurePosixPath(item).parts
        for item in paths
    )


def _paths_conflict(first, second):
    if first == second:
        return True
    if first.startswith(second + "/"):
        return True
    return second.startswith(first + "/")


def _inspect(kind, name):
    result = run(["docker", kind, "inspect", name], check=False, capture=True)
    if result.returncode:
        if "no such" in result.stderr.lower():
            return None
        raise DamError(result.stderr.strip() or f"Cannot inspect {kind}: {name}")
    try:
        return json.loads(result.stdout)[0]
    except (ValueError, TypeError, IndexError, KeyError) as error:
        raise DamError(f"Invalid Docker {kind} inspection: {name}") from error


class Runtime:
    def __init__(self, store, state):
        self.store = store
        self.state = state
        self.name = state["name"]
        self.key = _digest(store.root.resolve(), self.name)
        self.container = f"dam-{self.name}-{self.key[:8]}"
        self.volume = f"dam-home-{self.key}"
        self.owner = str(store.root.resolve())

    def _owned(self, data, kind):
        if data is not None:
            labels = (
                (data.get("Config") or {}).get("Labels")
                if kind == "container"
                else data.get("Labels")
            ) or {}
            if labels.get("io.dam.root") != self.owner:
                raise DamError(f"Docker {kind} root label mismatch: {self.name}")
            if labels.get("io.dam.yard") != self.name:
                raise DamError(f"Docker {kind} yard label mismatch: {self.name}")
        return data

    def inspect(self):
        return self._owned(_inspect("container", self.container), "container")

    def is_running(self):
        data = self.inspect()
        return bool(data and data.get("State", {}).get("Running"))

    def _labels(self):
        return [
            "--label",
            f"io.dam.root={self.owner}",
            "--label",
            f"io.dam.yard={self.name}",
        ]

    def _ensure_volume(self):
        if self._owned(_inspect("volume", self.volume), "volume") is not None:
            return
        run(["docker", "volume", "create", *self._labels(), self.volume], capture=True)

    def _base_image(self):
        with build_context() as context:
            tag = f"dam-base:{_digest(self.owner, self.state['uid'], _tree_digest(context))}"
            if _inspect("image", tag) is None:
                run(
                    [
                        "docker",
                        "build",
                        "--tag",
                        tag,
                        "--build-arg",
                        f"DAM_UID={self.state['uid']}",
                        str(context),
                    ]
                )
        return tag

    def _blueprint_image(self, base):
        root = self.store.blueprint_dir(self.state["blueprint"])
        dockerfile = root / "Dockerfile"
        if not dockerfile.is_file():
            raise DamError(
                f"Blueprint Dockerfile is missing: {self.state['blueprint']}"
            )
        image_files = root / "image"
        with tempfile.TemporaryDirectory(prefix="dam-blueprint-") as directory:
            target = Path(directory)
            shutil.copy2(dockerfile, target / "Dockerfile")
            if image_files.is_dir():
                shutil.copytree(image_files, target / "image")
            fingerprint = _digest(base, _tree_digest(target))
            tag = (
                f"dam-blueprint-{_digest(self.owner, self.state['blueprint'])}:"
                f"{fingerprint}"
            )
            if _inspect("image", tag) is None:
                run(
                    [
                        "docker",
                        "build",
                        "--tag",
                        tag,
                        "--build-arg",
                        f"DAM_BASE_IMAGE={base}",
                        str(target),
                    ]
                )
        return tag

    def _image_home_paths(self, image):
        result = run(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                "root",
                "--entrypoint",
                "find",
                image,
                "/home/dam",
                "-mindepth",
                "1",
                "(",
                "-type",
                "f",
                "-o",
                "-type",
                "l",
                ")",
                "-print0",
            ],
            capture=True,
        )
        prefix = "/home/dam/"
        paths = []
        for path in result.stdout.split("\0"):
            if not path:
                continue
            if not path.startswith(prefix):
                raise DamError(f"Invalid image home path: {path}")
            paths.append(path[len(prefix) :])
        if not _valid_managed_paths(paths):
            raise DamError(f"Invalid image home paths: {image}")
        return sorted(set(paths))

    def _sync_home(self, image):
        source = self.store.blueprint_dir(self.state["blueprint"]) / "home"
        if not source.is_dir():
            raise DamError(f"Blueprint home is missing: {self.state['blueprint']}")
        manifest = self.store.object_dir("yard", self.name) / "managed.json"
        try:
            record = json.loads(manifest.read_text(encoding="utf-8"))
        except FileNotFoundError:
            record = {"paths": [], "image_paths": []}
        if (
            not isinstance(record, dict)
            or not _valid_managed_paths(record.get("paths"))
            or not _valid_managed_paths(record.get("image_paths", []))
        ):
            raise DamError(f"Invalid managed file record: {manifest}")
        old_paths = set(record["paths"]) | set(record.get("image_paths", []))
        paths = sorted(
            entry.relative_to(source).as_posix()
            for entry in source.rglob("*")
            if entry.is_file() or entry.is_symlink()
        )
        # A blueprint path takes precedence over conflicting image paths.
        image_paths = [
            path
            for path in self._image_home_paths(image)
            if not any(_paths_conflict(path, blueprint) for blueprint in paths)
        ]
        desired = set(paths) | set(image_paths)
        pending = {
            "paths": sorted(set(record["paths"]) | set(paths)),
            "image_paths": sorted(
                set(record.get("image_paths", [])) | set(image_paths)
            ),
        }
        if pending != record:
            self.store._atomic_json(manifest, pending)
        script = ["set -eu"]
        for relative in sorted(old_paths - desired, reverse=True):
            script.append(f"rm -rf -- {shlex.quote('/dam-home/' + relative)}")

        def copy_files(source_root, relatives):
            for relative in relatives:
                target = "/dam-home/" + relative
                parent = str(Path(target).parent)
                script.append(
                    f"if [ ! -d {shlex.quote(parent)} ]; then rm -rf -- {shlex.quote(parent)}; mkdir -p -- {shlex.quote(parent)}; fi"
                )
                script.append(f"rm -rf -- {shlex.quote(target)}")
                script.append(
                    f"cp -R -- {shlex.quote(source_root + relative)} {shlex.quote(target)}"
                )
                script.append(
                    f"chown -h {self.state['uid']}:{self.state['gid']} {shlex.quote(target)}"
                )

        copy_files("/home/dam/", image_paths)
        copy_files("/source/", paths)
        script.append(f"chown -R {self.state['uid']}:{self.state['gid']} /dam-home")
        with tempfile.TemporaryDirectory(prefix="dam-sync-") as directory:
            script_path = Path(directory) / "sync.sh"
            script_path.write_text("\n".join(script) + "\n", encoding="utf-8")
            run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--user",
                    "root",
                    "--mount",
                    _mount_spec(
                        "type=volume",
                        f"source={self.volume}",
                        "target=/dam-home",
                        "volume-nocopy",
                    ),
                    "--mount",
                    _mount_spec(
                        "type=bind", f"source={source}", "target=/source", "readonly"
                    ),
                    "--mount",
                    _mount_spec(
                        "type=bind",
                        f"source={script_path}",
                        "target=/sync.sh",
                        "readonly",
                    ),
                    "--entrypoint",
                    "sh",
                    image,
                    "/sync.sh",
                ]
            )
        self.store._atomic_json(manifest, {"paths": paths, "image_paths": image_paths})

    def _mount_fingerprint(self):
        return _digest(json.dumps(self.state["mounts"], sort_keys=True))

    def _create_container(self, image):
        command = [
            "docker",
            "container",
            "create",
            "--name",
            self.container,
            "--hostname",
            self.name,
            "--user",
            "dam",
            "--workdir",
            "/home/dam",
            *self._labels(),
            "--label",
            f"io.dam.mounts={self._mount_fingerprint()}",
            "--mount",
            _mount_spec(
                "type=volume",
                f"source={self.volume}",
                "target=/home/dam",
                "volume-nocopy",
            ),
        ]
        for name, source in sorted(self.state["mounts"].items()):
            if not Path(source).is_dir():
                raise DamError(f"Mount source is missing: {source}")
            command.extend(
                [
                    "--mount",
                    _mount_spec("type=bind", f"source={source}", f"target=/mnt/{name}"),
                ]
            )
        run([*command, image], capture=True)

    def ensure_running(self):
        with self.store.registry_lock():
            return self._ensure_running_locked()

    def _ensure_running_locked(self):
        current = self.inspect()
        if current and current.get("State", {}).get("Running"):
            return
        base = self._base_image()
        image = self._blueprint_image(base)
        self._ensure_volume()
        self._sync_home(image)
        stale = current and (
            current.get("Config", {}).get("Image") != image
            or (current.get("Config", {}).get("Labels") or {}).get("io.dam.mounts")
            != self._mount_fingerprint()
        )
        if stale:
            backup = f"{self.container}-old-{uuid.uuid4().hex[:8]}"
            run(["docker", "container", "rename", self.container, backup], capture=True)
            try:
                self._create_container(image)
                run(["docker", "container", "start", self.container], capture=True)
            except BaseException:
                run(
                    ["docker", "container", "rm", "-f", self.container],
                    check=False,
                    capture=True,
                )
                run(
                    ["docker", "container", "rename", backup, self.container],
                    capture=True,
                )
                raise
            run(["docker", "container", "rm", backup], capture=True)
            return
        if current is None:
            self._create_container(image)
        run(["docker", "container", "start", self.container], capture=True)

    def stop(self):
        if self.is_running():
            run(["docker", "container", "stop", self.container], capture=True)

    def delete(self):
        if self.is_running():
            raise DamError(f"Stop yard before deleting it: {self.name}")
        if self.inspect() is not None:
            run(["docker", "container", "rm", self.container], capture=True)
        if self._owned(_inspect("volume", self.volume), "volume") is not None:
            run(["docker", "volume", "rm", self.volume], capture=True)

    def shell(self, path="/home/dam"):
        self.ensure_running()
        return run(
            [
                "docker",
                "exec",
                "-it",
                "--user",
                "dam",
                "--workdir",
                path,
                self.container,
                "bash",
            ],
            check=False,
        ).returncode
