#!/usr/bin/env bash
cd "$(dirname "$0")/.." || exit
pkill -f "uvicorn gateway.app" || true
pkill -f "brain.worker" || true
pkill -f "node.*vite" || true
pkill -f "rabbitmq_forward.sh" || true  # first, or it starts the port-forward again
pkill -f "kubectl.*port-forward" || true
docker stop otto-pg otto-control-plane >/dev/null 2>&1 || true
echo "stopped"
