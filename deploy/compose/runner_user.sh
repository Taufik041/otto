#!/usr/bin/env bash
# Create or update RabbitMQ's user for the sandbox runners (otto-runner), with the password in
# .env's RABBITMQ_RUNNER_PASSWORD. It may use only the sessions' own queues,
# otto.<session>.actions and otto.<session>.results: not otto.sessions (the brain workers' jobs),
# no other queue or exchange, no management. Run in deploy/compose, as the deploy user, with the
# stack up; deploy/aws/bootstrap.sh and deploy/aws/deploy.sh do. Running it again changes
# nothing, or applies a new password.
#
# The runners' URL, amqp://otto-runner:<password>@<RABBITMQ_BIND>:5672/, goes in the sandbox
# namespace's Secret (OTTO_RUNNER_AMQP_SECRET): deploy/sandbox-node/setup.sh makes it.
set -euo pipefail
cd "$(dirname "$0")"

RUNNER_USER=otto-runner
# a runner declares and reads both of its session's queues, and publishes its results through
# the default exchange (amq.default)
CONFIGURE_RE='^otto\.[a-z0-9-]+\.(actions|results)$'
WRITE_RE='^(otto\.[a-z0-9-]+\.(actions|results)|amq\.default)$'
READ_RE='^otto\.[a-z0-9-]+\.(actions|results)$'

password=$(grep -oP '^RABBITMQ_RUNNER_PASSWORD=\K.+' .env || true)
[ -n "$password" ] || { echo "set RABBITMQ_RUNNER_PASSWORD in $PWD/.env (openssl rand -hex 24)" >&2; exit 1; }
[[ "$password" =~ ^[A-Za-z0-9._~-]+$ ]] || { echo "RABBITMQ_RUNNER_PASSWORD must be URL-safe (openssl rand -hex 24)" >&2; exit 1; }

# RabbitMQ's definitions, with the password as RabbitMQ stores it (a salted SHA-256): the
# password itself never reaches the container or any process's arguments. Importing them again
# replaces the user's password and permissions.
definitions=$(RUNNER_PASSWORD="$password" python3 - "$RUNNER_USER" "$CONFIGURE_RE" "$WRITE_RE" "$READ_RE" <<'EOF'
import base64, hashlib, json, os, sys

user, configure, write, read = sys.argv[1:]
salt = os.urandom(4)
digest = hashlib.sha256(salt + os.environ["RUNNER_PASSWORD"].encode()).digest()
print(json.dumps({
    "users": [{"name": user, "password_hash": base64.b64encode(salt + digest).decode(),
               "hashing_algorithm": "rabbit_password_hashing_sha256", "tags": []}],
    "permissions": [{"user": user, "vhost": "/", "configure": configure, "write": write, "read": read}],
}))
EOF
)

printf '%s' "$definitions" | docker compose -f docker-compose.prod.yml exec -T rabbitmq sh -c '
    f=$(mktemp); trap "rm -f \"$f\"" EXIT; cat > "$f"; rabbitmqctl -q import_definitions "$f"' >/dev/null
echo "RabbitMQ user $RUNNER_USER: only otto.<session>.actions and .results"
