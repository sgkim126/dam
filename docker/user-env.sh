#!/usr/bin/env bash
set -euo pipefail
# Docker exec does not run login startup files. Use the same identity-based
# defaults as su/login shells before executing the requested command.
source /etc/profile.d/dam.sh
exec "$@"
