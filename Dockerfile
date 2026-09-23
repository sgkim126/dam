# syntax=docker/dockerfile:1
ARG GLAB_VERSION=v1.118.0
FROM gitlab/glab:${GLAB_VERSION} AS glab

FROM node:24-trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash build-essential ca-certificates curl fd-find git jq less neovim \
       openssh-client pipx python3 python3-pip python3-venv \
       python-is-python3 ripgrep rsync tmux unzip xz-utils passwd util-linux libpam-modules \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
       -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod a+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
       > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

COPY --from=glab /usr/bin/glab /usr/local/bin/glab
RUN npm install -g @openai/codex \
    && npm cache clean --force \
    && ln -s /usr/bin/fdfind /usr/local/bin/fd \
    && mkdir -p /etc/codex /home/node/.config /home/node/.local/bin /home/node/.codex /workspace \
    && chown -R node:node /home/node /workspace \
    && chmod 0700 /home/node \
    && passwd -l root \
    && passwd -l node \
    && groupadd --system --force users \
    && usermod --append --groups users node \
    && git config --system core.sharedRepository group \
    && git config --system --add safe.directory /workspace \
    && git config --system --add safe.directory '/workspace/*'

COPY docker/import-settings.py docker/prepare-settings.py docker/workspace.py /usr/local/lib/dam/
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/dam-entrypoint
COPY --chmod=755 docker/user-env.sh /usr/local/bin/dam-user-env
COPY --chmod=644 docker/profile.sh /etc/profile.d/dam.sh
COPY --chmod=644 docker/su.pam /etc/pam.d/su
COPY --chmod=644 docker/su-l.pam /etc/pam.d/su-l
COPY --chmod=644 docker/su-env.conf /etc/security/dam-env.conf

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    EDITOR=nvim \
    VISUAL=nvim
USER root
WORKDIR /workspace
ENTRYPOINT ["dam-entrypoint"]
CMD ["sleep", "infinity"]
