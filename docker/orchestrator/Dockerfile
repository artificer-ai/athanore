# The orchestrator: athanore **v0** (the MVP), driving the v1 build.
#
# v0 and v1 are both called `athanore`. They never share an environment:
# v0 lives in this image's venv, v1 lives in athanore/dev's (D67). They
# meet only over the container boundary — v0 spawns `docker run -i ...
# athanore/dev pi-acp` and speaks ACP to it.
#
# Dependencies are synced at RUNTIME, not build time: the driver pins v0
# by path to the sibling MVP checkout, which only exists once compose has
# mounted it.

ARG UV_VERSION=0.12.10
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:3.13-slim-bookworm

ARG UID=1000
ARG GID=1000

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg git \
 && rm -rf /var/lib/apt/lists/*

# The docker CLI: v0 spawns the sandbox through the mounted socket.
RUN install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg \
      -o /etc/apt/keyrings/docker.asc \
 && chmod a+r /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce-cli \
 && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

RUN groupadd -g "$GID" app \
 && useradd -m -u "$UID" -g "$GID" -s /bin/bash app

ENV HOME=/home/app \
    UV_PROJECT_ENVIRONMENT=/home/app/venv \
    UV_CACHE_DIR=/home/app/.cache/uv \
    UV_LINK_MODE=copy \
    PATH=/home/app/venv/bin:$PATH

RUN git config --system --add safe.directory '*' \
 && mkdir -p /home/app/venv /home/app/.cache/uv /data \
 && chown -R app:app /home/app /data

USER app
CMD ["bash"]
