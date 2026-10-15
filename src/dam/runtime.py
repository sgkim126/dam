"""Docker operations shared by the command handlers.

All Docker arguments are passed as argv elements; no user input is evaluated by
an intermediate shell. Persistent state belongs to Store, not to the container.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from pathlib import Path

from .assets import build_context
from .errors import DamError
from .process import run

LABEL_WORKSPACE = "io.dam.workspace"
LABEL_ROOT = "io.dam.config-root"
READY_TIMEOUT = 60.0


def _mount_spec(*fields: str) -> str:
    output = io.StringIO()
    csv.writer(output, lineterminator="").writerow(fields)
    return output.getvalue()


def _error(result, fallback: str) -> DamError:
    message = (result.stderr or result.stdout or fallback).strip()
    return DamError(message, exit_code=result.returncode or 1)


def _missing(result) -> bool:
    message = (result.stderr or "").lower()
    return result.returncode != 0 and any(
        marker in message
        for marker in (
            "no such container",
            "no such image",
            "no such volume",
            "no such object",
        )
    )


class Runtime:
    def __init__(self, store, state: dict):
        self.store = store
        self.state = state
        self.name = state["name"]
        digest = hashlib.sha256(self.name.encode()).hexdigest()[:16]
        self.image = f"dam-workspace:{digest}"
        self.volume = f"dam-home-{digest}"
        self.labels = {
            LABEL_WORKSPACE: self.name,
            LABEL_ROOT: str(store.root.resolve()),
        }

    def _inspect(self, kind: str, name: str):
        result = run(["docker", kind, "inspect", name], check=False, capture=True)
        if _missing(result):
            return None
        if result.returncode:
            raise _error(result, f"Cannot inspect Docker {kind}: {name}")
        try:
            data = json.loads(result.stdout)
            if not isinstance(data, list) or len(data) != 1:
                raise ValueError("expected a list with exactly one item")
            if not isinstance(data[0], dict):
                raise TypeError("expected an object")
            return data[0]
        except (TypeError, ValueError) as error:
            raise DamError(
                f"Invalid Docker {kind} inspection response: {name}"
            ) from error

    def _check_labels(self, labels: dict | None, resource: str):
        if any((labels or {}).get(key) != value for key, value in self.labels.items()):
            raise DamError(
                f"Docker resource is not owned by this workspace: {resource}"
            )

    def inspect(self) -> dict | None:
        data = self._inspect("container", self.name)
        if data is not None:
            self._check_labels(data.get("Config", {}).get("Labels"), self.name)
        return data

    def is_running(self) -> bool:
        data = self.inspect()
        return data is not None and bool(data.get("State", {}).get("Running"))

    def _prepare_mounts(self):
        self.store.profile_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
        self.store.profile_dir.chmod(0o755)
        self.store.snapshot_dir(self.name).mkdir(
            parents=True, exist_ok=True, mode=0o700
        )
        sources = [
            self.store.profile_dir,
            self.store.workspace_dir(self.name),
            self.store.snapshot_dir(self.name),
        ]
        for source in sources:
            if not source.is_dir():
                raise DamError(
                    f"Bind mount source is not an existing directory: {source}"
                )
        for item in self.state.get("mounts", {}).values():
            source = Path(item["path"])
            if not source.exists():
                raise DamError(f"Bind mount source does not exist: {source}")
            if not (source.is_dir() or source.is_file()):
                raise DamError(
                    f"Bind mount source is not a file or directory: {source}"
                )
        manifest = self.store.workspace_dir(self.name) / "workspace.json"
        if not manifest.is_file():
            raise DamError(f"Workspace configuration is missing: {manifest}")

    def _ensure_volume(self):
        volume = self._inspect("volume", self.volume)
        if volume is not None:
            self._check_labels(volume.get("Labels"), self.volume)
            return
        command = ["docker", "volume", "create"]
        for key, value in self.labels.items():
            command.extend(["--label", f"{key}={value}"])
        run([*command, self.volume], capture=True)

    def _ensure_image(self):
        if self._inspect("image", self.image) is None:
            self.build()

    def build(self, no_cache: bool = False):
        # Refuse a colliding container before modifying the workspace image tag.
        self.inspect()
        command = ["docker", "build", "--pull", "--tag", self.image]
        if no_cache:
            command.append("--no-cache")
        with build_context() as context:
            run([*command, str(context)])

    def _create(self):
        command = [
            "docker",
            "container",
            "create",
            "--name",
            self.name,
            "--init",
            "--user",
            "root",
            "--workdir",
            "/home/node",
            "--env",
            "TERM=xterm-256color",
            "--env",
            "COLORTERM=truecolor",
            "--cap-drop",
            "ALL",
        ]
        for capability in (
            "CHOWN",
            "DAC_OVERRIDE",
            "FOWNER",
            "KILL",
            "SETUID",
            "SETGID",
        ):
            command.extend(["--cap-add", capability])
        for key, value in self.labels.items():
            command.extend(["--label", f"{key}={value}"])
        command.extend(
            [
                "--mount",
                _mount_spec("type=volume", f"source={self.volume}", "target=/home"),
            ]
        )
        for source, target in (
            (self.store.profile_dir, "/etc/dam/profile"),
            (self.store.workspace_dir(self.name), "/etc/dam/workspace"),
            (self.store.snapshot_dir(self.name), "/etc/dam/host-settings"),
        ):
            command.extend(
                [
                    "--mount",
                    _mount_spec(
                        "type=bind", f"source={source}", f"target={target}", "readonly"
                    ),
                ]
            )
        for name, mount in sorted(self.state.get("mounts", {}).items()):
            command.extend(
                [
                    "--mount",
                    _mount_spec(
                        "type=bind", f"source={mount['path']}", f"target=/mnt/{name}"
                    ),
                ]
            )
        run([*command, self.image], capture=True)

    def _wait_ready(self):
        deadline = time.monotonic() + READY_TIMEOUT
        while True:
            container = self.inspect()
            state = (container or {}).get("State", {})
            if not state.get("Running"):
                raise DamError(
                    f"Workspace container stopped during startup: {self.name}. Check docker logs {self.name}."
                )
            health = state.get("Health", {}).get("Status")
            if health == "healthy":
                return
            if health == "unhealthy":
                raise DamError(
                    f"Workspace container is unhealthy: {self.name}. Check docker logs {self.name}."
                )
            if time.monotonic() >= deadline:
                raise DamError(
                    f"Timed out waiting for workspace: {self.name}. Check docker logs {self.name}."
                )
            time.sleep(0.25)

    def ensure_running(self):
        self._prepare_mounts()
        container = self.inspect()
        if container is None:
            self._ensure_image()
            self._ensure_volume()
            self._create()
        elif container.get("State", {}).get("Paused"):
            raise DamError(f"Workspace container is paused: {self.name}")
        elif container.get("State", {}).get("Running"):
            self._wait_ready()
            return
        run(["docker", "container", "start", self.name], capture=True)
        self._wait_ready()

    def exec(self, argv, user="root", interactive=False, capture=False, check=True):
        command = ["docker", "container", "exec"]
        if interactive:
            command.append("--interactive")
            import sys

            if sys.stdin.isatty() and sys.stdout.isatty():
                command.append("--tty")
        command.extend(["--user", user, self.name, "dam-user-env", *map(str, argv)])
        return run(command, interactive=interactive, capture=capture, check=check)

    def stop(self):
        if self.inspect() is not None:
            run(["docker", "container", "stop", self.name], capture=True)

    def down(self):
        if self.inspect() is not None:
            run(["docker", "container", "rm", "--force", self.name], capture=True)

    def logs(self, tail=None, follow=False):
        if self.inspect() is None:
            raise DamError(f"Workspace has no container: {self.name}")
        command = ["docker", "container", "logs"]
        if tail is not None:
            command.extend(["--tail", str(tail)])
        if follow:
            command.append("--follow")
        return run([*command, self.name])

    def configuration(self) -> dict:
        return {
            "workspace": self.name,
            "container": self.name,
            "image": self.image,
            "home_volume": self.volume,
            "workspace_path": str(self.store.workspace_dir(self.name)),
            "profile_path": str(self.store.profile_dir),
            "settings_path": str(self.store.snapshot_dir(self.name)),
            "mounts": {
                name: {**item, "target": f"/mnt/{name}"}
                for name, item in sorted(self.state.get("mounts", {}).items())
            },
        }
