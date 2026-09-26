#!/usr/bin/env python3
"""Stage allowlisted host settings without copying login or session state."""

from __future__ import annotations

import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import tomllib


MARKER = ".dam-settings-staging"
MARKER_CONTENT = "dam host settings staging v1\n"
MANAGED_NAMES = ("codex", "agents", "tmux.conf", "nvim", "vimrc", "vim")
CREDENTIAL_KEY = re.compile(
    r"token|secret|password|passwd|api_?key|authorization|cookie|private_?key|credential",
    re.IGNORECASE,
)


def copy_asset(
    source: Path, target: Path, ancestors: frozenset = frozenset(),
    *, excluded: frozenset = frozenset(),
) -> None:
    """Dereference host symlinks, including skills linked outside the host home."""
    if not source.exists():
        return
    info = source.stat()
    identity = (info.st_dev, info.st_ino)
    if identity in excluded:
        return
    if stat.S_ISDIR(info.st_mode):
        if identity in ancestors:
            raise ValueError(f"Symlink cycle in settings: {source}")
        target.mkdir(parents=True, exist_ok=True)
        target.chmod(0o755)
        for child in sorted(source.iterdir()):
            if child.name in {".git", ".DS_Store", "__pycache__", "logs"}:
                continue
            if child.name.endswith((".pyc", ".pyo", ".log")):
                continue
            copy_asset(child, target / child.name, ancestors | {identity}, excluded=excluded)
    elif stat.S_ISREG(info.st_mode):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        # The Linux container user must be able to read the read-only mount.
        target.chmod(0o755 if info.st_mode & 0o111 else 0o644)


def redact_credentials(config: dict) -> list[str]:
    skipped = []
    tables = []
    servers = config.get("mcp_servers", {})
    if not isinstance(servers, dict):
        servers = {}
    for name, server in servers.items():
        if not isinstance(server, dict):
            continue
        tables.extend(
            (f"mcp_servers.{name}.{field}", server.get(field, {}))
            for field in ("env", "http_headers")
        )
        # Keep references such as bearer_token_env_var; remove literal secrets.
        for key in list(server):
            if key in {"bearer_token", "api_key", "password", "client_secret"}:
                del server[key]
                skipped.append(f"mcp_servers.{name}.{key}")
    policy = config.get("shell_environment_policy", {})
    if isinstance(policy, dict):
        tables.append(("shell_environment_policy.set", policy.get("set", {})))
    for prefix, table in tables:
        if not isinstance(table, dict):
            continue
        for key in list(table):
            if CREDENTIAL_KEY.search(key.replace("-", "_")):
                del table[key]
                skipped.append(f"{prefix}.{key}")
    profiles = config.get("profiles", {})
    if isinstance(profiles, dict):
        for name, profile in profiles.items():
            if isinstance(profile, dict):
                skipped.extend(f"profiles.{name}.{key}" for key in redact_credentials(profile))
    return skipped


def toml_value(value) -> str:
    """Serialize parsed TOML using inline tables; the host needs no pip package."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(
            f"{json.dumps(key, ensure_ascii=False)} = {toml_value(item)}"
            for key, item in value.items()
        ) + " }"
    raise TypeError(f"Unsupported TOML value: {type(value).__name__}")


def stage_codex_config(source: Path, target: Path) -> None:
    if not source.is_file():
        return
    config = tomllib.loads(source.read_text())
    for key in redact_credentials(config):
        print(f"Omitted credential setting: {json.dumps(key)}")
    content = serialize_config(config)
    tomllib.loads(content)  # Verify serialization before replacing live staging.
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    target.chmod(0o644)


def serialize_config(config: dict) -> str:
    return "# Generated from host settings; host login and history are not shared.\n" + "".join(
        f"{json.dumps(key, ensure_ascii=False)} = {toml_value(value)}\n"
        for key, value in config.items()
    )


def prepare(host_home: Path, destination: Path) -> None:
    host_home = host_home.expanduser().resolve()
    destination = destination.expanduser().absolute()
    if destination.is_symlink():
        raise ValueError("The staging destination must not be a symlink")
    destination = destination.resolve()
    if destination == host_home or destination in host_home.parents:
        raise ValueError("The staging destination must not replace the host home or its parents")
    if destination.exists():
        if not destination.is_dir():
            raise ValueError("The staging destination must be a directory")
        marker = destination / MARKER
        if any(destination.iterdir()) and (
            marker.is_symlink() or not marker.is_file()
            or marker.read_text() != MARKER_CONTENT
        ):
            raise ValueError("Refusing to modify a nonempty directory without the staging marker")
    destination.mkdir(parents=True, exist_ok=True)
    destination.chmod(0o755)
    # Staging may be inside a copied settings tree, including through a symlink.
    destination_info = destination.stat()
    excluded = frozenset({(destination_info.st_dev, destination_info.st_ino)})
    marker = destination / MARKER
    if marker.is_symlink():
        raise ValueError("The staging marker must not be a symlink")
    marker.write_text(MARKER_CONTENT)
    marker.chmod(0o644)

    # Keep the destination inode: Docker bind mounts continue to see refreshes.
    with marker.open("r+") as lock, tempfile.TemporaryDirectory(prefix=".prepare-", dir=destination) as temporary:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pending = Path(temporary)
        stage_codex_config(host_home / ".codex/config.toml", pending / "codex/config.toml")
        skills = host_home / ".codex/skills"
        if skills.is_dir():
            for skill in skills.iterdir():
                if skill.name != ".system":
                    copy_asset(skill, pending / "codex/skills" / skill.name, excluded=excluded)
        for name in ("AGENTS.md", "rules", "agents"):
            copy_asset(host_home / ".codex" / name, pending / "codex" / name, excluded=excluded)
        for source, target in (
            (".agents/skills", "agents/skills"),
            (".tmux.conf", "tmux.conf"),
            (".config/nvim", "nvim"),
            (".vimrc", "vimrc"),
        ):
            copy_asset(host_home / source, pending / target, excluded=excluded)
        for name in ("autoload", "config", "colors", "after", "plugins.vim"):
            copy_asset(host_home / ".vim" / name, pending / "vim" / name, excluded=excluded)
        for name in MANAGED_NAMES:
            current = destination / name
            replacement = pending / name
            if current.exists() or current.is_symlink():
                # Renaming first also handles previous symlinks without following them.
                os.replace(current, pending / f".previous-{name}")
            if replacement.exists():
                os.replace(replacement, current)
    print("Host settings staged; host authentication and session files were excluded.")


def main() -> None:
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_absolute():
        sys.exit("Usage: prepare-settings.py ABSOLUTE_DESTINATION")
    prepare(Path.home(), Path(sys.argv[1]))


if __name__ == "__main__":
    main()
