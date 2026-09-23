# Shared by login shells, interactive bashrc, and dam-user-env.
# Resolve the actual uid; never carry another user's home or CLI paths over.
dam_identity=$(getent passwd "$(id -u)") || return 1
HOME=$(printf '%s\n' "$dam_identity" | cut -d: -f6)
USER=$(printf '%s\n' "$dam_identity" | cut -d: -f1)
LOGNAME=$USER
SHELL=/bin/bash
export HOME USER LOGNAME SHELL
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_STATE_HOME="$HOME/.local/state"
export CODEX_HOME="$HOME/.codex"
export GH_CONFIG_DIR="$HOME/.config/gh"
export GLAB_CONFIG_DIR="$HOME/.config/glab-cli"
export NPM_CONFIG_PREFIX="$HOME/.local"
export PATH="$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export LANG=C.UTF-8 LC_ALL=C.UTF-8 EDITOR=nvim VISUAL=nvim
umask 0002
unset dam_identity
