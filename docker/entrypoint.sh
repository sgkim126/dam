#!/usr/bin/env bash
set -euo pipefail
umask 077
rm -f /tmp/dam-ready
python3 /usr/local/lib/dam/workspace.py
python3 /usr/local/lib/dam/import-settings.py --system-only
setpriv --reuid=node --regid=node --init-groups dam-user-env python3 /usr/local/lib/dam/import-settings.py --user-only
touch /tmp/dam-ready
exec setpriv --reuid=node --regid=node --init-groups dam-user-env "$@"
