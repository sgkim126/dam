#!/usr/bin/env bash
set -euo pipefail
# Docker exec does not run login startup files. Apply the same shared-file
# permissions as login shells before executing the requested command.
source /etc/profile.d/dam.sh
exec "$@"
