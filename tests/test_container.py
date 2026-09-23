"""Opt-in integration tests on a disposable container and home volume.

DAM_INTEGRATION_IMAGE=dam-users-test python3 -m unittest discover -s tests -p test_container.py -v
No existing dam containers, settings, homes, or workspaces are used.
"""

import json
from concurrent.futures import ThreadPoolExecutor
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

    def test_added_accounts_are_saved_and_share_workspace_without_restarting(self):
        self.node("tmux", "new-session", "-d", "-s", "keep-alive")
        tmux_pid = self.node("tmux", "display-message", "-p", "#{pid}").stdout
        self.admin("add", "alice")
        self.admin("add", "bob")
        self.assertEqual(self.node("tmux", "display-message", "-p", "#{pid}").stdout, tmux_pid)
        registry = json.loads(self.docker(
            "exec", "--user", "root", self.name, "cat", "/home/.dam/users.json",
        ).stdout)
        for name in ("alice", "bob"):
            self.assertEqual(registry["accounts"][name], {
                "uid": int(self.account(name, "id -u").stdout),
                "gid": int(self.account(name, "id -g").stdout),
            })
        environment = json.loads(self.account("alice", "python3 -c 'import json,os; print(json.dumps(dict(os.environ)))'").stdout)
        for key, suffix in (
            ("HOME", ""), ("GH_CONFIG_DIR", "/.config/gh"),
            ("GLAB_CONFIG_DIR", "/.config/glab-cli"), ("CODEX_HOME", "/.codex"),
            ("NPM_CONFIG_PREFIX", "/.local"),
        ):
            self.assertEqual(environment[key], "/home/alice" + suffix)
        self.assertNotIn("/home/node", environment["PATH"])
        nonlogin = json.loads(self.node("su", "alice", "-c", "python3 -c 'import json,os; print(json.dumps(dict(os.environ)))'").stdout)
        for key in ("HOME", "GH_CONFIG_DIR", "GLAB_CONFIG_DIR", "CODEX_HOME", "NPM_CONFIG_PREFIX", "PATH"):
            self.assertEqual(nonlogin[key], environment[key], key)
        self.assertEqual(self.node("su", "alice", "-c", "umask").stdout.strip(), "0002")
        self.account("alice", "su - bob -c 'su - node -c id'")
        self.assertNotEqual(self.account("alice", "cat /home/node/.bashrc", check=False).returncode, 0)

        self.account("alice", "cd /workspace; git init repo; cd repo; echo first > file; git add file; git -c user.name=Alice -c user.email=alice@example.test commit -m first")
        self.account("bob", "cd /workspace/repo; echo second >> file; git add file; git -c user.name=Bob -c user.email=bob@example.test commit -m second")
        self.node("bash", "-c", "cd /workspace/repo; echo third >> file; git add file; git -c user.name=Node -c user.email=node@example.test commit -m third")
        self.assertEqual(self.node("git", "-C", "/workspace/repo", "rev-list", "--count", "HEAD").stdout.strip(), "3")
        self.account("alice", "tmux new-session -d -s alice-session")
        self.assertNotEqual(self.node("tmux", "has-session", "-t", "alice-session", check=False).returncode, 0)

    def test_su_checks_users_group_without_adopting_unmanaged_accounts(self):
        self.admin("add", "alice")
        for args in (("su",), ("su", "-", "root"), ("su", "daemon")):
            self.assertNotEqual(self.node(*args, check=False).returncode, 0, args)
        self.docker("exec", "--user", "root", self.name, "useradd", "-M", "-u", "30000", "-s", "/bin/bash", "outsider")
        self.assertNotEqual(self.node("su", "-", "outsider", check=False).returncode, 0)
        self.assertNotEqual(self.docker("exec", "--user", "outsider", self.name, "su", "-", "alice", "-c", "id", check=False).returncode, 0)
        self.docker("exec", "--user", "root", self.name, "usermod", "--append", "--groups", "users", "outsider")
        self.assertEqual(self.node("su", "outsider", "-c", "id -un").stdout.strip(), "outsider")
        self.assertEqual(self.docker("exec", "--user", "outsider", self.name, "su", "-", "alice", "-c", "id -un").stdout.strip(), "alice")
        self.assertNotEqual(self.admin("add", "outsider", check=False).returncode, 0)

    def test_concurrent_additions_keep_unique_ids_and_one_registration(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda name: self.admin("add", name), ("alice", "bob", "alice", "_review")))
        identities = {self.account(name, "id -u").stdout.strip() for name in ("alice", "bob", "_review")}
        self.assertEqual(len(identities), 3)


if __name__ == "__main__":
    unittest.main()
