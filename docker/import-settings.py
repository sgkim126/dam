#!/usr/bin/env python3
"""Import staged host preferences, leaving container identities and sessions alone."""

from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import tomllib


_spec = importlib.util.spec_from_file_location(
    "dam_prepare_settings", Path(__file__).with_name("prepare-settings.py")
)
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)


EXCLUDED_CODEX_KEYS = {"projects", "desktop", "notify", "marketplaces", "plugins"}
MAC_PATHS = ("/Users/", "/Applications/", "/opt/homebrew", "/Volumes/")
MIRROR_PREFIXES = (
    ".config/nvim/", ".vim/autoload/", ".vim/config/", ".vim/colors/", ".vim/after/",
)
MIRROR_FILES = {".vimrc", ".vim/plugins.vim"}


def atomic_write(path: Path, content: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".dam-", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.fchmod(handle.fileno(), mode)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def mac_path(value) -> bool:
    if isinstance(value, str):
        return any(part in value for part in MAC_PATHS)
    if isinstance(value, list):
        return any(mac_path(item) for item in value)
    return False


def portable_codex_config(source: Path, asset_root: Path) -> tuple[str, list[str]]:
    config = tomllib.loads(source.read_text()) if source.is_file() else {}
    skipped = _shared.redact_credentials(config)
    for key in EXCLUDED_CODEX_KEYS:
        if key in config:
            del config[key]
            skipped.append(key)
    servers = config.get("mcp_servers", {})
    if isinstance(servers, dict):
        for name in list(servers):
            server = servers[name]
            normalized = name.lower().replace("_", "-")
            if normalized in {"node-repl", "cua-repl"} or "computer-use" in normalized or (
                isinstance(server, dict)
                and any(mac_path(server.get(key)) for key in ("command", "cwd", "args"))
            ):
                del servers[name]
                skipped.append(f"mcp_servers.{name}")
                continue
    skills = config.get("skills", {})
    if isinstance(skills, dict) and isinstance(skills.get("config"), list):
        portable_skills = []
        for index, skill in enumerate(skills["config"]):
            if isinstance(skill, dict) and isinstance(skill.get("path"), str):
                portable = shared_asset_path(skill["path"], asset_root)
                if portable is not None:
                    skill["path"] = portable
                elif mac_path(skill["path"]):
                    skipped.append(f"skills.config[{index}].path")
                    continue
            portable_skills.append(skill)
        skills["config"] = portable_skills
    agents = config.get("agents", {})
    if isinstance(agents, dict):
        for name in list(agents):
            agent = agents[name]
            if isinstance(agent, dict) and isinstance(agent.get("config_file"), str):
                portable = shared_asset_path(agent["config_file"], asset_root)
                if portable is not None:
                    agent["config_file"] = portable
                elif mac_path(agent["config_file"]):
                    del agents[name]
                    skipped.append(f"agents.{name}.config_file")
    config["cli_auth_credentials_store"] = "file"
    return _shared.serialize_config(config), sorted(skipped)


def shared_asset_path(value: str, asset_root: Path) -> str | None:
    match = re.fullmatch(
        r"(?:/(?:Users|home)/[^/]+|/root)/(\.codex/(?:skills|agents|rules)|\.agents/skills)(/.*)?",
        value,
    )
    if match is None or ".." in Path(value).parts:
        return None
    return str(asset_root / (match[1].removeprefix(".") + (match[2] or "")))


def safe_parent(home: Path, target: Path) -> None:
    """Never write through a symlink in a destination directory."""
    relative = target.relative_to(home)
    current = home
    for component in relative.parts[:-1]:
        current /= component
        if current.is_symlink():
            raise ValueError(f"Refusing to write settings through symlink: {current}")
        current.mkdir(exist_ok=True)


def attach(source: Path, target: Path, home: Path, source_root: Path) -> None:
    safe_parent(home, target)
    if not source.exists():
        if target.is_symlink() and str(target.readlink()).startswith(str(source_root) + "/"):
            target.unlink()
        return
    if target.is_symlink() and target.readlink() == source:
        return
    if target.exists() or target.is_symlink():
        backup = target.with_name(target.name + ".before-host-settings")
        suffix = 1
        while backup.exists() or backup.is_symlink():
            backup = target.with_name(target.name + f".before-host-settings-{suffix}")
            suffix += 1
        target.rename(backup)
        print(f"Preserved existing container setting: {target.relative_to(home)}")
    target.symlink_to(source)


def attach_skills(source: Path, target: Path, home: Path, source_root: Path) -> None:
    safe_parent(home, target)
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        backup = target.with_name(target.name + ".before-host-settings")
        suffix = 1
        while backup.exists() or backup.is_symlink():
            backup = target.with_name(target.name + f".before-host-settings-{suffix}")
            suffix += 1
        target.rename(backup)
    target.mkdir(exist_ok=True)
    names = {asset.name for asset in source.iterdir()} if source.is_dir() else set()
    names.discard(".system")
    for existing in target.iterdir():
        if existing.name not in names and existing.is_symlink() and str(existing.readlink()).startswith(str(source) + "/"):
            existing.unlink()
    for name in sorted(names):
        attach(source / name, target / name, home, source_root)


def valid_mirror_path(relative: str) -> bool:
    path = Path(relative)
    return not path.is_absolute() and ".." not in path.parts and (
        relative in MIRROR_FILES or any(relative.startswith(prefix) for prefix in MIRROR_PREFIXES)
    )


def mirror_editor_settings(source: Path, home: Path) -> None:
    manifest = home / ".local/state/dam-settings/imported-files.json"
    previous = set()
    if manifest.is_file():
        values = json.loads(manifest.read_text())
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError("Invalid imported settings manifest")
        previous = {value for value in values if valid_mirror_path(value)}
    files = {}
    for source_name, target_name in (("nvim", ".config/nvim"), ("vim", ".vim")):
        directory = source / source_name
        if directory.is_dir():
            for asset in directory.rglob("*"):
                if asset.is_file():
                    relative = str(Path(target_name) / asset.relative_to(directory))
                    if valid_mirror_path(relative):
                        files[relative] = asset
    if (source / "vimrc").is_file():
        files[".vimrc"] = source / "vimrc"
    for relative, asset in files.items():
        target = home / relative
        safe_parent(home, target)
        mode = 0o755 if asset.stat().st_mode & 0o111 else 0o644
        atomic_write(target, asset.read_bytes(), mode)
    for relative in sorted(previous - files.keys()):
        target = home / relative
        safe_parent(home, target)
        if target.is_file() or target.is_symlink():
            target.unlink()
    safe_parent(home, manifest)
    atomic_write(manifest, (json.dumps(sorted(files), indent=2) + "\n").encode())


def import_system_settings(source: Path, system_config: Path) -> None:
    """Write only common settings; the administrator owns the shared lock."""
    config, skipped = portable_codex_config(source / "codex/config.toml", source)
    atomic_write(system_config, config.encode())
    for key in skipped:
        print(f"Skipped host-only Codex setting: {json.dumps(key)}")


def import_user_settings(source: Path, home: Path) -> None:
    """Run as the destination user, preserving their identity and session data."""
    attach_skills(source / "codex/skills", home / ".codex/skills", home, source)
    for name in ("rules", "agents", "AGENTS.md"):
        attach(source / "codex" / name, home / ".codex" / name, home, source)
    attach_skills(source / "agents/skills", home / ".agents/skills", home, source)
    attach(source / "tmux.conf", home / ".tmux.conf", home, source)
    mirror_editor_settings(source, home)
    for name in ("undo", "plugged"):
        directory = home / ".vim" / name
        safe_parent(home, directory / ".placeholder")
    print("Host preferences imported; container login, history, and local Codex config retained.")


def import_settings(
    source: Path,
    home: Path,
    system_config: Path,
    *,
    system_only: bool,
) -> None:
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise ValueError("Host settings mount is missing; run the host launcher first")
    if system_only:
        import_system_settings(source, system_config)
        return
    home = home.expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)
    lock_path = home / ".local/state/dam-settings/import.lock"
    safe_parent(home, lock_path)
    if lock_path.is_symlink():
        raise ValueError(f"Refusing to use a symlink for the settings lock: {lock_path}")
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        import_user_settings(source, home)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--system-only", action="store_true", help="Import common settings without touching a home")
    mode.add_argument("--user-only", action="store_false", dest="system_only", help="Import user settings without changing the system config")
    args = parser.parse_args()
    import_settings(
        Path("/mnt/host-settings"), Path.home(), Path("/etc/codex/config.toml"),
        system_only=args.system_only,
    )


if __name__ == "__main__":
    main()
