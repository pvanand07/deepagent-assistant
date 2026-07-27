FROM python:3.12-slim

ARG BWRAP_SETUID=0

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    bash \
    bubblewrap \
    ca-certificates \
    curl \
    git \
    ripgrep \
  && rm -rf /var/lib/apt/lists/*

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
COPY skills/grillme/ ./skills/grillme/
COPY frontend ./frontend
COPY AGENT.md /app/seed/AGENT.md
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
  && chmod +x /usr/local/bin/docker-entrypoint.sh

VOLUME /workspace

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "deep_agent.cli"]
