"""A stateful fake Docker adapter for lifecycle contract tests."""

import copy
import json
import subprocess
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from dam.errors import DamError
from dam.model import new_workspace
from dam.runtime import Runtime
from dam.store import Store


class FakeDocker:
    def __init__(self):
        self.calls = []
        self.containers = {}
        self.volumes = {}
        self.images = set()
        self.fail = None
        self.daemon_error = False
        self.next_id = 1

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append(argv)
        kind, action = argv[1:3]
        stdout, stderr, code = "", "", 0
        if self.daemon_error:
            code, stderr = 1, "Cannot connect to the Docker daemon"
        elif self.fail == (kind, action):
            self.fail = None
            code, stderr = 17, "injected Docker failure"
        elif kind == "build":
            self.images.add(argv[argv.index("--tag") + 1])
        elif action == "inspect":
            name = argv[-1]
            values = (
                self.containers
                if kind == "container"
                else self.volumes
                if kind == "volume"
                else {name: {} for name in self.images}
            )
            if name in values:
                stdout = json.dumps([values[name]])
            else:
                code, stderr = 1, f"Error: No such {kind}: {name}"
        elif kind == "volume" and action == "create":
            self.volumes[argv[-1]] = {
                "Labels": self.labels(argv),
            }
        elif kind == "container" and action == "create":
            name = argv[argv.index("--name") + 1]
            self.containers[name] = {
                "Id": str(self.next_id).zfill(64),
                "Config": {
                    "Labels": self.labels(argv),
                },
                "State": {
                    "Running": False,
                    "Status": "created",
                    "Health": {
                        "Status": "healthy",
                    },
                },
            }
            self.next_id += 1
        elif kind == "container" and action in ("start", "stop"):
            self.containers[argv[-1]]["State"].update(
                Running=action == "start",
                Status="running" if action == "start" else "exited",
            )
        elif kind == "container" and action == "rename":
            self.containers[argv[-1]] = self.containers.pop(argv[-2])
        elif kind == "container" and action == "rm":
            del self.containers[argv[-1]]
        elif kind == "container" and action in ("exec", "logs"):
            stdout = "sample output\n"
        else:
            raise AssertionError(f"Unexpected Docker command: {argv}")
        result = subprocess.CompletedProcess(argv, code, stdout, stderr)
        if code and kwargs.get("check", True):
            raise DamError(stderr, exit_code=code)
        return result

    @staticmethod
    def labels(argv):
        return dict(
            argv[index + 1].split("=", 1)
            for index, arg in enumerate(argv)
            if arg == "--label"
        )


class RuntimeTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dam-runtime-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / "config")
        self.state = new_workspace("dev")
        self.store.create(self.state)
        self.runtime = Runtime(self.store, self.state)
        self.docker = FakeDocker()
        patcher = patch("dam.runtime.run", self.docker)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch(
            "dam.runtime.build_context",
            lambda: nullcontext(self.root / "packaged-context"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def running(self):
        self.runtime.ensure_running()
        self.docker.calls.clear()
        return copy.deepcopy(self.docker.containers["dev"])
