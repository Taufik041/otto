#!/usr/bin/env bash
# Local dev: keep RabbitMQ (the kind cluster's svc/rabbitmq) on localhost:5672. A port-forward
# dies, or stops answering, when the pod restarts; this one is restarted whenever it ends or RabbitMQ
# stops answering through it. dev_up.sh starts it in the background (.logs/rabbitmq-forward.log).
#
#   scripts/rabbitmq_forward.sh            supervise the port-forward (runs until stopped)
#   scripts/rabbitmq_forward.sh wait [S]   wait up to S seconds [60] until RabbitMQ answers on it
set -uo pipefail

PORT="${RABBITMQ_FORWARD_PORT:-5672}"
CHECK_EVERY=5   # seconds between checks
MAX_MISSES=3    # checks in a row without an answer before the port-forward is restarted

log() { echo "[rabbitmq-forward] $(date +%T) $*"; }

# RabbitMQ answers an AMQP 0-9-1 protocol header with its Connection.Start frame; a port-forward
# whose pod is gone accepts the connection but never answers
answers() {
    (
        exec 3<>"/dev/tcp/127.0.0.1/$PORT" || exit 1
        printf 'AMQP\0\0\x09\x01' >&3
        [ -n "$(timeout 3 head -c 1 <&3 | od -An -c)" ]
    ) 2>/dev/null
}

if [ "${1:-}" = wait ]; then
    for _ in $(seq "${2:-60}"); do answers && exit 0; sleep 1; done
    echo "RabbitMQ doesn't answer on localhost:$PORT (see .logs/rabbitmq-forward.log)" >&2
    exit 1
fi

pf=
trap '[ -n "$pf" ] && kill "$pf" 2>/dev/null; exit 0' INT TERM
while true; do
    kubectl port-forward svc/rabbitmq "$PORT:5672" >/dev/null 2>&1 &
    pf=$!
    log "port-forward started (pid $pf)"
    misses=0
    while kill -0 "$pf" 2>/dev/null; do
        sleep "$CHECK_EVERY"
        if answers; then
            misses=0
        elif (( ++misses >= MAX_MISSES )); then
            log "RabbitMQ hasn't answered for $((misses * CHECK_EVERY))s: restarting the port-forward"
            kill "$pf" 2>/dev/null
        fi
    done
    wait "$pf" 2>/dev/null
    log "port-forward ended; starting it again in 2s"
    sleep 2
done
