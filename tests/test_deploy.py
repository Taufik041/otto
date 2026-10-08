"""The production packaging stays in step with the code: deploy/compose/.env.prod.example lists
every variable (with no values), and docker-compose.prod.yml keeps its promises (nothing public,
memory that fits 2 GB, log rotation, healthchecks, restarts)."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "deploy/compose/docker-compose.prod.yml"
ENV_EXAMPLE = ROOT / "deploy/compose/.env.prod.example"
READS = re.compile(r'(?:environ\.get|env\.get|csv\(os\.environ, |flag\(os\.environ, |numbered_keys\(env, )\(?"([A-Z0-9_]+)"')
# set by the compose file itself, or only inside a sandbox (by the orchestrator)
NOT_IN_ENV_FILE = {"OTTO_ENV", "DATABASE_URL", "BUS_URL", "OTTO_SANDBOX_KUBECONFIG", "GITHUB_APP_KEY_PATH",
                   "SESSION_ID", "REPO_URL", "GITHUB_TOKEN", "OTTO_WORKSPACE"}
BACKUP_VARS = {"BACKUP_S3_BUCKET", "BACKUP_S3_PREFIX", "BACKUP_KEEP_DAYS", "BACKUP_CRON", "AWS_ACCESS_KEY_ID",
               "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION", "AWS_ENDPOINT_URL"}
MIB = {"m": 1, "g": 1024}


def code_vars() -> set[str]:
    found = set()
    for d in ("shared", "brain", "gateway", "orchestrator", "runner"):
        for f in (ROOT / d).glob("*.py"):
            found |= set(READS.findall(f.read_text()))
    return found


def env_lines() -> dict[str, str]:
    """name -> the line, for `NAME=` and `# NAME=` lines"""
    out = {}
    for line in ENV_EXAMPLE.read_text().splitlines():
        m = re.fullmatch(r"(?:# )?([A-Z][A-Z0-9_]*)=(.*)", line)
        if m:
            out[m.group(1)] = line
    return out


def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text())


def test_the_env_example_lists_every_variable():
    listed = env_lines()
    compose_vars = set(re.findall(r"\$\{([A-Z0-9_]+)", COMPOSE.read_text()))
    wanted = (code_vars() - NOT_IN_ENV_FILE) | compose_vars | BACKUP_VARS
    assert wanted - listed.keys() == set()
    assert "AUTH_SECRET" in wanted and "POSTGRES_PASSWORD" in wanted  # the scan finds things


def test_the_env_example_has_no_values():
    assert {name: line for name, line in env_lines().items() if not line.endswith("=")} == {}


def test_the_compose_file_sets_what_the_env_file_must_not():
    env = compose()["x-backend"]["environment"]
    assert env["OTTO_ENV"] == "production"
    assert {"DATABASE_URL", "BUS_URL", "OTTO_SANDBOX_KUBECONFIG", "GITHUB_APP_KEY_PATH"} <= env.keys()


def test_nothing_is_published_publicly():
    services = compose()["services"]
    assert "ports" not in services["postgres"]
    for name, svc in services.items():
        for port in svc.get("ports", []):
            host = port.rsplit(":", 2)[0]
            assert host.startswith(("127.0.0.1", "${RABBITMQ_BIND:-127.0.0.1}")), (name, port)


def test_every_service_restarts_rotates_logs_and_fits_2_gb():
    services = compose()["services"]
    total = 0
    for name, svc in services.items():
        assert svc["restart"] == "unless-stopped", name
        assert svc["logging"]["options"] == {"max-size": "10m", "max-file": "3"}, name
        limit = svc["deploy"]["resources"]["limits"]["memory"]
        total += int(limit[:-1]) * MIB[limit[-1]]
    assert total <= 1700  # MiB: the rest of 2 GB is the system's


def test_the_long_running_services_have_healthchecks():
    services = compose()["services"]
    for name in ("postgres", "rabbitmq", "gateway", "worker", "cloudflared"):
        assert services[name]["healthcheck"]["test"], name


def test_the_worker_waits_for_the_gateway_which_migrates():
    services = compose()["services"]
    assert services["worker"]["depends_on"]["gateway"]["condition"] == "service_healthy"
    assert services["gateway"]["depends_on"]["postgres"]["condition"] == "service_healthy"
