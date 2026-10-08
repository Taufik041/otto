#!/usr/bin/env bash
# Prepare a fresh Ubuntu 24.04 server (an EC2 t3.small, x86, with no inbound ports) to run Otto's
# backend: swap, unattended upgrades, Docker and its compose plugin, Tailscale, a deploy user, the
# repo with its compose stack, and a systemd unit that starts the stack on boot.
#
# Idempotent: every step checks before it changes anything, so run it again after an update, or
# to finish a step it skipped (Tailscale without a key, a stack whose .env isn't filled in yet).
#
#   sudo env TAILSCALE_AUTH_KEY=tskey-auth-... \
#            DEPLOY_SSH_PUBLIC_KEY="ssh-ed25519 AAAA... github-actions" \
#            bash bootstrap.sh
#
# Settings (environment):
#   TAILSCALE_AUTH_KEY      joins the tailnet (only needed until it has joined)
#   TAILSCALE_HOSTNAME      its name on the tailnet [otto-prod]
#   DEPLOY_USER             the user deploys log in as [deploy]
#   DEPLOY_SSH_PUBLIC_KEY   a public key allowed to log in as it (GitHub Actions'), added once
#   OTTO_REPO               the repo to check out [https://github.com/Taufik041/otto.git]
#   OTTO_DIR                where [/opt/otto]
#   SWAP_SIZE               the swap file's size [2G]
#   GHCR_USER, GHCR_TOKEN   log Docker in to ghcr.io (only if the otto-backend image is private)
set -euo pipefail

TAILSCALE_HOSTNAME="${TAILSCALE_HOSTNAME:-otto-prod}"
DEPLOY_USER="${DEPLOY_USER:-deploy}"
OTTO_REPO="${OTTO_REPO:-https://github.com/Taufik041/otto.git}"
OTTO_DIR="${OTTO_DIR:-/opt/otto}"
SWAP_SIZE="${SWAP_SIZE:-2G}"
COMPOSE_DIR="$OTTO_DIR/deploy/compose"
COMPOSE=(docker compose -f docker-compose.prod.yml)
export DEBIAN_FRONTEND=noninteractive

step() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "run it as root: sudo bash $0" >&2; exit 1; }
# shellcheck source=/dev/null
. /etc/os-release
[ "${ID:-}" = ubuntu ] || echo "warning: written for Ubuntu 24.04; this is ${PRETTY_NAME:-unknown}" >&2

step "swap ($SWAP_SIZE)"
if [ -f /.dockerenv ] || [ -f /run/.containerenv ] || systemd-detect-virt --container --quiet 2>/dev/null; then
    note "skipped: this is a container (its host's swap applies)"
elif swapon --show=NAME --noheadings | grep -qx /swapfile; then
    note "/swapfile is on"
else
    [ -f /swapfile ] || { fallocate -l "$SWAP_SIZE" /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null; }
    swapon /swapfile
    note "/swapfile on"
fi
[ -f /swapfile ] && { grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab; }
# only swap under real pressure: 2 GB of RAM is the budget, swap the safety net
echo 'vm.swappiness=10' > /etc/sysctl.d/90-otto-swap.conf
sysctl -q -p /etc/sysctl.d/90-otto-swap.conf

step "packages and unattended upgrades"
apt-get update -q
apt-get install -y -q ca-certificates curl git gnupg unattended-upgrades >/dev/null
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
# security updates every day; a reboot when one needs it, at 04:30 UTC (after the 03:15 backup).
# The stack comes back by itself (otto.service).
cat > /etc/apt/apt.conf.d/52otto-unattended <<'EOF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:30";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
EOF
systemctl enable --now unattended-upgrades >/dev/null
note "on: daily security updates, rebooting at 04:30 UTC when needed"

step "docker"
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -q
    apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
fi
systemctl enable --now docker >/dev/null
note "$(docker --version), compose $(docker compose version --short)"
if [ -n "${GHCR_TOKEN:-}" ]; then
    echo "$GHCR_TOKEN" | docker login ghcr.io -u "${GHCR_USER:?set GHCR_USER with GHCR_TOKEN}" --password-stdin >/dev/null
    note "logged in to ghcr.io as $GHCR_USER"
fi

step "tailscale"
if ! command -v tailscale >/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh >/var/log/tailscale-install.log 2>&1 \
        || { cat /var/log/tailscale-install.log >&2; exit 1; }
fi
systemctl enable --now tailscaled >/dev/null
if tailscale status >/dev/null 2>&1; then
    note "joined as $(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["HostName"])'), $(tailscale ip -4)"
elif [ -n "${TAILSCALE_AUTH_KEY:-}" ]; then
    tailscale up --auth-key="$TAILSCALE_AUTH_KEY" --hostname="$TAILSCALE_HOSTNAME"
    note "joined as $TAILSCALE_HOSTNAME, $(tailscale ip -4)"
