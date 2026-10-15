"""Opt-in checks using disposable real Docker containers and volumes.

Run with DAM_RUN_INTEGRATION=1. DAM_INTEGRATION_IMAGE may name an already
built image containing the packaged dam Docker assets; only a unique test tag
is added to it. Host preferences and credentials are never used by this test.
"""

import os
import tempfile
import unittest
import uuid
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from dam.commands import workspace_init
from dam.model import new_workspace
from dam.process import run
from dam.runtime import Runtime
from dam.store import Store


@unittest.skipUnless(
    os.environ.get("DAM_RUN_INTEGRATION") == "1",
    "set DAM_RUN_INTEGRATION=1 to use Docker",
)
class ContainerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dam-integration-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.host_home = self.root / "host-home"
        self.host_home.mkdir(mode=0o700)
        self.store = Store(self.root / "config")
        self.name = "dam-it-" + uuid.uuid4().hex[:16]
        self.runtime = Runtime(self.store, new_workspace(self.name))
        self.addCleanup(self.cleanup_docker)
        source_image = os.environ.get("DAM_INTEGRATION_IMAGE")
        if source_image:
            run(["docker", "image", "tag", source_image, self.runtime.image])

    def cleanup_docker(self):
        # Ownership is checked before removal, including when initialization failed.
        self.runtime.down()
        volume = self.runtime._inspect("volume", self.runtime.volume)
        if volume is not None:
            self.runtime._check_labels(volume.get("Labels"), self.runtime.volume)
            run(["docker", "volume", "rm", self.runtime.volume], capture=True)
        run(["docker", "image", "rm", self.runtime.image], check=False, capture=True)

    def test_initialize_environment_and_home_survive_container_recreation(self):
        with patch.object(workspace_init.Path, "home", return_value=self.host_home):
            workspace_init.run(Namespace(workspace=self.name), self.store)
        self.runtime = Runtime(self.store, self.store.load(self.name))
        self.assertTrue(self.runtime.is_running())
        identity = self.runtime.exec(
            [
                "python3",
                "-c",
                'import os; print(os.getuid()); print(os.environ["HOME"])',
            ],
            user="node",
            capture=True,
        )
        self.assertEqual(identity.stdout.splitlines(), ["1000", "/home/node"])
        self.runtime.exec(
            [
                "python3",
                "-c",
                (
                    "import shutil; assert all(shutil.which(name) for name in "
                    '("node", "npm", "tmux", "nvim", "gh", "glab"))'
                ),
            ],
            user="node",
            capture=True,
        )
        self.runtime.exec(
            [
                "python3",
                "-c",
                'from pathlib import Path; Path("/home/node/persist.txt").write_text("keep home data")',
            ],
            user="node",
            capture=True,
        )
        before = self.runtime.inspect()["Id"]
        self.runtime.recreate()
        self.assertNotEqual(self.runtime.inspect()["Id"], before)
        contents = self.runtime.exec(
            ["cat", "/home/node/persist.txt"], user="node", capture=True
        )
        self.assertEqual(contents.stdout, "keep home data")
        self.assertEqual(self.store.load(self.name)["users"]["node"]["uid"], 1000)
        # Boot never implicitly creates a tmux session.
        self.assertNotEqual(
            self.runtime.exec(
                ["tmux", "list-sessions"], user="node", capture=True, check=False
            ).returncode,
            0,
        )
