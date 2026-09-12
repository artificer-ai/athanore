# One image for the whole v1 dev stack: the `dev` shell, the `app`
# server, the `web` Vite server, and the ACP agents athanore dispatches
# to. Everything a task in `docs/v1/17-serial-task-plan.md` needs to run
# lives here, so a green gate means the same thing on every machine.
#
# It is deliberately one image and not three. The agents run the gate
# themselves (implement → gate → review), so the sandbox they run in has
# to be the same toolchain the human uses; splitting them is how the two
# drift apart.
#
#   docker compose build
#   ./scripts/test.sh                 # gate, in the container
#   ./scripts/agent.sh pi             # ACP on stdin/stdout
#
# Nothing in `athanore/` may depend on this image (02 §Library choices:
# the core knows nothing about pi, Claude, or Docker). It is dev
# machinery only.

ARG UV_VERSION=0.12.10
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM node:22-bookworm-slim

# Agent adapters, pinned. Floating `npx -y pkg` resolves the latest
# version at every spawn (12 §Supply chain, S7).
ARG PI_VERSION=0.85.1
ARG PI_ACP_VERSION=0.0.33
ARG CLAUDE_CODE_VERSION=2.1.261
ARG CLAUDE_ACP_VERSION=0.75.1
ARG PNPM_VERSION=10
ARG PYTHON_VERSION=3.13
ARG PLAYWRIGHT_VERSION=1.63.0
# 1 installs a chromium for the Playwright suite (T068 flips the default).
ARG WITH_BROWSERS=0
# Match the host uid/gid so files written into the bind-mounted worktree
# are owned by the host user, not root.
ARG UID=1000
ARG GID=1000

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg \
      git openssh-client \
      build-essential \
      jq sqlite3 ripgrep less procps \
 && rm -rf /var/lib/apt/lists/*

# docker CLI so a workflow inside the container can spawn a sibling
# sandbox (`examples/docker_acp`) through the mounted socket.
RUN install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg \
      -o /etc/apt/keyrings/docker.asc \
 && chmod a+r /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
 && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

# The two ACP agents athanore dispatches to, plus the CLIs behind them.
RUN npm install -g --no-fund --no-audit \
      "pnpm@${PNPM_VERSION}" \
      "@earendil-works/pi-coding-agent@${PI_VERSION}" \
      "pi-acp@${PI_ACP_VERSION}" \
      "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
      "@agentclientprotocol/claude-agent-acp@${CLAUDE_ACP_VERSION}" \
 && npm cache clean --force

# The node image already owns uid/gid 1000 as `node`; rename it when the
# requested ids match, otherwise create a fresh user.
RUN if [ "$UID" = "1000" ] && [ "$GID" = "1000" ]; then \
      usermod -l agent -d /home/agent -m node && groupmod -n agent node; \
    else \
      groupadd -g "$GID" agent && useradd -m -u "$UID" -g "$GID" -s /bin/bash agent; \
    fi

# The worktree is bind-mounted from the host and its .venv points at a
# host Python that does not exist in here. Keep uv's environment and
# cache OUT of the worktree so `uv sync` never rewrites the host venv;
# both are named volumes in compose.yaml so they survive across runs.
# LINK_MODE=copy: cache and venv sit on different volumes, so hardlinks
# are impossible.
ENV HOME=/home/agent \
    PI_CODING_AGENT_DIR=/home/agent/.pi/agent \
    UV_PROJECT_ENVIRONMENT=/home/agent/venv \
    UV_CACHE_DIR=/home/agent/.cache/uv \
    UV_LINK_MODE=copy \
    UV_PYTHON_PREFERENCE=only-managed \
    PNPM_HOME=/home/agent/.local/share/pnpm \
    PLAYWRIGHT_BROWSERS_PATH=/home/agent/ms-playwright \
    ATHANORE_IN_CONTAINER=1 \
    PATH=/home/agent/venv/bin:/home/agent/.local/share/pnpm:/home/agent/.local/bin:$PATH

# Bind-mounted checkouts are owned by the host user; git refuses them by
# default when the ids do not line up on some hosts.
RUN git config --system --add safe.directory '*'

COPY --chown=agent:agent pi/models.json pi/settings.json /home/agent/.pi/agent/

RUN if [ "$WITH_BROWSERS" = "1" ]; then \
      npx -y "playwright@${PLAYWRIGHT_VERSION}" install-deps chromium; \
    fi

RUN mkdir -p /home/agent/venv \
             /home/agent/venvs \
             /home/agent/.cache/uv \
             /home/agent/.local/share/pnpm/store \
             /home/agent/.claude \
             /home/agent/ms-playwright \
 && chown -R agent:agent /home/agent

USER agent

# Managed interpreter, plus python/python3 shims on PATH for ad-hoc use.
RUN uv python install --default "${PYTHON_VERSION}"

RUN if [ "$WITH_BROWSERS" = "1" ]; then \
      npx -y "playwright@${PLAYWRIGHT_VERSION}" install chromium; \
    fi

# Overridden per service in compose.yaml: `bash -lc` for dev/app/web,
# `pi-acp` / `claude-agent-acp` for the agents.
CMD ["bash"]
