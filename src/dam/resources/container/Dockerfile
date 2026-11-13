FROM node:26.12.0-trixie-slim

ARG DAM_UID=1000
RUN apt-get update \
    && apt-get install -y --no-install-recommends vim neovim \
    && rm -rf /var/lib/apt/lists/* \
    && groupmod -n dam node \
    && usermod -l dam -d /home/dam -m node \
    && usermod -u "${DAM_UID}" dam \
    && chown -R dam:dam /home/dam

USER dam
WORKDIR /home/dam
CMD ["sleep", "infinity"]
