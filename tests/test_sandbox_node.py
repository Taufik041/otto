"""The sandbox node (deploy/sandbox-node/) keeps its promises: k3s without the parts Otto doesn't
use and its API on the Tailscale address only, sandbox pods that can reach only DNS, the server's
RabbitMQ and the internet on 80/443, a gateway that can touch only Jobs and Pods in its namespace,
a runner RabbitMQ user limited to the sessions' queues, and the sandbox image built on main."""
import re
from pathlib import Path

import yaml

from shared import bus

ROOT = Path(__file__).resolve().parent.parent
NODE = ROOT / "deploy/sandbox-node"
VALUES = {"NODE_NAME": "otto-sandbox", "NODE_TS_IP": "100.101.102.103", "SERVER_TS_IP": "100.90.80.70",
          "SANDBOX_NAMESPACE": "otto-sandboxes", "SANDBOX_SLOTS": "1", "QUOTA_PODS": "2",
          "CPU_REQUEST": "200m", "CPU_LIMIT": "1", "MEMORY_REQUEST": "300Mi", "MEMORY_LIMIT": "1Gi",
          "STORAGE_REQUEST": "1Gi", "STORAGE_LIMIT": "4Gi", "QUOTA_CPU_REQUESTS": "450m",
          "QUOTA_CPU_LIMITS": "1250m", "QUOTA_MEMORY_REQUESTS": "556Mi", "QUOTA_MEMORY_LIMITS": "1280Mi",
          "QUOTA_STORAGE_REQUESTS": "2Gi", "QUOTA_STORAGE_LIMITS": "5Gi"}
