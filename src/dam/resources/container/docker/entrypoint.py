"""Restore workspace accounts and settings before accepting shell connections."""

import os
import subprocess
import sys
from pathlib import Path

READY = Path("/tmp/dam-ready")
HELPERS = Path("/usr/local/lib/dam")


def main():
    os.umask(0o077)
    READY.unlink(missing_ok=True)
    # Reapply the stored snapshot, without reading or refreshing host settings.
    subprocess.run(["python3", str(HELPERS / "users.py"), "sync"], check=True)
    subprocess.run(["python3", str(HELPERS / "shares.py"), "apply-all"], check=True)
    READY.touch(mode=0o644)
    command = sys.argv[1:] or ["sleep", "infinity"]
    os.execvp(
        "setpriv",
        [
            "setpriv",
            "--reuid=node",
            "--regid=node",
            "--init-groups",
            "/usr/local/bin/dam-user-env",
            *command,
        ],
    )


if __name__ == "__main__":
    main()
