#!/usr/bin/env bash
# Turn an Ubuntu 24.04 x86 machine (a cloud instance, a desktop, a laptop: nothing here assumes
# which) into Otto's sandbox node: one k3s node, reachable only over Tailscale, running sandbox
# Jobs in one namespace that the gateway reaches with its own narrow kubeconfig. The machine must
# already be on the tailnet with the sandbox tag (docs/deploy.md, "Sandbox node").
#
# Idempotent: every step checks before it changes anything. Run it again to change a setting, to
# upgrade k3s (K3S_VERSION), or to finish a step it skipped.
#
#   sudo env SERVER_TS_IP=100.x.y.z RUNNER_AMQP_PASSWORD=... bash setup.sh
#   sudo env SERVER_TS_IP=100.x.y.z bash setup.sh render     # print the manifests, change nothing
#
# Settings (environment):
#   SERVER_TS_IP            the server's Tailscale address (its RabbitMQ), required
#   NODE_NAME               the Kubernetes node's name [the hostname]
#   SANDBOX_TAG             the Tailscale tag this machine must have [tag:sandbox]
#   SANDBOX_NAMESPACE       where sandboxes run, the gateway's OTTO_SANDBOX_NAMESPACE [otto-sandboxes]
#   SANDBOX_IMAGE           pulled ahead of the first session [ghcr.io/taufik041/otto-sandbox:main].
#                           The gateway runs the deployed commit's tag (:<sha>, deploy.sh pins it),
#                           which shares all but its last layers with :main, so pulling :main
#                           makes that first pull small. Pass the deployed :<sha> to pull it all.
#   SANDBOX_SLOTS           sandboxes at once, the gateway's MAX_ACTIVE_SANDBOXES [1: a 2 GB node]
#   OTTO_SANDBOX_CPU_REQUEST, _CPU_LIMIT, _MEMORY_REQUEST, _MEMORY_LIMIT, _STORAGE_REQUEST,
#   _STORAGE_LIMIT          one sandbox's size, as the gateway's variables of the same names
#                           [200m/1, 300Mi/1Gi, 1Gi/4Gi]; the quota is SANDBOX_SLOTS of them
#   RUNNER_AMQP_PASSWORD    the server's RABBITMQ_RUNNER_PASSWORD: creates or updates the runners'
#                           RabbitMQ URL Secret (only needed once, and when it changes)
#   RUNNER_AMQP_USER        its RabbitMQ user [otto-runner]
#   RUNNER_AMQP_SECRET      the Secret's name, the gateway's OTTO_RUNNER_AMQP_SECRET [otto-runner-amqp]
#   GHCR_USER, GHCR_TOKEN   pull credentials for ghcr.io, only if the sandbox image is private
#   K3S_VERSION             install or move to this k3s release (e.g. v1.34.1+k3s1) [the stable
#                           channel's, on first install; left alone after]
#   SWAP_SIZE               the swap file's size, when the machine has no swap [2G]
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
NODE_NAME="${NODE_NAME:-$(hostname -s | tr '[:upper:]_' '[:lower:]-')}"
SANDBOX_TAG="${SANDBOX_TAG:-tag:sandbox}"
SANDBOX_NAMESPACE="${SANDBOX_NAMESPACE:-otto-sandboxes}"
SANDBOX_IMAGE="${SANDBOX_IMAGE:-ghcr.io/taufik041/otto-sandbox:main}"
SANDBOX_SLOTS="${SANDBOX_SLOTS:-1}"
CPU_REQUEST="${OTTO_SANDBOX_CPU_REQUEST:-200m}"
CPU_LIMIT="${OTTO_SANDBOX_CPU_LIMIT:-1}"
MEMORY_REQUEST="${OTTO_SANDBOX_MEMORY_REQUEST:-300Mi}"
MEMORY_LIMIT="${OTTO_SANDBOX_MEMORY_LIMIT:-1Gi}"
STORAGE_REQUEST="${OTTO_SANDBOX_STORAGE_REQUEST:-1Gi}"
STORAGE_LIMIT="${OTTO_SANDBOX_STORAGE_LIMIT:-4Gi}"
RUNNER_AMQP_USER="${RUNNER_AMQP_USER:-otto-runner}"
RUNNER_AMQP_SECRET="${RUNNER_AMQP_SECRET:-otto-runner-amqp}"
SWAP_SIZE="${SWAP_SIZE:-2G}"
K3S_VERSION="${K3S_VERSION:-}"
# room in the quota for scripts/check_isolation.sh's two small pods, never for another sandbox
EXTRA_PODS=2 EXTRA_CPU_M=200 EXTRA_MEMORY_MI=256 EXTRA_STORAGE_MI=1024

