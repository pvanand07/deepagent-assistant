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

COPY agent.py streaming.py bubblewrap_sandbox.py openrouter_model.py cli.py ./

ENV DEEPAGENT_WORKDIR=/workspace
ENV CODEX_GUI_WORKSPACE=/workspace
ENV DEEPAGENT_NETWORK_ACCESS=false

VOLUME /workspace

CMD ["python", "cli.py"]
