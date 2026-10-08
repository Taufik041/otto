#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker start otto-control-plane otto-pg >/dev/null 2>&1 || true
./scripts/dev_up.sh
source .venv/bin/activate
mkdir -p .logs
pkill -f "uvicorn gateway.app" || true
pkill -f "brain.worker" || true
pkill -f "node.*vite" || true
OTTO_LANDING_ORIGINS=http://localhost:5174 nohup uvicorn gateway.app:app --port 8000 > .logs/gateway.log 2>&1 &
nohup python -m brain.worker > .logs/worker.log 2>&1 &
(cd web && nohup npm run dev > ../.logs/web.log 2>&1 &)
(cd web && VITE_API_URL=http://localhost:8000 VITE_APP_URL=http://localhost:5173 nohup npm run dev:landing > ../.logs/landing.log 2>&1 &)
for i in $(seq 1 30); do curl -sf localhost:8000/health >/dev/null && break; sleep 1; done
echo "health   $(curl -s localhost:8000/health || echo 'gateway not up, see .logs/gateway.log')"
echo "app      http://localhost:5173"
echo "landing  http://localhost:5174"
echo "gateway  http://localhost:8000/docs"
echo "logs     tail -f .logs/gateway.log .logs/worker.log .logs/web.log .logs/landing.log"