ENV_FILE=/etc/otto/sandbox-node.env
K3S_CONFIG=/etc/rancher/k3s/config.yaml
K3S_REGISTRIES=/etc/rancher/k3s/registries.yaml
K3S_DROPIN=/etc/systemd/system/k3s.service.d/10-otto.conf
export DEBIAN_FRONTEND=noninteractive

step() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# Kubernetes quantities as millicores / MiB (binary suffixes only, or none: a CPU count)
cpu_m() {
    case "$1" in
        *m) awk -v q="${1%m}" 'BEGIN { printf "%d", q }' ;;
        *[!0-9.]* | "") die "not a CPU quantity: $1 (e.g. 500m, 1, 1.5)" ;;
        *) awk -v q="$1" 'BEGIN { printf "%d", q * 1000 }' ;;
    esac
}
mib() {
    case "$1" in
        *Ki) awk -v q="${1%Ki}" 'BEGIN { printf "%d", q / 1024 }' ;;
        *Mi) awk -v q="${1%Mi}" 'BEGIN { printf "%d", q }' ;;
        *Gi) awk -v q="${1%Gi}" 'BEGIN { printf "%d", q * 1024 }' ;;
        *Ti) awk -v q="${1%Ti}" 'BEGIN { printf "%d", q * 1024 * 1024 }' ;;
        *) die "not a size in Ki, Mi, Gi or Ti: $1" ;;
    esac
}

as_size() {  # MiB as Kubernetes writes it back (so a second apply finds nothing to change)
    if (( $1 % 1024 == 0 )); then echo "$(( $1 / 1024 ))Gi"; else echo "${1}Mi"; fi
}

is_cgnat() {  # in 100.64.0.0/10, Tailscale's addresses
    [[ "$1" =~ ^100\.([0-9]+)\.[0-9]+\.[0-9]+$ ]] && (( BASH_REMATCH[1] >= 64 && BASH_REMATCH[1] <= 127 ))
}

tailscale_field() {  # one field of `tailscale status --json`: state, tags or ip
    tailscale status --json 2>/dev/null | python3 -c '
import json, sys
s = json.load(sys.stdin)
me = s.get("Self") or {}
field = sys.argv[1]
if field == "state":
    print(s.get("BackendState", ""))
elif field == "tags":
    print(" ".join(me.get("Tags") or []))
elif field == "ip":
    print(next((a for a in me.get("TailscaleIPs") or [] if "." in a), ""))
' "$1"
}

node_ts_ip() {
    if [ -n "${NODE_TS_IP:-}" ]; then echo "$NODE_TS_IP"; return; fi
    command -v tailscale >/dev/null || die "Tailscale isn't installed: join the tailnet first (docs/deploy.md, \"Sandbox node\")"
    tailscale_field ip
}

# shellcheck disable=SC2034  # the QUOTA_* are read by render(), through ${!name}
compute_quota() {
    [[ "$SANDBOX_SLOTS" =~ ^[1-9][0-9]*$ ]] || die "SANDBOX_SLOTS must be a whole number, at least 1"
    local slots=$SANDBOX_SLOTS
    QUOTA_PODS=$(( slots + EXTRA_PODS ))
    QUOTA_CPU_REQUESTS="$(( slots * $(cpu_m "$CPU_REQUEST") + EXTRA_CPU_M ))m"
    QUOTA_CPU_LIMITS="$(( slots * $(cpu_m "$CPU_LIMIT") + EXTRA_CPU_M ))m"
    QUOTA_MEMORY_REQUESTS=$(as_size $(( slots * $(mib "$MEMORY_REQUEST") + EXTRA_MEMORY_MI )))
    QUOTA_MEMORY_LIMITS=$(as_size $(( slots * $(mib "$MEMORY_LIMIT") + EXTRA_MEMORY_MI )))
    QUOTA_STORAGE_REQUESTS=$(as_size $(( slots * $(mib "$STORAGE_REQUEST") + EXTRA_STORAGE_MI )))
    QUOTA_STORAGE_LIMITS=$(as_size $(( slots * $(mib "$STORAGE_LIMIT") + EXTRA_STORAGE_MI )))
    (( $(cpu_m "$CPU_REQUEST") <= $(cpu_m "$CPU_LIMIT") )) || die "the CPU request is above the limit"
    (( $(mib "$MEMORY_REQUEST") <= $(mib "$MEMORY_LIMIT") )) || die "the memory request is above the limit"
    (( $(mib "$STORAGE_REQUEST") <= $(mib "$STORAGE_LIMIT") )) || die "the storage request is above the limit"
}

