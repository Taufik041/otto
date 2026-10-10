#!/usr/bin/env bash
# Deploy one commit on the server (run as the deploy user, in the repo): check the commit out,
# pin its images in .env (pin_images.sh: ghcr.io/taufik041/otto-backend:<sha> for the stack,
# ghcr.io/taufik041/otto-sandbox:<sha> for the sandboxes), so a reboot or a later `up` keeps
# them, pull, bring the stack up, wait until the gateway says /health, and make sure RabbitMQ's
# runner user is as .env says (runner_user.sh).
#
#   bash deploy/aws/deploy.sh <commit sha>
#
# .github/workflows/deploy.yml runs it over SSH after each image build on main. To roll back, run
# it with an earlier commit (or the workflow's "Run workflow" with that sha): both images go back
# to that commit's.
set -euo pipefail

SHA="${1:?usage: deploy.sh <commit sha>}"
OTTO_DIR="${OTTO_DIR:-/opt/otto}"
IMAGE_REPO="${IMAGE_REPO:-ghcr.io/taufik041/otto-backend}"
IMAGE="$IMAGE_REPO:$SHA"
SANDBOX_IMAGE_REPO="${SANDBOX_IMAGE_REPO:-ghcr.io/taufik041/otto-sandbox}"
SANDBOX="$SANDBOX_IMAGE_REPO:$SHA"
COMPOSE=(docker compose -f docker-compose.prod.yml)
log() { echo "[deploy] $*"; }

cd "$OTTO_DIR"
log "checking out $SHA"
git fetch --quiet origin
git checkout --quiet --detach "$SHA"

cd deploy/compose
[ -f .env ] || { echo ".env is missing in $PWD: run deploy/aws/bootstrap.sh first" >&2; exit 1; }
# the sandbox node pulls this tag at the first session: it must exist before the gateway asks
# for it (commits from before CI pushed a sandbox image for each one have none)
docker manifest inspect "$SANDBOX" >/dev/null 2>&1 \
    || { echo "no $SANDBOX on the registry: not deploying $SHA" >&2; exit 1; }
IMAGE_REPO="$IMAGE_REPO" SANDBOX_IMAGE_REPO="$SANDBOX_IMAGE_REPO" bash ../aws/pin_images.sh .env "$SHA"
log "pinned $IMAGE and $SANDBOX"

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
        # the sandbox runners' RabbitMQ user, as .env's RABBITMQ_RUNNER_PASSWORD says
        bash runner_user.sh | sed 's/^/[deploy] /'
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
