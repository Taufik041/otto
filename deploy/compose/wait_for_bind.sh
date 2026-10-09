#!/usr/bin/env bash
# otto.service's ExecStartPre (deploy/aws/bootstrap.sh): RabbitMQ publishes its port on
# RABBITMQ_BIND, which is the Tailscale address; Docker can't bind to it until tailscaled has put
# it on tailscale0. Wait for it, up to two minutes; then fail, so systemd tries again later.
set -euo pipefail
cd "$(dirname "$0")"
bind=$(grep -oP '^RABBITMQ_BIND=\K.+' .env 2>/dev/null || true)
case "$bind" in "" | 127.* | 0.0.0.0) exit 0 ;; esac
for i in $(seq 60); do
    ip -4 -o addr show | grep -q " inet $bind/" && exit 0
    [ "$i" -eq 1 ] && echo "waiting for $bind (RABBITMQ_BIND) to come up" >&2
    sleep 2
done
echo "no interface has $bind (RABBITMQ_BIND) after 2 minutes: is Tailscale up? (tailscale status)" >&2
exit 1
