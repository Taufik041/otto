#!/bin/sh
# The backup container: cron runs scripts/backup_db.sh nightly (BACKUP_CRON, default 03:15 UTC).
# Cron jobs start with an empty environment, so the container's (bucket, credentials, PG*) is
# saved here, quoted by the shell, and loaded by the job.
set -eu
umask 077
export -p > /run/backup.env
SCHEDULE="${BACKUP_CRON:-15 3 * * *}"
echo "$SCHEDULE . /run/backup.env; /usr/local/bin/backup_db.sh >> /proc/1/fd/1 2>&1" > /etc/crontabs/root
echo "[backup] scheduled: $SCHEDULE (UTC)"
exec crond -f -l 8
