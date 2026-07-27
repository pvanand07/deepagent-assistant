FROM python:3.12-slim

ARG BWRAP_SETUID=0
ARG TARGETARCH
ARG NODE_VERSION=22.14.0

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    bash \
    bubblewrap \
    build-essential \
    ca-certificates \
    chromium \
    curl \
    fonts-liberation \
    git \
    libicu-dev \
    procps \
    ripgrep \
    xz-utils \
  && rm -rf /var/lib/apt/lists/* \
  && chromium --version

# Node.js for chrome-devtools-axi (and npx fallback).
RUN set -eux; \
    arch="${TARGETARCH:-}"; \
    if [ -z "$arch" ]; then arch="$(dpkg --print-architecture)"; fi; \
    case "$arch" in \
      amd64) NODE_ARCH=x64 ;; \
      arm64) NODE_ARCH=arm64 ;; \
      *) echo "unsupported arch=${arch}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL --max-time 300 \
      "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
      -o /tmp/node.tar.xz; \
    tar -xJf /tmp/node.tar.xz --strip-components=1 -C /usr/local; \
    rm /tmp/node.tar.xz; \
    node --version; \
    npm --version; \
    npm install --global --no-fund --no-audit chrome-devtools-axi@0.1.26; \
    npm cache clean --force; \
    chrome-devtools-axi --version

# officecli is a self-contained .NET binary (needs libicu). Install to
# /usr/local/bin — available inside bwrap via the /usr read-only bind.
RUN set -eux; \
    arch="${TARGETARCH:-}"; \
    if [ -z "$arch" ]; then arch="$(dpkg --print-architecture)"; fi; \
    case "$arch" in \
      amd64) ASSET=officecli-linux-x64 ;; \
      arm64) ASSET=officecli-linux-arm64 ;; \
      *) echo "unsupported arch=${arch}" >&2; exit 1 ;; \
    esac; \
    VERSION="$(curl -fsSL --max-time 30 -o /dev/null -w '%{url_effective}' \
      https://github.com/iOfficeAI/OfficeCLI/releases/latest \
      | sed 's|.*/tag/||')"; \
    test -n "${VERSION}" && test "${VERSION}" != "latest"; \
    curl -fsSL --max-time 300 \
      "https://github.com/iOfficeAI/OfficeCLI/releases/download/${VERSION}/${ASSET}" \
      -o /usr/local/bin/officecli; \
    chmod +x /usr/local/bin/officecli; \
    officecli --version

# Only when the host blocks unprivileged user namespaces (see reference_sandboxing.md).
RUN if [ "$BWRAP_SETUID" = "1" ]; then chmod u+s /usr/bin/bwrap; fi

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    DEEPAGENT_WORKDIR=/workspace \
    CODEX_GUI_WORKSPACE=/workspace \
    DEEPAGENT_NETWORK_ACCESS=false

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
COPY agents/ ./agents/
COPY skills/ ./skills/
COPY frontend ./frontend
COPY AGENT.md /app/seed/AGENT.md
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
  && chmod +x /usr/local/bin/docker-entrypoint.sh

VOLUME /workspace

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "deep_agent.cli"]
