#!/usr/bin/env bash
# Check, from throwaway pods, that the sandbox namespace's NetworkPolicy really holds. Run it on
# the sandbox node, as root, after setup.sh:
#
#   sudo bash scripts/check_isolation.sh
#
# A probe pod in the sandbox namespace must reach github.com and pypi.org (DNS and HTTPS) and the
# server's RabbitMQ, and nothing else: not cloud metadata (169.254.169.254), not the private,
# carrier-grade NAT (tailnet) or link-local ranges, not this node's own addresses (where the
# script listens on 443 for the check), not the k3s API, not other pods, not the server's other
# ports. The same probe from a pod in a namespace without the policy shows which of those are
# really there, so a "blocked" means the policy blocked it. Last, from the node itself (not a
# pod), the tailnet policy should let it reach the server's RabbitMQ and nothing else.
#
# Exit status: 0 when every check passes. Settings: /etc/otto/sandbox-node.env (setup.sh).
set -euo pipefail

# shellcheck source=/dev/null
[ -f /etc/otto/sandbox-node.env ] && . /etc/otto/sandbox-node.env
NS="${SANDBOX_NAMESPACE:-otto-sandboxes}"
CONTROL_NS=otto-isolation-control
IMAGE="${SANDBOX_IMAGE:-ghcr.io/taufik041/otto-sandbox:main}"
: "${NODE_TS_IP:?run deploy/sandbox-node/setup.sh first}" "${SERVER_TS_IP:?run deploy/sandbox-node/setup.sh first}"
[ "$(id -u)" -eq 0 ] || { echo "run it as root: sudo bash $0" >&2; exit 1; }
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kc() { k3s kubectl "$@"; }

# Runs in the pods: each argument is tcp:<host>:<port> or https:<url>. Prints one line per target:
# "<target> ok|blocked <detail>". A connection that's made, or an HTTP answer of any status, is ok.
PROBE=$(cat <<'EOF'
import socket, ssl, sys, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

def probe(target):
    kind, _, rest = target.partition(":")
    try:
        if kind == "https":
            try:
                with urllib.request.urlopen(rest, timeout=10) as r:
                    return target, "ok", f"HTTP {r.status}"
            except urllib.error.HTTPError as e:
                return target, "ok", f"HTTP {e.code}"
        host, port = rest.rsplit(":", 1)
        socket.create_connection((host, int(port)), timeout=4).close()
        return target, "ok", "connected"
    except Exception as e:
        reason = getattr(e, "reason", e)
        return target, "blocked", f"{type(reason).__name__}: {reason}"[:80]

with ThreadPoolExecutor(32) as pool:
    for target, verdict, detail in pool.map(probe, sys.argv[1:]):
        print(target, verdict, detail, sep="\t")
EOF
)

