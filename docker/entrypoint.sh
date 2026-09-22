#!/usr/bin/env bash
set -euo pipefail
umask 077
rm -f /tmp/dam-ready
python3 /usr/local/lib/dam/import-settings.py
touch /tmp/dam-ready
exec "$@"
