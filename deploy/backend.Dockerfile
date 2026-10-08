# otto-backend: the gateway and the brain worker, one image (the sandbox runner has its own,
# infra/sandbox.Dockerfile). Build from the repo root:
#   docker build -f deploy/backend.Dockerfile -t otto-backend .
#   docker run otto-backend gateway | worker | access-requests [args]

# --- build: the dependencies and the package, into a virtualenv -------------------------
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src
# the dependencies first, so a code change doesn't reinstall them
COPY pyproject.toml ./
RUN mkdir -p shared runner brain orchestrator gateway \
    && pip install . && pip uninstall -y otto
COPY shared/ shared/
COPY runner/ runner/
COPY brain/ brain/
COPY orchestrator/ orchestrator/
COPY gateway/ gateway/
RUN pip install --no-deps . && find /opt/venv -name '__pycache__' -prune -exec rm -rf {} +

# --- runtime ------------------------------------------------------------------------------
FROM python:3.12-slim
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system --gid 10001 otto \
    && useradd --system --uid 10001 --gid otto --home-dir /app --shell /usr/sbin/nologin otto
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
# python -m scripts.access_requests (approving access requests) runs from here
COPY scripts/access_requests.py scripts/access_requests.py
COPY deploy/otto-entrypoint.sh /usr/local/bin/otto
USER otto
EXPOSE 8000
# the gateway's own check; the worker's service overrides it (deploy/compose)
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status != 200)"]
ENTRYPOINT ["otto"]
CMD ["gateway"]
