#!/usr/bin/env bash
# Bring Otto's dev stack up: postgres -> kind cluster -> rabbitmq -> sandbox image -> port-forward.
# Sandboxes (runner Jobs) are created per session by the gateway.
set -euo pipefail

CLUSTER=otto
IMAGE=taufik041/otto-sandbox:dev
RABBIT_YML=infra/k8s/rabbitmq.yml

port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

echo "== postgres"
if docker start otto-pg >/dev/null 2>&1; then
    echo "started otto-pg"
elif port_open 5432; then
    echo "no otto-pg container, but something already serves :5432; using it"
else
    docker run -d --name otto-pg \
        -e POSTGRES_USER=otto -e POSTGRES_PASSWORD=otto -e POSTGRES_DB=otto \
        -p 5432:5432 postgres:16-alpine >/dev/null
    echo "created otto-pg"
fi
for _ in $(seq 30); do port_open 5432 && break; sleep 1; done
port_open 5432 || { echo "postgres is not reachable on :5432" >&2; exit 1; }

echo "== cluster"
kind get clusters | grep -qx "$CLUSTER" || kind create cluster --name "$CLUSTER"
kubectl config use-context "kind-$CLUSTER" >/dev/null

echo "== rabbitmq"
kubectl apply -f "$RABBIT_YML"
kubectl rollout status deploy/rabbitmq --timeout=120s

echo "== image"
docker build -t "$IMAGE" --target runner -f infra/sandbox.Dockerfile .
# kind load docker-image "$IMAGE" --name "$CLUSTER"
docker save "$IMAGE" | docker exec -i "${CLUSTER}-control-plane" ctr -n k8s.io images import -

echo "== port-forward"
pkill -f "port-forward svc/rabbitmq" || true
kubectl port-forward svc/rabbitmq 5672:5672 >/dev/null 2>&1 &
sleep 2

cat <<'EOF'
ready. In two terminals:
  uvicorn gateway.app:app --port 8000
  python -m brain.worker
(SANDBOX_IDLE_MINUTES=2 on the gateway makes new sandboxes exit after 2 idle minutes)
Then open http://localhost:8000/docs: sign up (POST /auth/signup), connect GitHub
(http://localhost:8000/github/install), and start a chat (POST /sessions {"message", "repo"?}).
See docs/dev.md ("Trying it without a frontend"). The API needs AUTH_SECRET, and GitHub needs
GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET and GITHUB_APP_SLUG.
A database from before migrations must be reset first (docs/dev.md).
EOF
