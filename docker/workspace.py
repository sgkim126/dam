#!/usr/bin/env python3
"""Prepare the workspace root for new shared files without inspecting its contents."""

import grp
import os
from pathlib import Path
import stat
import sys


NOFOLLOW = os.O_NOFOLLOW | os.O_CLOEXEC


def prepare_workspace(workspace: Path, gid: int) -> None:
    """Set the root's shared group and permissions, leaving all children alone."""
    descriptor = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        mode = stat.S_IMODE(info.st_mode)
        desired = (mode & ~(stat.S_ISUID | stat.S_ISVTX)) | 0o070 | stat.S_ISGID
        if info.st_gid != gid:
            os.fchown(descriptor, -1, gid)
        if info.st_gid != gid or mode != desired:
            os.fchmod(descriptor, desired)
    finally:
        os.close(descriptor)


def main() -> None:
    if sys.argv[1:]:
        sys.exit("Usage: workspace.py")
    try:
        if os.geteuid() != 0:
            raise ValueError("Workspace permissions must be initialized as root")
        gid = grp.getgrnam("users").gr_gid
        os.setgroups(sorted(set(os.getgroups()) | {gid}))
        prepare_workspace(Path("/workspace"), gid)
    except (OSError, ValueError, KeyError) as error:
        sys.exit(f"Workspace sharing failed: {error}")


if __name__ == "__main__":
    main()
