#!/usr/bin/env bash
# otto.sh — feel the product: sessions as pods
set -e
CMD=$1; SID=$2

case $CMD in
  up)
    kubectl run "otto-$SID" \
      --image=taufik041/otto-sandbox:dev \
      --image-pull-policy=Always \
      --restart=Never \
      --env="SESSION_ID=$SID" \
      --env="REPO_URL=${3:-}" \
      --command -- sh -c '
        if [ -n "$REPO_URL" ]; then git clone "$REPO_URL" /workspace; else mkdir -p /workspace; fi;
        echo "sandbox $SESSION_ID ready"; touch /tmp/otto-ready; sleep infinity'
    echo "waiting for pod..."
    kubectl wait --for=condition=Ready "pod/otto-$SID" --timeout=120s
    echo "waiting for sandbox setup (apt + clone)..."
    until kubectl exec "otto-$SID" -- test -f /tmp/otto-ready 2>/dev/null; do sleep 2; done
    echo "session $SID ready"
    ;;
  sh)
    kubectl exec -it "otto-$SID" -- bash -c 'cd /workspace && exec bash'
    ;;
  down)
    kubectl delete pod "otto-$SID" --grace-period=0 --force
    ;;
  ls)
    kubectl get pods --no-headers 2>/dev/null | grep ^otto- || echo "no sessions"
    ;;
  *)
    echo "usage: ./otto.sh up <session-id> [repo-url] | sh <id> | down <id> | ls"
    ;;
esac