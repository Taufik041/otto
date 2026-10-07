#!/usr/bin/env bash
# Stop the local Otto stack (keeps the cluster and database data).
pkill -f "uvicorn gateway.app" || true
pkill -f "brain.worker" || true
pkill -f "node.*vite" || true
pkill -f "port-forward svc/rabbitmq" || true
docker stop otto-pg otto-control-plane >/dev/null 2>&1 || true
echo "Otto stopped."