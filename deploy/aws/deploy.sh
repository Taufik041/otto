#!/usr/bin/env bash
# Deploy one commit on the server (run as the deploy user, in the repo): check the commit out,
# pin its image (ghcr.io/taufik041/otto-backend:<sha>) in .env, so a reboot or a later `up` keeps
# it, pull, bring the stack up, and wait until the gateway says /health.
#
#   bash deploy/aws/deploy.sh <commit sha>
#
# .github/workflows/deploy.yml runs it over SSH after each image build on main. To roll back, run
# it with an earlier commit (or the workflow's "Run workflow" with that sha).
set -euo pipefail

SHA="${1:?usage: deploy.sh <commit sha>}"
OTTO_DIR="${OTTO_DIR:-/opt/otto}"
IMAGE_REPO="${IMAGE_REPO:-ghcr.io/taufik041/otto-backend}"
IMAGE="$IMAGE_REPO:$SHA"
COMPOSE=(docker compose -f docker-compose.prod.yml)
log() { echo "[deploy] $*"; }

cd "$OTTO_DIR"
log "checking out $SHA"
git fetch --quiet origin
git checkout --quiet --detach "$SHA"

cd deploy/compose
[ -f .env ] || { echo ".env is missing in $PWD: run deploy/aws/bootstrap.sh first" >&2; exit 1; }
if grep -q '^OTTO_IMAGE=' .env; then
    sed -i "s|^OTTO_IMAGE=.*|OTTO_IMAGE=$IMAGE|" .env
else
    printf '\n# pinned by deploy/aws/deploy.sh\nOTTO_IMAGE=%s\n' "$IMAGE" >> .env
fi
sed -i "s|^OTTO_VERSION=.*|OTTO_VERSION=${SHA:0:12}|" .env
grep -q '^OTTO_VERSION=' .env || echo "OTTO_VERSION=${SHA:0:12}" >> .env

log "pulling $IMAGE"
"${COMPOSE[@]}" pull --quiet gateway worker
log "building the backup image (cached unless its files changed)"
"${COMPOSE[@]}" build --quiet backup
log "starting"
"${COMPOSE[@]}" up -d --remove-orphans

PORT=$(grep -oP '^GATEWAY_PORT=\K.+' .env || echo 8000)
for i in $(seq 40); do
    if body=$(curl -fsS "http://127.0.0.1:$PORT/health" 2>/dev/null); then
        log "healthy after ${i} check(s): $body"
        "${COMPOSE[@]}" ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}'
        docker image prune -f >/dev/null # old images: the disk is small
        exit 0
    fi
    sleep 5
done
log "the gateway didn't answer /health in 200s"
"${COMPOSE[@]}" ps
"${COMPOSE[@]}" logs --tail 50 gateway
exit 1