else
    note "NOT JOINED: run again with TAILSCALE_AUTH_KEY (deploys and the sandbox cluster reach the server over Tailscale)"
fi

step "deploy user ($DEPLOY_USER)"
id "$DEPLOY_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$DEPLOY_USER"
usermod -aG docker "$DEPLOY_USER"
HOME_DIR=$(getent passwd "$DEPLOY_USER" | cut -d: -f6)
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$HOME_DIR/.ssh"
touch "$HOME_DIR/.ssh/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "$HOME_DIR/.ssh/authorized_keys"
chmod 600 "$HOME_DIR/.ssh/authorized_keys"
if [ -n "${DEPLOY_SSH_PUBLIC_KEY:-}" ] && ! grep -qxF "$DEPLOY_SSH_PUBLIC_KEY" "$HOME_DIR/.ssh/authorized_keys"; then
    echo "$DEPLOY_SSH_PUBLIC_KEY" >> "$HOME_DIR/.ssh/authorized_keys"
    note "added a key to $HOME_DIR/.ssh/authorized_keys"
fi
note "$(grep -c . "$HOME_DIR/.ssh/authorized_keys") key(s) may log in as $DEPLOY_USER"
# keys only, no root logins (the security group has no inbound rules: ssh comes over Tailscale)
cat > /etc/ssh/sshd_config.d/60-otto.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true

step "the repo ($OTTO_DIR)"
if [ -d "$OTTO_DIR/.git" ]; then
    note "already checked out (deploys update it)"
else
    install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$OTTO_DIR"
    sudo -u "$DEPLOY_USER" git clone --quiet "$OTTO_REPO" "$OTTO_DIR"
    note "cloned $OTTO_REPO"
fi
cd "$COMPOSE_DIR"
if [ ! -f .env ]; then
    install -m 600 -o "$DEPLOY_USER" -g "$DEPLOY_USER" .env.prod.example .env
    note "created $COMPOSE_DIR/.env from the example: fill it in"
fi
# the backend runs as uid 10001 and reads these (read-only); nobody else may
install -d -m 700 -o 10001 -g 10001 secrets
find secrets -type f -exec chown 10001:10001 {} + -exec chmod 400 {} +

step "systemd unit (otto.service)"
cat > /etc/systemd/system/otto.service <<EOF
[Unit]
Description=Otto's backend (docker compose, $COMPOSE_DIR)
Requires=docker.service
Wants=network-online.target tailscaled.service
After=docker.service network-online.target tailscaled.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=$DEPLOY_USER
Group=docker
WorkingDirectory=$COMPOSE_DIR
# RabbitMQ may bind to the Tailscale address (RABBITMQ_BIND): wait for it, up to a minute
ExecStartPre=/bin/sh -c 'for i in \$(seq 30); do tailscale ip -4 >/dev/null 2>&1 && exit 0; sleep 2; done; echo "no Tailscale address yet" >&2'
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml up -d --remove-orphans
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml stop
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable otto.service >/dev/null
note "enabled: the stack starts on boot"

step "the stack"
# required = the example's uncommented lines; each must have a value in .env
missing=()
while IFS= read -r name; do
    grep -qE "^${name}=.+" .env || missing+=("$name")
done < <(grep -oE '^[A-Z][A-Z0-9_]*=' .env.prod.example | tr -d '=')
for f in sandbox.kubeconfig github-app.pem; do [ -s "secrets/$f" ] || missing+=("secrets/$f"); done
if [ "${#missing[@]}" -gt 0 ]; then
    note "not started: still missing in $COMPOSE_DIR: ${missing[*]}"
    note "fill them in, then run this again (or: sudo systemctl start otto)"
else
    systemctl restart otto.service
    note "started; waiting for the gateway"
    for _ in $(seq 60); do
        curl -fsS "http://127.0.0.1:$(grep -oP '^GATEWAY_PORT=\K.+' .env || echo 8000)/health" 2>/dev/null && { echo; break; }
        sleep 5
    done
    sudo -u "$DEPLOY_USER" "${COMPOSE[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
fi

step "for GitHub Actions (docs/deploy.md, \"Deploys\")"
note "DEPLOY_HOST:        $TAILSCALE_HOSTNAME  ($(tailscale ip -4 2>/dev/null || echo 'not on Tailscale yet'))"
note "DEPLOY_KNOWN_HOSTS: (the lines below)"
HOST_KEY=/etc/ssh/ssh_host_ed25519_key.pub
# both the tailnet name and its address, so DEPLOY_HOST may be either
NAMES="$TAILSCALE_HOSTNAME"
TS_IP=$(tailscale ip -4 2>/dev/null || true)
[ -n "$TS_IP" ] && NAMES="$NAMES,$TS_IP"
[ -f "$HOST_KEY" ] && echo "$NAMES $(cut -d' ' -f1,2 "$HOST_KEY")"
note "RABBITMQ_BIND for the sandbox cluster's runners: $(tailscale ip -4 2>/dev/null || echo 'its Tailscale address')"
