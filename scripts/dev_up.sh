#!/usr/bin/env bash
# Bring Otto's dev stack up on kind: cluster -> rabbitmq -> image -> runner job -> port-forward.
set -euo pipefail

CLUSTER=otto
IMAGE=taufik041/otto-sandbox:dev
RABBIT_YML=infra/k8s/rabbitmq.yml

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

echo "== runner job"
# replaces any old job, injects a fresh GitHub token, and waits until the runner is listening
python -m orchestrator.cli create "${SESSION_ID:-s1}" --repo "${REPO_URL:-https://github.com/Taufik041/otto_test}"

echo "== port-forward"
pkill -f "port-forward svc/rabbitmq" || true
kubectl port-forward svc/rabbitmq 5672:5672 >/dev/null 2>&1 &
sleep 2
echo "ready: python -m brain.main \"<task>\""
