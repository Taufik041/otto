# Nightly database backups (scripts/backup_db.sh): pg_dump 16, the aws CLI, and cron.
FROM postgres:16-alpine
RUN apk add --no-cache aws-cli
COPY scripts/backup_db.sh /usr/local/bin/backup_db.sh
COPY deploy/backup/start.sh /usr/local/bin/backup-start
ENTRYPOINT []
CMD ["backup-start"]
