FROM python:3.12-slim

ARG BWRAP_SETUID=0

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

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY tests/ ./tests/
COPY pytest.ini ./
COPY agents/ ./agents/
COPY frontend ./frontend
COPY AGENT.md /app/seed/AGENT.md
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
  && chmod +x /usr/local/bin/docker-entrypoint.sh

ENV PYTHONPATH=/app/src
ENV DEEPAGENT_WORKDIR=/workspace
ENV CODEX_GUI_WORKSPACE=/workspace
ENV DEEPAGENT_NETWORK_ACCESS=false
ENV DEEPAGENT_DATA_DIR=/app/data

VOLUME /workspace
VOLUME /app/data

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:8010/health || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
# IMPORTANT: single uvicorn process only (no --workers). Run state, SSE
# subscriber queues, and the SQLite event log are all in-process; multiple
# workers would split sessions/runs across processes.
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8010"]