# B385: Campy memory service container (AWS ECS/Fargate; see
# docs/cloud-integration-guide.md). Build from the repo root:
#
#   docker build -f deploy/Dockerfile -t campy:latest .
#
# Registries/hosts the BUILD needs: the base image registry, pypi.org,
# github.com (spaCy model), huggingface.co (embedding model). The RUNTIME
# needs none of them: both models are baked in and HF_HUB_OFFLINE=1.
#
# PYTHON_IMAGE lets you pull the base from a mirror, e.g.
#   --build-arg PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.12-slim

ARG PYTHON_IMAGE=python:3.12-slim

# ---- build: dependencies and models ---------------------------------------
FROM ${PYTHON_IMAGE} AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FASTEMBED_CACHE_PATH=/opt/campy-models/fastembed

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt \
 && python -m spacy download en_core_web_md

# Bake the embedding model (the one [embeddings].model names) so the runtime
# never downloads it.
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
# The Hugging Face cache writes some files owner-only (0600) as root; make the
# tree world-readable so the runtime user (UID 1000) can read all of it. It
# stays root-owned: the runtime never needs to write to it.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='${EMBEDDING_MODEL}')" \
 && chmod -R a+rX /opt/campy-models

# ---- runtime ----------------------------------------------------------------
FROM ${PYTHON_IMAGE}

RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin campy \
 && mkdir -p /data/campy /tmp/campy \
 && chown campy:campy /data/campy /tmp/campy

COPY --from=build /opt/venv /opt/venv
COPY --from=build /opt/campy-models /opt/campy-models
COPY --chown=campy:campy campy /app/campy
COPY --chown=campy:campy web /app/web
COPY --chown=campy:campy adapters /app/adapters
COPY --chown=campy:campy deploy/campy.container.toml /app/deploy/campy.container.toml
COPY --chown=campy:campy deploy/entrypoint.sh /app/deploy/entrypoint.sh

# CAMPY_HOME is the persistent mount (EFS on ECS); all runtime state lives
# there (B456). The IPC socket stays on local disk: AF_UNIX sockets on NFS
# are unreliable. Auth defaults to IAM: the bind guard refuses 0.0.0.0
# without it. The dashboard is off (a local-operator UI; see B457).
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    FASTEMBED_CACHE_PATH=/opt/campy-models/fastembed \
    CAMPY_HOME=/data/campy \
    CAMPY_SOCKET_PATH=/tmp/campy/brain.sock \
    CAMPY_SERVER_BIND_HOST=0.0.0.0 \
    CAMPY_SERVER_AUTH=iam \
    CAMPY_SERVER_DASHBOARD_ENABLED=false \
    CAMPY_WEB_PORT=7799

USER 1000:1000
# Run from CAMPY_HOME: load_config() checks the working directory first, so
# this keeps a stray campy.toml elsewhere from shadowing the deployed config.
WORKDIR /data/campy
EXPOSE 7799

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7799/health', timeout=3).status == 200 else 1)"

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
