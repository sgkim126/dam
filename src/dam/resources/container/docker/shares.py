"""Apply explicitly requested group sharing to mount roots only."""

import argparse
import json
import os
import stat
from pathlib import Path

CONFIG = Path("/etc/dam/workspace/workspace.json")


def apply(path: Path, gid: int):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        mode = stat.S_IMODE(before.st_mode) | stat.S_IRWXG | stat.S_ISGID
        # Without CAP_FSETID Linux clears setgid unless the caller belongs to it.
        groups = os.getgroups()
        if gid not in groups:
            os.setgroups([*groups, gid])
        os.fchown(descriptor, -1, gid)
        # chown may clear setuid/setgid; restore the complete desired mode after it.
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("apply", "apply-all"))
    parser.add_argument("name", nargs="?")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Sharing mounts requires root")
    state = json.loads(CONFIG.read_text())
    mounts = state["mounts"]
    if args.action == "apply":
        if args.name not in mounts:
            parser.error("Unknown mount")
        names = [args.name]
    else:
        if args.name is not None:
            parser.error("apply-all takes no mount name")
        names = [name for name, mount in mounts.items() if mount["shared"]]
    for name in names:
        apply(Path("/mnt") / name, state["shared_gid"])


if __name__ == "__main__":
    main()
