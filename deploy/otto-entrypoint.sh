#!/bin/sh
# otto-backend's entrypoint: which process this container is.
#   gateway           the HTTP API (migrates the database to head when it starts)
#   worker            a brain worker (consumes otto.sessions)
#   access-requests   list or approve access requests (python -m scripts.access_requests ...)
set -e
cmd="${1:-gateway}"
[ "$#" -gt 0 ] && shift
case "$cmd" in
    gateway)
        # behind cloudflared: trust its X-Forwarded-* (the gateway itself is never public)
        exec uvicorn gateway.app:app --host 0.0.0.0 --port "${PORT:-8000}" \
            --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" --no-server-header "$@" ;;
    worker)
        exec python -m brain.worker "$@" ;;
    access-requests)
        exec python -m scripts.access_requests "$@" ;;
    *)
        exec "$cmd" "$@" ;;
esac
