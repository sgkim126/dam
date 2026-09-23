"""Opt-in integration tests on a disposable container and home volume.

DAM_INTEGRATION_IMAGE=dam-users-test python3 -m unittest discover -s tests -p test_container.py -v
No existing dam containers, settings, homes, or workspaces are used.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid


@unittest.skipUnless(os.environ.get("DAM_INTEGRATION_IMAGE"), "set DAM_INTEGRATION_IMAGE to a built dam image")
class ContainerAccountTests(unittest.TestCase):
    def docker(self, *args, check=True):
        result = subprocess.run(
            ["docker", *args], text=True, capture_output=True, timeout=90,
        )
        if check and result.returncode:
            self.fail(f"docker {args!r}:\n{result.stdout}\n{result.stderr}")
        return result

    def setUp(self):
        self.image = os.environ["DAM_INTEGRATION_IMAGE"]
        self.name = "dam-test-" + uuid.uuid4().hex[:12]
        self.home_volume = self.name + "-users"
        self.temporary = Path(tempfile.mkdtemp(prefix="dam-container-")).resolve()
        self.workspace = self.temporary / "workspace"
        self.settings = self.temporary / "settings"
        self.workspace.mkdir()
        self.settings.mkdir()
        self.addCleanup(self.cleanup)
        # First use of the empty /home volume copies the image's node home.
        self.start_container()

    def cleanup(self):
        self.docker("exec", "--user", "root", self.name, "chmod", "-R", "a+rwX", "/workspace", check=False)
        self.docker("rm", "-f", self.name, check=False)
        self.docker("volume", "rm", self.home_volume, check=False)
        # The test deliberately changes bind-mounted group ownership. Restore
        # permissions before removing only this test's temporary directory.
        shutil.rmtree(self.temporary, ignore_errors=True)

    def start_container(self):
        args = ["run", "-d", "--name", self.name, "--network", "none", "--init", "--cap-drop", "ALL"]
        for capability in ("CHOWN", "DAC_OVERRIDE", "FOWNER", "KILL", "SETUID", "SETGID"):
            args.extend(["--cap-add", capability])
        args.extend([
            "--mount", f"type=bind,source={self.workspace},target=/workspace",
            "--mount", f"type=bind,source={self.settings},target=/mnt/host-settings,readonly",
            "--mount", f"type=volume,source={self.home_volume},target=/home",
            self.image,
        ])
        self.docker(*args)
        for _ in range(100):
            if self.docker("exec", self.name, "test", "-f", "/tmp/dam-ready", check=False).returncode == 0:
                return
            if self.docker("inspect", "--format", "{{.State.Running}}", self.name).stdout.strip() != "true":
                break
            time.sleep(0.1)
        self.fail("container did not become ready:\n" + self.docker("logs", self.name, check=False).stdout)

    def admin(self, *args, check=True):
        return self.docker("exec", "--user", "root", self.name, "python3", "/usr/local/lib/dam/users.py", *args, check=check)

    def node(self, *args, check=True):
        return self.docker("exec", "--user", "node", self.name, "dam-user-env", *args, check=check)

    def account(self, name, command, check=True):
        return self.node("su", "-", name, "-c", command, check=check)

    def test_registered_accounts_and_homes_survive_container_recreation(self):
        seed_registry = """
import json
from pathlib import Path
registry = Path('/home/.dam/users.json')
state = json.loads(registry.read_text())
state['accounts']['alice'] = {'uid': 2345, 'gid': 2346}
registry.write_text(json.dumps(state))
"""
        self.docker("exec", "--user", "root", self.name, "python3", "-c", seed_registry)
        self.admin("sync")
        self.assertEqual(self.account("alice", "id -u").stdout.strip(), "2345")
        self.assertEqual(self.account("alice", "id -g").stdout.strip(), "2346")
        self.account("alice", "printf alice-state > ~/.codex/auth.json")
        self.node("bash", "-c", "printf node-state > ~/.codex/auth.json")
        original = json.loads(self.docker(
            "exec", "--user", "root", self.name, "cat", "/home/.dam/users.json",
        ).stdout)

        # Discard /etc accounts while retaining the shared home volume.
        self.docker("rm", "-f", self.name)
        self.start_container()
        self.assertEqual(self.account("alice", "id -u").stdout.strip(), "2345")
        self.assertEqual(self.account("alice", "id -g").stdout.strip(), "2346")
        self.assertEqual(self.account("alice", "pwd").stdout.strip(), "/home/alice")
        self.assertEqual(self.account("alice", "cat ~/.codex/auth.json").stdout, "alice-state")
        self.assertEqual(self.account("alice", "stat -c '%u:%g' ~/.codex/auth.json").stdout.strip(), "2345:2346")
        self.assertEqual(self.node("cat", "/home/node/.codex/auth.json").stdout, "node-state")
        restored = json.loads(self.docker(
            "exec", "--user", "root", self.name, "cat", "/home/.dam/users.json",
        ).stdout)
        self.assertEqual(restored, original)


if __name__ == "__main__":
    unittest.main()
