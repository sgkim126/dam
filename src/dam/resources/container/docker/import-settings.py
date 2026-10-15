"""Initialize the user's shell environment and shared profile."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import stat
import tempfile
from pathlib import Path


def atomic_write(path: Path, content: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=".dam-", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.fchmod(handle.fileno(), mode)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def managed_block(
    content: str, label: str, lines: list[str], *, first: bool = False
) -> str:
    start, end = f"# >>> dam {label} >>>", f"# <<< dam {label} <<<"
    if content.splitlines().count(start) != content.splitlines().count(end):
        raise ValueError(f"Incomplete dam {label} block in .bashrc")
    if content.splitlines().count(start) > 1:
        raise ValueError(f"Repeated dam {label} block in .bashrc")
    block = start + "\n" + "\n".join(lines) + "\n" + end + "\n"
    pattern = re.compile(
        r"^" + re.escape(start) + r"\n.*?^" + re.escape(end) + r"(?:\n|$)",
        re.MULTILINE | re.DOTALL,
    )
    if start in content.splitlines():
        if not pattern.search(content):
            raise ValueError(f"Invalid dam {label} block in .bashrc")
        return pattern.sub(lambda match: block, content)
    return block + content if first else content.rstrip("\n") + "\n\n" + block


def initialize_shell(home: Path, profile: str | None = None) -> None:
    """Keep personal shell settings and make new accounts usable immediately."""
    bashrc = home / ".bashrc"
    if bashrc.is_symlink():
        raise ValueError(f"Refusing to write shell settings through symlink: {bashrc}")
    if bashrc.exists():
        content = bashrc.read_text()
        mode = stat.S_IMODE(bashrc.stat().st_mode)
    else:
        skeleton = Path("/etc/skel/.bashrc")
        content = (
            skeleton.read_text()
            if skeleton.is_file() and not skeleton.is_symlink()
            else ""
        )
        mode = 0o644
    content = managed_block(
        content,
        "environment",
        [
            "if [ -f /etc/profile.d/dam.sh ]; then . /etc/profile.d/dam.sh; fi",
        ],
        first=True,
    )
    profile_lines = ["alias vi=nvim"]
    if profile is not None:
        if profile in {".", ".."}:
            raise ValueError(f"Reserved profile name: {profile!r}")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", profile):
            raise ValueError("Invalid profile name")
        source = shlex.quote("/etc/dam/profile/" + profile)
        profile_lines.append(
            f"if [ -f {source} ] && [ -r {source} ] && [ ! -L {source} ]; then . {source}; fi"
        )
    content = managed_block(content, "profile", profile_lines)
    atomic_write(bashrc, content.encode(), mode)

    login_files = [home / name for name in (".bash_profile", ".bash_login", ".profile")]
    if not any(path.exists() or path.is_symlink() for path in login_files):
        atomic_write(
            home / ".profile",
            b'if [ -n "${BASH_VERSION:-}" ] && [ -f "$HOME/.bashrc" ]; then . "$HOME/.bashrc"; fi\n',
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--shell-only",
        action="store_true",
        help="Update the managed Bash profile block only",
    )
    parser.add_argument(
        "--profile", help="Global shell profile selected for this account"
    )
    args = parser.parse_args()
    initialize_shell(Path.home(), args.profile)


if __name__ == "__main__":
    main()