decoy_pid=""
# shellcheck disable=SC2329  # run by the trap below
cleanup() {
    [ -n "$decoy_pid" ] && kill "$decoy_pid" 2>/dev/null
    kc delete pod -n "$NS" otto-isolation-probe otto-isolation-neighbour --ignore-not-found --wait=false >/dev/null 2>&1 || true
    kc delete namespace "$CONTROL_NS" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT

pod() {  # pod <namespace> <name> <role> <command...>: a small pod of the sandbox image
    local ns=$1 name=$2 role=$3; shift 3
    local args="" a
    for a in "$@"; do args+="\"$a\", "; done
    kc apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: $name
  namespace: $ns
  labels: { app: otto-isolation-check, role: $role }
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  terminationGracePeriodSeconds: 0
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 1000
    seccompProfile: { type: RuntimeDefault }
    # a non-root listener on 443 (a "safe" sysctl, allowed by the restricted profile)
    sysctls: [{ name: net.ipv4.ip_unprivileged_port_start, value: "0" }]
  containers:
    - name: check
      image: $IMAGE
      imagePullPolicy: IfNotPresent
      command: [${args%, }]
      securityContext:
        allowPrivilegeEscalation: false
        capabilities: { drop: [ALL] }
      resources:
        requests: { cpu: 50m, memory: 64Mi, ephemeral-storage: 64Mi }
        limits: { cpu: 100m, memory: 128Mi, ephemeral-storage: 512Mi }
EOF
}
pod_ip() { kc get pod -n "$1" "$2" -o jsonpath='{.status.podIP}'; }
probe_from() { local ns=$1 name=$2; shift 2; kc exec -n "$ns" "$name" -- python3 -c "$PROBE" "$@"; }

echo "== starting the check's pods"
kc create namespace "$CONTROL_NS" --dry-run=client -o yaml | kc apply -f - >/dev/null
pod "$NS" otto-isolation-probe probe sleep 600
pod "$NS" otto-isolation-neighbour neighbour python3 -m http.server 443
pod "$CONTROL_NS" otto-isolation-control control python3 -m http.server 443
for p in "$NS/otto-isolation-probe" "$NS/otto-isolation-neighbour" "$CONTROL_NS/otto-isolation-control"; do
    kc wait --for=condition=Ready -n "${p%/*}" "pod/${p#*/}" --timeout=180s >/dev/null \
        || { kc describe pod -n "${p%/*}" "${p#*/}" | tail -20; exit 1; }
done
NEIGHBOUR_IP=$(pod_ip "$NS" otto-isolation-neighbour)
CONTROL_IP=$(pod_ip "$CONTROL_NS" otto-isolation-control)

# something listening on 443 on every address of this node, so "blocked" can't mean "nothing there"
if ! ss -ltnH 'sport = :443' | grep -q .; then
    python3 -m http.server 443 --bind 0.0.0.0 >/dev/null 2>&1 &
    decoy_pid=$!
    sleep 1
fi
mapfile -t NODE_IPS < <(ip -4 -o addr show | awk '{ split($4, a, "/"); if (a[1] !~ /^127\./) print a[1] }' | sort -u)

ALLOWED=(https:https://github.com https:https://pypi.org/simple/ "tcp:$SERVER_TS_IP:5672")
BLOCKED=(tcp:169.254.169.254:80 tcp:169.254.169.254:443
         tcp:10.0.0.1:443 tcp:172.16.0.1:443 tcp:192.168.0.1:443 tcp:192.168.1.1:443 tcp:100.100.100.100:80
         "tcp:$NODE_TS_IP:6443" tcp:10.43.0.1:443
         "tcp:$CONTROL_IP:443"
         "tcp:$SERVER_TS_IP:22" "tcp:$SERVER_TS_IP:80" "tcp:$SERVER_TS_IP:443" "tcp:$SERVER_TS_IP:8000"
         "tcp:$SERVER_TS_IP:5432" "tcp:$SERVER_TS_IP:15672"
         tcp:8.8.8.8:53 tcp:1.1.1.1:22)
for a in "${NODE_IPS[@]}"; do BLOCKED+=("tcp:$a:443" "tcp:$a:22" "tcp:$a:10250"); done

echo "== probing"
declare -A sandbox control
while IFS=$'\t' read -r t v d; do sandbox[$t]="$v	$d"; done \
    < <(probe_from "$NS" otto-isolation-probe "${ALLOWED[@]}" "${BLOCKED[@]}" "tcp:$NEIGHBOUR_IP:443")
while IFS=$'\t' read -r t v d; do control[$t]="$v"; done \
    < <(probe_from "$CONTROL_NS" otto-isolation-control "${BLOCKED[@]}" "tcp:$NEIGHBOUR_IP:443")
# the neighbour's own view: its listener is up (so "blocked" below isn't "nothing there")
neighbour_self=$(probe_from "$NS" otto-isolation-neighbour tcp:127.0.0.1:443 | cut -f2)

failed=0
printf '\n%-50s %-8s %s\n' "from a sandbox pod: must work" result detail
for t in "${ALLOWED[@]}"; do
    IFS=$'\t' read -r v d <<<"${sandbox[$t]:-missing	no answer}"
    if [ "$v" = ok ]; then r=PASS; else r=FAIL; failed=1; fi
    printf '%-50s %-8s %s\n' "$t" "$r" "$d"
done
printf '\n%-50s %-8s %s\n' "from a sandbox pod: must be blocked" result "without the policy"
real=0
for t in "${BLOCKED[@]}"; do
    IFS=$'\t' read -r v d <<<"${sandbox[$t]:-missing	no answer}"
    if [ "$v" = blocked ]; then r=PASS; else r=FAIL; failed=1; fi
    c=${control[$t]:-?}
    [ "$c" = ok ] && { real=$((real + 1)); c="reachable"; } || c="not there either"
    printf '%-50s %-8s %s\n' "$t" "$r" "$c"
done
echo "   ($real of ${#BLOCKED[@]} are reachable from a pod without the policy: the policy is what blocks them)"

printf '\n%-50s %-8s %s\n' "into a sandbox pod: must be blocked" result detail
t="tcp:$NEIGHBOUR_IP:443"
IFS=$'\t' read -r v d <<<"${sandbox[$t]:-missing	no answer}"
if [ "$v" = blocked ]; then r=PASS; else r=FAIL; failed=1; fi
printf '%-50s %-8s %s\n' "$t (from another sandbox)" "$r" "its listener: ${neighbour_self:-?} from inside"
v=${control[$t]:-missing}
if [ "$v" = blocked ]; then r=PASS; else r=FAIL; failed=1; fi
printf '%-50s %-8s %s\n' "$t (from outside the namespace)" "$r" "$v"

echo
echo "from this node (the tailnet policy: $SERVER_TS_IP:5672 only)"
for port in 5672 22 443 8000; do
    if timeout 4 bash -c "exec 3<>/dev/tcp/$SERVER_TS_IP/$port" 2>/dev/null; then got=open; else got=closed; fi
    if [ "$port" = 5672 ]; then want=open; else want=closed; fi
    if [ "$got" = "$want" ]; then r=PASS; else r=FAIL; failed=1; fi
    printf '%-50s %-8s %s\n' "tcp:$SERVER_TS_IP:$port" "$r" "$got (want $want)"
done

echo
if [ "$failed" -eq 0 ]; then echo "isolation: every check passed"; else echo "isolation: SOME CHECKS FAILED (above)"; fi
exit "$failed"
