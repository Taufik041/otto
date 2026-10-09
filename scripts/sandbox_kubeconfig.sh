#!/usr/bin/env bash
# Print a kubeconfig for the gateway: its service account (otto-gateway, with the long-lived token
# in the Secret otto-gateway-token, deploy/sandbox-node/manifests/rbac.yaml), pointing at the
# sandbox node's API on its Tailscale address. Run it on the node, as root:
#
#   sudo bash scripts/sandbox_kubeconfig.sh > sandbox.kubeconfig
#
# It then goes into the server's deploy/compose/secrets/ (docs/deploy.md, "Sandbox node").
# The kubeconfig is on stdout; everything else on stderr.
#
# Settings (environment; /etc/otto/sandbox-node.env, written by setup.sh, gives the defaults):
#   SANDBOX_NAMESPACE   [otto-sandboxes]
#   SANDBOX_API_SERVER  the API's URL as the gateway reaches it [https://<NODE_TS_IP>:6443]
#   KUBECTL             a kubectl with admin access to the cluster [kubectl; k3s's on the node]
set -euo pipefail

# shellcheck source=/dev/null
[ -f /etc/otto/sandbox-node.env ] && . /etc/otto/sandbox-node.env
NS="${SANDBOX_NAMESPACE:-otto-sandboxes}"
KUBECTL="${KUBECTL:-kubectl}"
[ -f /etc/rancher/k3s/k3s.yaml ] && [ -z "${KUBECONFIG:-}" ] && export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
if [ -n "${SANDBOX_API_SERVER:-}" ]; then
    SERVER="$SANDBOX_API_SERVER"
elif [ -n "${NODE_TS_IP:-}" ]; then
    SERVER="https://$NODE_TS_IP:6443"
else
    echo "set SANDBOX_API_SERVER (or run deploy/sandbox-node/setup.sh first)" >&2
    exit 1
fi
kc() { "$KUBECTL" "$@"; }

# the token controller fills the Secret in a moment after it's created
token=""
for _ in $(seq 30); do
    token=$(kc get secret otto-gateway-token -n "$NS" -o jsonpath='{.data.token}' 2>/dev/null || true)
    [ -n "$token" ] && break
    sleep 1
done
[ -n "$token" ] || { echo "no token in secret/otto-gateway-token in $NS: run setup.sh (or apply manifests/rbac.yaml)" >&2; exit 1; }
ca=$(kc get secret otto-gateway-token -n "$NS" -o jsonpath='{.data.ca\.crt}')

# written out here, not with `kubectl config set-credentials --token=...`: the token stays out of
# every process's arguments
config=$(cat <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: otto-sandbox
    cluster:
      server: $SERVER
      certificate-authority-data: $ca
users:
  - name: otto-gateway
    user:
      token: $(printf '%s' "$token" | base64 -d)
contexts:
  - name: otto-sandbox
    context:
      cluster: otto-sandbox
      user: otto-gateway
      namespace: $NS
current-context: otto-sandbox
EOF
)

# check it as the gateway will use it: allowed, then refused
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
chmod 600 "$tmp"
printf '%s\n' "$config" > "$tmp"
can() { KUBECONFIG="$tmp" kc auth can-i "$@" -n "$NS" 2>/dev/null || true; }
create_jobs=$(can create jobs)
get_secrets=$(can get secrets)
other_ns=$(KUBECONFIG="$tmp" kc auth can-i list pods -n kube-system 2>/dev/null || true)
echo "checked through $SERVER: create jobs: $create_jobs; get secrets: $get_secrets; pods in kube-system: $other_ns" >&2
[ "$create_jobs" = yes ] && [ "$get_secrets" = no ] && [ "$other_ns" = no ] \
    || { echo "the kubeconfig doesn't have the gateway's access (want yes, no, no)" >&2; exit 1; }

printf '%s\n' "$config"
