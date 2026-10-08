#!/bin/sh
# Back up Otto's Postgres to S3: a compressed pg_dump (custom format), uploaded as
#   s3://$BACKUP_S3_BUCKET/$BACKUP_S3_PREFIX/otto-YYYYMMDDTHHMMSSZ.dump
# then deletes this prefix's dumps older than $BACKUP_KEEP_DAYS (14). The backup service in
# deploy/compose runs it nightly; it also runs by hand:
#   docker compose -f docker-compose.prod.yml exec backup backup_db.sh
#
# Needs: pg_dump (matching the server's major version), the aws CLI, and
#   PGHOST PGUSER PGDATABASE PGPASSWORD (or PG* defaults)   the database
#   BACKUP_S3_BUCKET, BACKUP_S3_PREFIX (default: otto/db)    where dumps go
#   AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
#   AWS_ENDPOINT_URL (optional: an S3-compatible store instead of AWS)
# Restore: pg_restore --clean --if-exists -d otto otto-....dump
set -eu

: "${BACKUP_S3_BUCKET:?set BACKUP_S3_BUCKET}"
PREFIX="${BACKUP_S3_PREFIX:-otto/db}"
PREFIX="${PREFIX%/}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
KEY="$PREFIX/otto-$STAMP.dump"
DEST="s3://$BACKUP_S3_BUCKET/$KEY"
log() { echo "[backup] $(date -u +%FT%TZ) $*"; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
FILE="$TMP/otto-$STAMP.dump"

log "dumping ${PGDATABASE:-otto} from ${PGHOST:-localhost}"
pg_dump --format=custom --compress=9 --no-owner --file="$FILE"
log "uploading $(du -h "$FILE" | cut -f1) to $DEST"
aws s3 cp --only-show-errors "$FILE" "$DEST"

# keep KEEP_DAYS days: the dump's own timestamp (in its name) decides, not the object's dates
CUTOFF=$(date -u -d "@$(( $(date -u +%s) - KEEP_DAYS * 86400 ))" +%Y%m%dT%H%M%SZ)
aws s3api list-objects-v2 --bucket "$BACKUP_S3_BUCKET" --prefix "$PREFIX/otto-" \
    --query 'Contents[].Key' --output text |
    tr '\t' '\n' |
    while read -r old; do
        case "$old" in
            "$PREFIX"/otto-*.dump) ;;
            *) continue ;; # "None" (nothing listed), or not one of ours
        esac
        stamp=${old#"$PREFIX"/otto-}
        stamp=${stamp%.dump}
        # YYYYMMDDTHHMMSSZ without the T and Z is a number: compare as numbers (POSIX)
        if [ "$(echo "$stamp" | tr -d TZ)" -lt "$(echo "$CUTOFF" | tr -d TZ)" ] 2>/dev/null; then
            log "deleting $old (older than $KEEP_DAYS days)"
            aws s3 rm --only-show-errors "s3://$BACKUP_S3_BUCKET/$old"
        fi
    done
log "done: $DEST"
