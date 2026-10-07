#!/usr/bin/env bash
# Bring up the whole local Otto stack: cluster, rabbitmq, postgres, gateway, worker, web.
set -euo pipefail
cd "$(dirname "$0")/.."
docker start otto-control-plane otto-pg >/dev/null 2>&1 || true
./scripts/dev_up.sh
source .venv/bin/activate
mkdir -p .logs
pkill -f "uvicorn gateway.app" || true
pkill -f "brain.worker" || true
pkill -f "node.*vite" || true
nohup uvicorn gateway.app:app --port 8000 > .logs/gateway.log 2>&1 &
nohup python -m brain.worker > .logs/worker.log 2>&1 &
(cd web && nohup npm run dev > ../.logs/web.log 2>&1 &)
sleep 4
echo "web      http://localhost:5173"
echo "gateway  http://localhost:8000/docs"
echo "logs     tail -f .logs/gateway.log .logs/worker.log .logs/web.log"