# syntax=docker/dockerfile:1
ARG GLAB_VERSION=v1.123.0
ARG UV_VERSION=0.13.1
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv
FROM gitlab/glab:${GLAB_VERSION} AS glab
FROM node:26.12.0-trixie-slim

ARG GH_VERSION=2.102.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash bash-completion build-essential ca-certificates curl fd-find git jq less neovim \
       openssh-client procps python3 python3-venv \
       python-is-python3 ripgrep rsync tmux unzip xz-utils passwd util-linux libpam-modules \
    && rm -rf /var/lib/apt/lists/* \
    && architecture="$(dpkg --print-architecture)" \
    && curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${architecture}.tar.gz" \
       -o /tmp/gh.tar.gz \
    && tar -xzf /tmp/gh.tar.gz -C /tmp \
    && install -m 0755 "/tmp/gh_${GH_VERSION}_linux_${architecture}/bin/gh" /usr/local/bin/gh \
    && rm -rf /tmp/gh.tar.gz "/tmp/gh_${GH_VERSION}_linux_${architecture}" \
    && ln -s /usr/bin/fdfind /usr/local/bin/fd
COPY --from=glab /usr/bin/glab /usr/local/bin/glab
COPY --from=uv /uv /uvx /usr/local/bin/

RUN mkdir -p /etc/codex /etc/dam/profile /etc/dam/workspace /etc/dam/host-settings \
    && passwd -l root \
    && passwd -l node \
    && groupadd --system --force users \
    && git config --system core.sharedRepository group
COPY docker/ /usr/local/lib/dam/
RUN install -m 0755 /usr/local/lib/dam/user-env.sh /usr/local/bin/dam-user-env \
    && install -m 0644 /usr/local/lib/dam/profile.sh /etc/profile.d/dam.sh \
    && install -m 0644 /usr/local/lib/dam/su.pam /etc/pam.d/su \
    && install -m 0644 /usr/local/lib/dam/su-l.pam /etc/pam.d/su-l \
    && install -m 0644 /usr/local/lib/dam/su-env.conf /etc/security/dam-env.conf
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8 EDITOR=nvim VISUAL=nvim
USER root
WORKDIR /home/node
HEALTHCHECK --interval=1s --timeout=2s --start-period=5s --retries=30 CMD test -f /tmp/dam-ready
ENTRYPOINT ["python3", "/usr/local/lib/dam/entrypoint.py"]
CMD ["sleep", "infinity"]