PRIVATE = {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"}


def render(path: Path) -> list[dict]:
    """The file as setup.sh renders it (${NAME} -> its value), as YAML documents."""
    text = path.read_text()
    for name, value in VALUES.items():
        text = text.replace("${" + name + "}", value)
    assert "${" not in text, re.findall(r"\$\{\w+\}", text)
    return [d for d in yaml.safe_load_all(text) if d]


def manifests() -> dict[tuple[str, str], dict]:
    docs = [d for f in sorted((NODE / "manifests").glob("*.yaml")) for d in render(f)]
    return {(d["kind"], d["metadata"]["name"]): d for d in docs}


def test_k3s_runs_without_traefik_servicelb_or_metrics_server():
    (cfg,) = render(NODE / "k3s-config.yaml")
    assert set(cfg["disable"]) >= {"traefik", "servicelb", "metrics-server"}
    assert "disable-network-policy" not in cfg  # its policy controller enforces the NetworkPolicy


def test_the_k3s_api_listens_only_on_the_tailscale_address():
    (cfg,) = render(NODE / "k3s-config.yaml")
    ip = VALUES["NODE_TS_IP"]
    assert cfg["bind-address"] == cfg["advertise-address"] == cfg["node-ip"] == ip
    assert ip in cfg["tls-san"]
    assert f"address={ip}" in cfg["kubelet-arg"]  # the kubelet too, not every interface


def test_everything_lives_in_one_restricted_namespace():
    ms = manifests()
    ns = ms[("Namespace", "otto-sandboxes")]
    assert ns["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"
    for (kind, name), doc in ms.items():
        if kind != "Namespace":
            assert doc["metadata"]["namespace"] == "otto-sandboxes", (kind, name)


def test_sandbox_pods_get_no_ingress_and_egress_only_where_they_need():
    pol = manifests()[("NetworkPolicy", "otto-sandbox-isolation")]["spec"]
    assert pol["podSelector"] == {}  # every pod in the namespace
    assert sorted(pol["policyTypes"]) == ["Egress", "Ingress"]
    assert pol.get("ingress", []) == []
    dns, rabbit, internet = pol["egress"]

    assert dns["to"] == [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
                          "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}]
    assert sorted((p["protocol"], p["port"]) for p in dns["ports"]) == [("TCP", 53), ("UDP", 53)]

    assert rabbit["to"] == [{"ipBlock": {"cidr": VALUES["SERVER_TS_IP"] + "/32"}}]
    assert rabbit["ports"] == [{"protocol": "TCP", "port": 5672}]

    (block,) = internet["to"]
    assert block["ipBlock"]["cidr"] == "0.0.0.0/0"
    assert set(block["ipBlock"]["except"]) == PRIVATE
    assert sorted(p["port"] for p in internet["ports"]) == [80, 443]
    assert {p["protocol"] for p in internet["ports"]} == {"TCP"}


def test_the_gateway_can_only_run_jobs_and_read_pods():
    ms = manifests()
    assert not any(kind.startswith("Cluster") for kind, _ in ms)
    role = ms[("Role", "otto-gateway")]
    rules = {(g, r): sorted(rule["verbs"]) for rule in role["rules"]
             for g in rule["apiGroups"] for r in rule["resources"]}
    assert rules == {("batch", "jobs"): ["create", "delete", "get", "list"],
                     ("", "pods"): ["get", "list"], ("", "pods/log"): ["get"]}
    binding = ms[("RoleBinding", "otto-gateway")]
    assert binding["subjects"] == [{"kind": "ServiceAccount", "name": "otto-gateway", "namespace": "otto-sandboxes"}]
    token = ms[("Secret", "otto-gateway-token")]
    assert token["type"] == "kubernetes.io/service-account-token"
    assert token["metadata"]["annotations"]["kubernetes.io/service-account.name"] == "otto-gateway"


def test_sandbox_pods_get_no_service_account_token():
    sa = manifests()[("ServiceAccount", "default")]
    assert sa["automountServiceAccountToken"] is False


def test_the_quota_and_limits_fit_the_configured_sandboxes():
    ms = manifests()
    hard = ms[("ResourceQuota", "otto-sandboxes")]["spec"]["hard"]
    assert hard["pods"] == VALUES["QUOTA_PODS"]
    assert hard["limits.memory"] == VALUES["QUOTA_MEMORY_LIMITS"]
    assert hard["services"] == "0"  # nothing in the namespace listens
    (limit,) = ms[("LimitRange", "otto-sandboxes")]["spec"]["limits"]
    assert limit["type"] == "Container"
    assert limit["max"] == {"cpu": "1", "memory": "1Gi", "ephemeral-storage": "4Gi"}
    assert limit["default"] == limit["max"]
    assert limit["defaultRequest"] == {"cpu": "200m", "memory": "300Mi", "ephemeral-storage": "1Gi"}


def runner_permissions() -> dict[str, str]:
    """configure / write / read, as deploy/compose/runner_user.sh sets them"""
    text = (ROOT / "deploy/compose/runner_user.sh").read_text()
    return {k: re.search(rf"^{k.upper()}_RE='([^']+)'", text, re.M).group(1) for k in ("configure", "write", "read")}


def test_the_runner_user_may_use_only_the_sessions_queues():
    perms = runner_permissions()
    sid = "a1b2-c3"
    for k in ("configure", "write", "read"):
        assert re.fullmatch(perms[k], bus.actions_queue(sid)), k
        assert re.fullmatch(perms[k], bus.results_queue(sid)), k
        for other in (bus.SESSIONS_QUEUE, "otto.a1.events", "amq.gen-x", "otto..actions", "x.otto.a.actions"):
            assert not re.search(perms[k], other), (k, other)
    # results go out through the default exchange (amq.default); nothing else is written
    assert re.search(perms["write"], "amq.default")
    assert not re.search(perms["configure"], "amq.default")
    assert not re.search(perms["read"], "amq.default")


def test_ci_builds_the_sandbox_image_for_every_commit_on_main():
    wf = yaml.safe_load((ROOT / ".github/workflows/backend.yml").read_text())
    on = wf[True]  # yaml reads the `on:` key as True
    # every push to main, whatever it changes, so each deployable commit has its :<sha> images
    assert on["push"] == {"branches": ["main"]}
    assert {"infra/sandbox.Dockerfile", "infra/entrypoint.sh"} <= set(on["pull_request"]["paths"])
    # and a newer push never cancels main's run halfway, leaving a commit without them
    assert wf["concurrency"]["cancel-in-progress"] == "${{ github.ref != 'refs/heads/main' }}"
    job = wf["jobs"]["sandbox-image"]
    assert job["needs"] == "test" and "refs/heads/main" in job["if"]
    (build,) = [s for s in job["steps"] if str(s.get("uses", "")).startswith("docker/build-push-action")]
    w = build["with"]
    assert (w["file"], w["target"], w["push"]) == ("infra/sandbox.Dockerfile", "runner", True)
    assert set(w["tags"].splitlines()) == {"ghcr.io/taufik041/otto-sandbox:${{ github.sha }}",
                                      "ghcr.io/taufik041/otto-sandbox:main"}


def test_production_defaults_to_the_published_sandbox_image(monkeypatch):
    import dotenv, importlib
    from shared import config

    monkeypatch.setattr(dotenv, "load_dotenv", lambda **kw: None)
    monkeypatch.delenv("SANDBOX_IMAGE", raising=False)
    try:
        monkeypatch.setenv("OTTO_ENV", "production")
        assert importlib.reload(config).SANDBOX_IMAGE == "ghcr.io/taufik041/otto-sandbox:main"
        monkeypatch.setenv("OTTO_ENV", "development")
        assert importlib.reload(config).SANDBOX_IMAGE == "taufik041/otto-sandbox:dev"  # kind loads it locally
        monkeypatch.setenv("SANDBOX_IMAGE", "ghcr.io/taufik041/otto-sandbox:abc")
        assert importlib.reload(config).SANDBOX_IMAGE == "ghcr.io/taufik041/otto-sandbox:abc"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_workers_show_offline_within_30_seconds_of_the_node_going_down():
    from orchestrator import sandbox

    compose = yaml.safe_load((ROOT / "deploy/compose/docker-compose.prod.yml").read_text())
    check = compose["x-backend"]["environment"]["OTTO_WORKERS_CHECK_SECONDS"]
    seconds = float(re.fullmatch(r"\$\{OTTO_WORKERS_CHECK_SECONDS:-(\d+)\}", check).group(1))
    # a cached "online" lasts at most `seconds`; the next check gives up after REACH_TIMEOUT
    assert seconds + sandbox.REACH_TIMEOUT <= 30


def test_the_runners_rabbitmq_password_is_required():
    env = (ROOT / "deploy/compose/.env.prod.example").read_text()
    assert re.search(r"^RABBITMQ_RUNNER_PASSWORD=$", env, re.M)
    assert re.search(r"^# SANDBOX_IMAGE=$", env, re.M)  # optional now: production has a default


def rendered(**env) -> dict[tuple[str, str], dict]:
    """`setup.sh render`'s output: what it would apply (it changes nothing, and needs no root)."""
    import os, subprocess
    run = subprocess.run(["bash", str(NODE / "setup.sh"), "render"], capture_output=True, text=True,
                         env={"PATH": os.environ["PATH"], "SERVER_TS_IP": "100.90.80.70",
                              "NODE_TS_IP": "100.101.102.103", "NODE_NAME": "otto-sandbox", **env})
    assert run.returncode == 0, run.stderr
    docs = [d for d in yaml.safe_load_all(run.stdout) if d]
    return {(d.get("kind", "k3s-config"), d.get("metadata", {}).get("name", "")): d for d in docs}


def test_the_quota_is_one_sandbox_by_default_and_grows_with_the_slots():
    hard = rendered()[("ResourceQuota", "otto-sandboxes")]["spec"]["hard"]
    # one sandbox (200m/1 CPU, 300Mi/1Gi, 1Gi/4Gi) and the isolation check's two small pods
    assert hard == {"pods": "3", "requests.cpu": "400m", "limits.cpu": "1200m",
                    "requests.memory": "556Mi", "limits.memory": "1280Mi",
                    "requests.ephemeral-storage": "2Gi", "limits.ephemeral-storage": "5Gi",
                    "services": "0", "persistentvolumeclaims": "0"}
    big = rendered(SANDBOX_SLOTS="3", OTTO_SANDBOX_CPU_LIMIT="2", OTTO_SANDBOX_MEMORY_LIMIT="2Gi")
    hard = big[("ResourceQuota", "otto-sandboxes")]["spec"]["hard"]
    assert (hard["pods"], hard["limits.cpu"], hard["limits.memory"]) == ("5", "6200m", "6400Mi")
    (limit,) = big[("LimitRange", "otto-sandboxes")]["spec"]["limits"]
    assert limit["max"] == {"cpu": "2", "memory": "2Gi", "ephemeral-storage": "4Gi"}


def test_render_refuses_bad_settings():
    import os, subprocess
    for env in ({"SERVER_TS_IP": "10.0.0.5"}, {"SERVER_TS_IP": ""}, {"SANDBOX_SLOTS": "0"},
                {"OTTO_SANDBOX_MEMORY_LIMIT": "1G"}, {"OTTO_SANDBOX_CPU_REQUEST": "2", "OTTO_SANDBOX_CPU_LIMIT": "1"}):
        run = subprocess.run(["bash", str(NODE / "setup.sh"), "render"], capture_output=True, text=True,
                             env={"PATH": os.environ["PATH"], "SERVER_TS_IP": "100.90.80.70",
                                  "NODE_TS_IP": "100.101.102.103", "NODE_NAME": "n", **env})
        assert run.returncode != 0 and "error:" in run.stderr, env


SHA_A, SHA_B = "a" * 40, "0123456789abcdef" * 2 + "01234567"


def pin(env_file: Path, sha: str):
    import os, subprocess
    return subprocess.run(["bash", str(ROOT / "deploy/aws/pin_images.sh"), str(env_file), sha],
                          capture_output=True, text=True, env={"PATH": os.environ["PATH"]})


def pinned(env_file: Path) -> dict[str, list[str]]:
    lines = env_file.read_text().splitlines()
    return {k: [l.split("=", 1)[1] for l in lines if l.startswith(k + "=")]
            for k in ("OTTO_IMAGE", "SANDBOX_IMAGE", "OTTO_VERSION")}


def test_a_deploy_pins_the_commits_backend_and_sandbox_images(tmp_path):
    env = tmp_path / ".env"
    env.write_text("POSTGRES_PASSWORD=x\n# SANDBOX_IMAGE=\nOTTO_SANDBOX_NAMESPACE=otto-sandboxes")  # no last newline
    assert pin(env, SHA_A).returncode == 0
    assert pinned(env) == {"OTTO_IMAGE": [f"ghcr.io/taufik041/otto-backend:{SHA_A}"],
                           "SANDBOX_IMAGE": [f"ghcr.io/taufik041/otto-sandbox:{SHA_A}"],
                           "OTTO_VERSION": [SHA_A[:12]]}
    text = env.read_text()
    assert "POSTGRES_PASSWORD=x\n# SANDBOX_IMAGE=\nOTTO_SANDBOX_NAMESPACE=otto-sandboxes\n" in text  # the rest as it was


def test_a_rollback_puts_back_both_images(tmp_path):
    env = tmp_path / ".env"
    env.write_text("POSTGRES_PASSWORD=x\nSANDBOX_IMAGE=ghcr.io/taufik041/otto-sandbox:main\n")
    for sha in (SHA_A, SHA_B, SHA_A):  # deploy A, deploy B, roll back to A
        assert pin(env, sha).returncode == 0
    assert pinned(env) == {"OTTO_IMAGE": [f"ghcr.io/taufik041/otto-backend:{SHA_A}"],
                           "SANDBOX_IMAGE": [f"ghcr.io/taufik041/otto-sandbox:{SHA_A}"],
                           "OTTO_VERSION": [SHA_A[:12]]}
    assert env.read_text().count("pinned by") == 2  # added once each (OTTO_IMAGE, OTTO_VERSION), then replaced


def test_pinning_refuses_anything_but_a_full_commit_sha(tmp_path):
    env = tmp_path / ".env"
    env.write_text("POSTGRES_PASSWORD=x\n")
    for bad in ("main", SHA_A[:12], SHA_A + "; rm -rf /", SHA_A.upper()):
        assert pin(env, bad).returncode != 0, bad
    assert env.read_text() == "POSTGRES_PASSWORD=x\n"


def test_deploy_pins_through_pin_images_and_checks_the_sandbox_tag_first():
    deploy = (ROOT / "deploy/aws/deploy.sh").read_text()
    check = deploy.index('docker manifest inspect "$SANDBOX"')
    assert check < deploy.index("pin_images.sh .env") < deploy.index("up -d")
    assert "sed -i" not in deploy  # the pins live in one place
