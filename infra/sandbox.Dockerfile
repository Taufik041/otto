FROM python:3.12-slim AS base
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ripgrep ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace

FROM base AS full
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm \
    && rm -rf /var/lib/apt/lists/*

FROM full AS runner
RUN pip install --no-cache-dir aio-pika pytest
RUN useradd -m -u 1000 otto

COPY scripts/step1_3_runner.py /app/runner.py
COPY infra/entrypoint.sh /app/entrypoint.sh

# root owns /app; otto can read+execute but NOT write
RUN chown -R root:root /app && chmod -R 555 /app

RUN mkdir -p /workspace && chown otto:otto /workspace

USER otto
WORKDIR /app
ENTRYPOINT ["/app/entrypoint.sh"]