RENDER_VARS=(NODE_NAME NODE_TS_IP SERVER_TS_IP SANDBOX_NAMESPACE SANDBOX_SLOTS QUOTA_PODS
             CPU_REQUEST CPU_LIMIT MEMORY_REQUEST MEMORY_LIMIT STORAGE_REQUEST STORAGE_LIMIT
             QUOTA_CPU_REQUESTS QUOTA_CPU_LIMITS QUOTA_MEMORY_REQUESTS QUOTA_MEMORY_LIMITS
             QUOTA_STORAGE_REQUESTS QUOTA_STORAGE_LIMITS)
render() {  # a template with ${NAME} placeholders, filled in
    local text name
    text=$(<"$1")
    for name in "${RENDER_VARS[@]}"; do
        text=${text//"\${$name}"/${!name}}
    done
    # shellcheck disable=SC2016  # a literal ${, the placeholders' start
    [[ "$text" != *'${'* ]] || die "$1: a placeholder is left: $(grep -o '\${[A-Z_]*}' <<<"$text" | sort -u | tr '\n' ' ')"
    printf '%s\n' "$text"
}

manifests() {  # the namespace first: everything else lives in it
    render "$HERE/manifests/namespace.yaml"
    local f
    for f in "$HERE"/manifests/*.yaml; do
        [ "$(basename "$f")" = namespace.yaml ] && continue
        printf -- '---\n'
        render "$f"
    done
}

install_if_changed() {  # install_if_changed <mode> <path>, content on stdin; true if it changed
    local mode=$1 path=$2 tmp
    tmp=$(mktemp)
    cat > "$tmp"
    if [ -f "$path" ] && cmp -s "$tmp" "$path"; then
        rm -f "$tmp"
        chmod "$mode" "$path"
        return 1
    fi
    install -D -m "$mode" "$tmp" "$path"
    rm -f "$tmp"
}

# --- settings, checked before anything changes ---------------------------------------------
[ -n "${SERVER_TS_IP:-}" ] || die "set SERVER_TS_IP to the server's Tailscale address (on the server: tailscale ip -4)"
is_cgnat "$SERVER_TS_IP" || die "SERVER_TS_IP=$SERVER_TS_IP isn't a Tailscale address (100.64.0.0/10)"
[[ "$NODE_NAME" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || die "NODE_NAME=$NODE_NAME: use lowercase letters, digits and '-'"
compute_quota

if [ "${1:-}" = render ]; then
    NODE_TS_IP=$(node_ts_ip)
    [ -n "$NODE_TS_IP" ] || die "no Tailscale address: set NODE_TS_IP to render without Tailscale"
    render "$HERE/k3s-config.yaml"
    printf -- '---\n'
    manifests
    exit 0
fi
[ $# -eq 0 ] || die "usage: setup.sh [render]"
[ "$(id -u)" -eq 0 ] || die "run it as root: sudo bash $0"
# shellcheck source=/dev/null
. /etc/os-release
[ "${ID:-}" = ubuntu ] && [ "${VERSION_ID:-}" = 24.04 ] || echo "warning: written for Ubuntu 24.04; this is ${PRETTY_NAME:-unknown}" >&2
[ "$(uname -m)" = x86_64 ] || echo "warning: written for x86_64; this is $(uname -m)" >&2

step "swap"
if [ -f /.dockerenv ] || [ -f /run/.containerenv ] || systemd-detect-virt --container --quiet 2>/dev/null; then
    note "skipped: this is a container (its host's swap applies)"
elif [ -n "$(swapon --show=NAME --noheadings)" ]; then
    note "already on: $(swapon --show=NAME,SIZE --noheadings | tr -s ' ' | paste -sd, -)"
else
    [ -f /swapfile ] || { fallocate -l "$SWAP_SIZE" /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null; }
    swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    # only under real pressure: k3s and the system may swap, sandboxes never do (no swap for pods)
    echo 'vm.swappiness=10' > /etc/sysctl.d/90-otto-swap.conf
    sysctl -q -p /etc/sysctl.d/90-otto-swap.conf
    note "/swapfile ($SWAP_SIZE) on"
fi

step "packages"
missing=()
for cmd in curl python3 awk ip; do command -v "$cmd" >/dev/null || missing+=("$cmd"); done
if [ "${#missing[@]}" -gt 0 ]; then
    apt-get update -q
    apt-get install -y -q ca-certificates curl python3 gawk iproute2 >/dev/null
    note "installed: ${missing[*]}"
else
    note "curl, python3, awk and ip are there"
fi

step "tailscale ($SANDBOX_TAG)"
command -v tailscale >/dev/null || die "Tailscale isn't installed: join the tailnet with a $SANDBOX_TAG key first (docs/deploy.md, \"Sandbox node\")"
state=$(tailscale_field state)
[ "$state" = Running ] || die "Tailscale isn't connected (state: ${state:-unknown}): run tailscale up with a $SANDBOX_TAG key"
tags=$(tailscale_field tags)
[[ " $tags " == *" $SANDBOX_TAG "* ]] || die "this machine isn't tagged $SANDBOX_TAG (tags: ${tags:-none}): join with a key for that tag, or tailscale up --advertise-tags=$SANDBOX_TAG"
NODE_TS_IP=$(node_ts_ip)
is_cgnat "$NODE_TS_IP" || die "no Tailscale IPv4 address (got '${NODE_TS_IP}')"
[ "$NODE_TS_IP" != "$SERVER_TS_IP" ] || die "SERVER_TS_IP is this machine's own address: give the server's"
note "joined as $NODE_TS_IP, tagged $tags"
if timeout 5 bash -c "exec 3<>/dev/tcp/$SERVER_TS_IP/5672" 2>/dev/null; then
    note "the server's RabbitMQ answers at $SERVER_TS_IP:5672"
else
    note "warning: nothing answers at $SERVER_TS_IP:5672 yet (the server's RABBITMQ_BIND, and the tailnet rule $SANDBOX_TAG -> tag:otto:5672)"
fi

step "the node's settings ($ENV_FILE)"
install -D -m 0755 "$HERE/sandbox-node" /usr/local/bin/sandbox-node
install_if_changed 0644 "$ENV_FILE" <<EOF || true
# written by deploy/sandbox-node/setup.sh; read by sandbox-node, scripts/check_isolation.sh and
# scripts/sandbox_kubeconfig.sh
NODE_NAME=$NODE_NAME
NODE_TS_IP=$NODE_TS_IP
SERVER_TS_IP=$SERVER_TS_IP
SANDBOX_NAMESPACE=$SANDBOX_NAMESPACE
SANDBOX_IMAGE=$SANDBOX_IMAGE
SANDBOX_SLOTS=$SANDBOX_SLOTS
EOF
note "sandbox-node up|down|status is installed"

step "k3s"
changed=0
render "$HERE/k3s-config.yaml" | install_if_changed 0600 "$K3S_CONFIG" && { changed=1; note "wrote $K3S_CONFIG"; }
if [ -n "${GHCR_TOKEN:-}" ]; then
    # the node's pull credentials (containerd's), so neither a Job spec nor a Secret carries them
    printf 'configs:\n  "ghcr.io":\n    auth:\n      username: "%s"\n      password: "%s"\n' \
        "${GHCR_USER:?set GHCR_USER with GHCR_TOKEN}" "$GHCR_TOKEN" \
        | install_if_changed 0600 "$K3S_REGISTRIES" && { changed=1; note "wrote ghcr.io's pull credentials to $K3S_REGISTRIES"; }
fi
# start only once the Tailscale address exists: the API and the kubelet bind to it
install_if_changed 0644 "$K3S_DROPIN" <<'EOF' && { changed=1; systemctl daemon-reload; } || true
# written by deploy/sandbox-node/setup.sh
[Unit]
Wants=tailscaled.service
After=tailscaled.service network-online.target

[Service]
ExecStartPre=/usr/local/bin/sandbox-node wait-address
EOF
installed=$(k3s --version 2>/dev/null | awk 'NR == 1 { print $3 }' || true)
if [ -z "$installed" ] || { [ -n "$K3S_VERSION" ] && [ "$installed" != "$K3S_VERSION" ]; }; then
    note "installing k3s ${K3S_VERSION:-(stable channel)}${installed:+ over $installed}"
    installer=$(mktemp)
    curl -fsSL https://get.k3s.io -o "$installer"
    INSTALL_K3S_VERSION="$K3S_VERSION" INSTALL_K3S_SKIP_START=true INSTALL_K3S_SKIP_ENABLE=true \
        sh "$installer" server >/var/log/k3s-install.log 2>&1 \
        || { cat /var/log/k3s-install.log >&2; die "the k3s install failed"; }
    rm -f "$installer"
    changed=1
fi
systemctl daemon-reload
systemctl enable k3s >/dev/null 2>&1
if [ "$changed" -eq 1 ] && systemctl is-active --quiet k3s; then
    note "restarting k3s (its settings changed)"
    systemctl restart k3s
else
    systemctl start k3s
fi
note "$(k3s --version | head -1)"

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kc() { k3s kubectl "$@"; }
for _ in $(seq 90); do kc get --raw /readyz >/dev/null 2>&1 && break; sleep 2; done
kc get --raw /readyz >/dev/null || die "the k3s API didn't come up: journalctl -u k3s"
for _ in $(seq 60); do kc get node "$NODE_NAME" >/dev/null 2>&1 && break; sleep 2; done
kc wait --for=condition=Ready "node/$NODE_NAME" --timeout=180s >/dev/null
# k3s deploys CoreDNS a moment after the API is up; sandboxes need it to resolve anything
for _ in $(seq 60); do kc -n kube-system get deploy/coredns >/dev/null 2>&1 && break; sleep 2; done
kc -n kube-system rollout status deploy/coredns --timeout=180s >/dev/null
note "node $NODE_NAME is Ready; the API listens on https://$NODE_TS_IP:6443"

step "the sandbox namespace ($SANDBOX_NAMESPACE)"
# again if needed: a new namespace's default service account appears while this applies
for i in 1 2 3; do
    if out=$(manifests | kc apply -f - 2>&1); then break; fi
    [ "$i" -lt 3 ] || { echo "$out" >&2; die "couldn't apply the manifests"; }
    sleep 3
done
printf '   %s\n' "${out//$'\n'/$'\n'   }"
note "quota: $SANDBOX_SLOTS sandbox(es) of $CPU_LIMIT CPU, $MEMORY_LIMIT memory, $STORAGE_LIMIT disk"

step "the runners' RabbitMQ URL (Secret $RUNNER_AMQP_SECRET)"
if [ -n "${RUNNER_AMQP_PASSWORD:-}" ]; then
    [[ "$RUNNER_AMQP_PASSWORD" =~ ^[A-Za-z0-9._~-]+$ ]] || die "RUNNER_AMQP_PASSWORD must be URL-safe (openssl rand -hex 24)"
    # through stdin, so the password never sits in a process's arguments
    printf 'amqp://%s:%s@%s:5672/' "$RUNNER_AMQP_USER" "$RUNNER_AMQP_PASSWORD" "$SERVER_TS_IP" \
        | kc create secret generic "$RUNNER_AMQP_SECRET" -n "$SANDBOX_NAMESPACE" --from-file=url=/dev/stdin \
            --dry-run=client -o yaml \
        | kc apply -f - | sed 's/^/   /'
elif kc get secret "$RUNNER_AMQP_SECRET" -n "$SANDBOX_NAMESPACE" >/dev/null 2>&1; then
    note "already there (set RUNNER_AMQP_PASSWORD to change it)"
else
    note "MISSING: run again with RUNNER_AMQP_PASSWORD (the server's RABBITMQ_RUNNER_PASSWORD)"
fi

step "the sandbox image ($SANDBOX_IMAGE)"
pulled=0
for i in 1 2 3; do
    if err=$(k3s crictl pull "$SANDBOX_IMAGE" 2>&1 >/dev/null); then pulled=1; break; fi
    note "pull failed (try $i of 3): $(tail -1 <<<"$err" | cut -c1-160)"
    sleep 5
done
if [ "$pulled" -eq 1 ]; then
    note "pulled: the first session starts without waiting for it"
else
    note "warning: couldn't pull it (private? set GHCR_USER and GHCR_TOKEN); sessions will try again"
fi

step "next"
note "the gateway's kubeconfig:   sudo bash scripts/sandbox_kubeconfig.sh > sandbox.kubeconfig"
note "the isolation check:        sudo bash scripts/check_isolation.sh"
note "on the server, in .env:     OTTO_SANDBOX_NAMESPACE=$SANDBOX_NAMESPACE  OTTO_RUNNER_AMQP_SECRET=$RUNNER_AMQP_SECRET"
note "                            MAX_ACTIVE_SANDBOXES=$SANDBOX_SLOTS, and the same OTTO_SANDBOX_* sizes as here"
