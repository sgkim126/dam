#!/usr/bin/env bash
set -euo pipefail

dam_session=$1
dam_config="$HOME/$dam_session.tmux.conf"

if [[ ! -f "$dam_config" ]]; then
  exec tmux new-session -A -s "$dam_session"
fi

if ! tmux has-session -t "=$dam_session" 2>/dev/null; then
  tmux new-session -d -s "$dam_session" \; source-file -t "=$dam_session:" "$dam_config"
fi
exec tmux attach-session -t "=$dam_session"
