#!/usr/bin/env bash
# The backup drill: prove last night's dump restores. On the server, as the deploy user:
#
#   bash /opt/otto/scripts/restore_drill.sh
#
# It lists the newest dumps in the backup bucket (dates and sizes), downloads the newest, restores
# it into a throwaway Postgres 16 container with no network and no ports, prints sanity counts
# (users, sessions, session_events, the newest event's time), and removes everything it made. The
# exit status is non-zero if any step fails, the restored database has no users, or the newest dump
# is older than MAX_AGE_HOURS.
#
# The bucket and its credentials are the backup service's (deploy/compose/.env: BACKUP_S3_BUCKET,
# BACKUP_S3_PREFIX, AWS_*): the aws CLI runs in the backup image, so the server needs none.
#
# Settings (environment):
#   OTTO_DIR        the checkout [/opt/otto, or the one this script is in]
#   MAX_AGE_HOURS   how old the newest dump may be [36]
#   SHOW            how many of the newest dumps to list [5]
#   DRILL_IMAGE     the throwaway database's image [postgres:16-alpine, as production's]
set -euo pipefail

OTTO_DIR="${OTTO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
COMPOSE_DIR="$OTTO_DIR/deploy/compose"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-36}"
SHOW="${SHOW:-5}"
DRILL_IMAGE="${DRILL_IMAGE:-postgres:16-alpine}"
NAME="otto-restore-drill-$$"

step() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
fail() { echo "restore drill FAILED: $*" >&2; exit 1; }

[ -f "$COMPOSE_DIR/.env" ] || fail "no $COMPOSE_DIR/.env (run this on the server)"
docker info >/dev/null 2>&1 || fail "can't use docker (run this as the deploy user, in the docker group)"
cd "$COMPOSE_DIR"

WORK=$(mktemp -d)
chmod 700 "$WORK"
cleanup() {
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

# in_backup SCRIPT [docker compose run options]: runs a POSIX sh script in the backup image, with
# the backup service's settings (from .env). The scripts are single-quoted on purpose: they expand
# the container's variables, not this shell's.
in_backup() {
    local script=$1
    shift
    docker compose -f docker-compose.prod.yml --progress quiet run --rm --no-deps -T "$@" backup sh -euc "$script"
}
# the bucket's dump prefix, as scripts/backup_db.sh makes it
# shellcheck disable=SC2016
PREFIX_SH='PREFIX="${BACKUP_S3_PREFIX:-otto/db}"; PREFIX="${PREFIX%/}"; : "${BACKUP_S3_BUCKET:?set BACKUP_S3_BUCKET in .env}"'

step "the newest dumps"
# key, size, upload time; the dump's own time is in its name (otto-YYYYMMDDTHHMMSSZ.dump)
# shellcheck disable=SC2016
in_backup "$PREFIX_SH"'
aws s3api list-objects-v2 --bucket "$BACKUP_S3_BUCKET" --prefix "$PREFIX/otto-" \
    --query "Contents[].[Key,Size,LastModified]" --output text' > "$WORK/listing" \
    || fail "couldn't list the bucket (its settings are in $COMPOSE_DIR/.env)"
grep -E '/otto-[0-9]{8}T[0-9]{6}Z\.dump\s' "$WORK/listing" | sort > "$WORK/dumps" || true
[ -s "$WORK/dumps" ] || fail "no dumps in the bucket"
note "$(wc -l < "$WORK/dumps") in the bucket; the newest:"
tail -n "$SHOW" "$WORK/dumps" | while read -r key size modified; do
    printf '   %-48s %8s  uploaded %s\n' "${key##*/}" "$(numfmt --to=iec --suffix=B "$size")" "$modified"
done
read -r KEY SIZE _ < <(tail -n 1 "$WORK/dumps")

STAMP=${KEY##*/otto-}
STAMP=${STAMP%.dump}
# YYYYMMDDTHHMMSSZ -> YYYY-MM-DD HH:MM:SS UTC
TAKEN=$(sed -E 's/^(....)(..)(..)T(..)(..)(..)Z$/\1-\2-\3 \4:\5:\6 UTC/' <<<"$STAMP")
AGE_HOURS=$(( ($(date -u +%s) - $(date -u -d "$TAKEN" +%s)) / 3600 ))
TOO_OLD=
if (( AGE_HOURS > MAX_AGE_HOURS )); then
    TOO_OLD="the newest dump is ${AGE_HOURS} hours old (more than $MAX_AGE_HOURS): is the nightly backup running?"
    note "WARNING: $TOO_OLD"
else
    note "the newest was taken $TAKEN, $AGE_HOURS hour(s) ago"
fi

step "download ${KEY##*/}"
# shellcheck disable=SC2016
in_backup 'aws s3 cp --only-show-errors "s3://$BACKUP_S3_BUCKET/$DRILL_KEY" -' -e "DRILL_KEY=$KEY" > "$WORK/otto.dump"
[ "$(stat -c %s "$WORK/otto.dump")" -eq "$SIZE" ] || fail "downloaded $(stat -c %s "$WORK/otto.dump") bytes, expected $SIZE"
note "$(numfmt --to=iec --suffix=B "$SIZE"), complete"

step "restore into a throwaway database ($DRILL_IMAGE, no network, no ports)"
docker run -d --name "$NAME" --network none --memory 384m \
    -e POSTGRES_USER=otto -e POSTGRES_DB=otto -e POSTGRES_PASSWORD="$(od -An -tx1 -N16 /dev/urandom | tr -d ' \n')" \
    "$DRILL_IMAGE" >/dev/null
# over TCP on its own loopback: the entrypoint's first, temporary server listens only on the socket
for _ in $(seq 60); do
    docker exec "$NAME" pg_isready -q -h 127.0.0.1 -U otto -d otto 2>/dev/null && break
    sleep 1
done
docker exec "$NAME" pg_isready -q -h 127.0.0.1 -U otto -d otto || fail "the throwaway database didn't start"
docker cp "$WORK/otto.dump" "$NAME:/tmp/otto.dump" >/dev/null
docker exec "$NAME" pg_restore --exit-on-error --no-owner --no-privileges -U otto -d otto /tmp/otto.dump \
    || fail "pg_restore failed"
note "restored"

step "sanity counts"
q() { docker exec "$NAME" psql -X -A -t -v ON_ERROR_STOP=1 -U otto -d otto -c "$1"; }
USERS=$(q 'SELECT count(*) FROM users')
note "users:          $USERS"
note "sessions:       $(q 'SELECT count(*) FROM sessions')"
note "session_events: $(q 'SELECT count(*) FROM session_events')"
note "newest event:   $(q "SELECT coalesce(max(ts)::text, 'none') FROM session_events")"
note "migration:      $(q 'SELECT version_num FROM alembic_version')"

step "clean up"
cleanup
note "removed the throwaway database and the download"

[ "$USERS" -gt 0 ] || fail "the restored database has no users"
[ -z "$TOO_OLD" ] || fail "$TOO_OLD"
printf '\nrestore drill passed: %s restores, with %s user(s)\n' "${KEY##*/}" "$USERS"
