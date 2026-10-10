#!/usr/bin/env bash
# Pin one commit's images in the stack's .env (deploy.sh runs it): the backend
# (ghcr.io/taufik041/otto-backend:<sha>, OTTO_IMAGE) and the sandbox the gateway starts Jobs with
# (ghcr.io/taufik041/otto-sandbox:<sha>, SANDBOX_IMAGE), and OTTO_VERSION. CI pushes both tags for
# every commit on main. An exact tag per commit is what makes the sandbox node pull a new runner:
# Kubernetes never pulls a tag it already has again. Pinning an earlier commit (a rollback) puts
# back its images, both of them.
#
#   bash deploy/aws/pin_images.sh <.env> <commit sha>
set -euo pipefail

ENV_FILE="${1:?usage: pin_images.sh <.env> <commit sha>}"
SHA="${2:?usage: pin_images.sh <.env> <commit sha>}"
BACKEND_REPO="${IMAGE_REPO:-ghcr.io/taufik041/otto-backend}"
SANDBOX_REPO="${SANDBOX_IMAGE_REPO:-ghcr.io/taufik041/otto-sandbox}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "not a full commit sha: $SHA" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "no $ENV_FILE: run deploy/aws/bootstrap.sh first" >&2; exit 1; }

pin() {  # pin NAME VALUE: replace NAME=..., or add it at the end
    if grep -q "^$1=" "$ENV_FILE"; then
        sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"
    else
        printf '# pinned by deploy/aws/deploy.sh\n%s=%s\n' "$1" "$2" >> "$ENV_FILE"
    fi
}

[ -z "$(tail -c1 "$ENV_FILE")" ] || echo >> "$ENV_FILE"  # a last line without its newline
pin OTTO_IMAGE "$BACKEND_REPO:$SHA"
pin SANDBOX_IMAGE "$SANDBOX_REPO:$SHA"
pin OTTO_VERSION "${SHA:0:12}"
