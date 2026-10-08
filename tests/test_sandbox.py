import pytest

from orchestrator import sandbox


@pytest.fixture
def batch(monkeypatch):
    # never talk to a real cluster
    calls = []

    class FakeBatch:
        def create_namespaced_job(self, body, namespace):
            calls.append(("create", body.metadata.name, namespace))

        def delete_namespaced_job(self, name, namespace, body):
            calls.append(("delete", name, namespace))

    monkeypatch.setattr(sandbox, "_batch_api", lambda: FakeBatch())
    return calls


@pytest.mark.parametrize("sid", ["s1", "abc-123", "0", "a" * 58])
def test_valid_session_ids(batch, sid):
    assert sandbox.create_sandbox(sid, "https://example.com/r.git") == f"otto-{sid}"
    sandbox.destroy_sandbox(sid)
    assert [c[:2] for c in batch] == [("create", f"otto-{sid}"), ("delete", f"otto-{sid}")]


@pytest.mark.parametrize("sid", [
    "", "S1", "s_1", "s.1", "s 1", "s1-", "-", "s1\n", "ü", "a" * 59,  # otto- + 59 = 64 chars
])
def test_invalid_session_ids_raise_before_touching_k8s(batch, sid):
    with pytest.raises(ValueError, match="session id"):
        sandbox.create_sandbox(sid, "https://example.com/r.git")
    with pytest.raises(ValueError, match="session id"):
        sandbox.destroy_sandbox(sid)
    assert batch == []


# --- GitHub token injection ---------------------------------------------------

from shared import config
from gateway import github_app

TOKEN = "ghs_MintedInstallationToken42"


@pytest.fixture
def jobs(monkeypatch):
    created = []

    class FakeBatch:
        def create_namespaced_job(self, body, namespace):
            created.append(body)

    monkeypatch.setattr(sandbox, "_batch_api", lambda: FakeBatch())
    return created


def env_of(job):
    return {e.name: e.value for e in job.spec.template.spec.containers[0].env}


@pytest.fixture
def app_configured(monkeypatch):
    monkeypatch.setattr(config, "GITHUB_APP_ID", "123")
    monkeypatch.setattr(config, "GITHUB_INSTALLATION_ID", "456")  # the CLI's fallback; never used here
    monkeypatch.setattr(config, "GITHUB_APP_KEY_PATH", "/keys/app.pem")
    minted = []

    def mint(installation_id, repositories=None):
        minted.append((installation_id, repositories))
        return TOKEN

    monkeypatch.setattr(github_app, "mint_token", mint)
    return minted


def test_a_token_for_the_sessions_installation_and_repo_is_injected(jobs, app_configured, capsys):
    sandbox.create_sandbox("s1", "https://github.com/o/r", installation_id=789)
    env = env_of(jobs[0])
    assert env["GITHUB_TOKEN"] == TOKEN
    assert env["SESSION_ID"] == "s1" and env["REPO_URL"] == "https://github.com/o/r"
    assert app_configured == [(789, ["r"])]  # a fresh token, for this repo only
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err


def test_given_token_is_used_as_is(jobs, app_configured):
    sandbox.create_sandbox("s1", "https://github.com/o/r", installation_id=789, token="ghs_given")
    assert env_of(jobs[0])["GITHUB_TOKEN"] == "ghs_given"
    assert app_configured == []


def test_no_installation_means_no_token(jobs, app_configured):
    sandbox.create_sandbox("s1", "https://github.com/o/r")  # GITHUB_INSTALLATION_ID is not a fallback here
    assert "GITHUB_TOKEN" not in env_of(jobs[0])
    assert app_configured == []


def test_no_github_app_means_no_token(jobs, monkeypatch):
    monkeypatch.setattr(config, "GITHUB_APP_ID", None)
    monkeypatch.setattr(github_app, "mint_token", lambda *a, **kw: pytest.fail("must not mint without the App"))
    sandbox.create_sandbox("s1", "https://github.com/o/r", installation_id=789)
    assert "GITHUB_TOKEN" not in env_of(jobs[0])


# --- Job limits, status, removal ----------------------------------------------

from types import SimpleNamespace as NS

from kubernetes.client.exceptions import ApiException


def test_job_spec_limits_the_pod_lifetime(jobs, monkeypatch):
    monkeypatch.setattr(config, "SANDBOX_MAX_AGE_SECONDS", 3000)
    monkeypatch.setattr(config, "SANDBOX_IDLE_MINUTES", 2.5)
    sandbox.create_sandbox("s1", "https://github.com/o/r")
    spec = jobs[0].spec
    assert spec.active_deadline_seconds == 3000
    assert spec.ttl_seconds_after_finished == 100
    assert env_of(jobs[0])["SANDBOX_IDLE_MINUTES"] == "2.5"


def job(succeeded=None, failed=None, conditions=None, deleting=False):
    return NS(metadata=NS(name="otto-s1", deletion_timestamp="now" if deleting else None),
              status=NS(active=None, succeeded=succeeded, failed=failed, conditions=conditions))


class FakeK8s:
    def __init__(self, job=None, pods=()):
        self.job, self.pods, self.deleted = job, list(pods), []

    def read_namespaced_job(self, name, namespace):
        if self.job is None:
            raise ApiException(status=404, reason="NotFound")
        return self.job

    def delete_namespaced_job(self, name, namespace, body):
        if self.job is None:
            raise ApiException(status=404, reason="NotFound")
        self.deleted.append(name)
        self.job, self.pods = None, []  # instant, for the test

    def list_namespaced_pod(self, namespace, label_selector):
        return NS(items=[NS(metadata=NS(name=f"p{i}"), status=NS(phase=ph)) for i, ph in enumerate(self.pods)])


@pytest.fixture
def k8s(monkeypatch):
    def install(fake):
        monkeypatch.setattr(sandbox, "_batch_api", lambda: fake)
        monkeypatch.setattr(sandbox, "_core_api", lambda: fake)
        return fake
    return install


@pytest.mark.parametrize("fake, expected", [
    (FakeK8s(), "missing"),
    (FakeK8s(job(), []), "running"),                       # just created, no pod yet
    (FakeK8s(job(), ["Pending"]), "running"),
    (FakeK8s(job(), ["Running"]), "running"),
    (FakeK8s(job(), ["Succeeded"]), "finished"),           # runner exited (idle / shutdown)
    (FakeK8s(job(succeeded=1), ["Succeeded"]), "finished"),
    (FakeK8s(job(failed=1), ["Failed"]), "finished"),
    (FakeK8s(job(conditions=[NS(type="Failed", status="True")]), []), "finished"),  # deadline exceeded
    (FakeK8s(job(deleting=True), ["Running"]), "finished"),
])
def test_sandbox_status(k8s, fake, expected):
    k8s(fake)
    assert sandbox.sandbox_status("s1") == expected


def test_remove_sandbox(k8s):
    fake = k8s(FakeK8s(job(), ["Running"]))
    assert sandbox.remove_sandbox("s1") is True
    assert fake.deleted == ["otto-s1"]
    assert sandbox.remove_sandbox("s1") is False  # nothing left; not an error


# --- the Job's hardening, resources and the bus Secret ------------------------------------

def test_the_pod_is_locked_down(jobs):
    sandbox.create_sandbox("s1", "https://github.com/o/r")
    pod = jobs[0].spec.template.spec
    [c] = pod.containers
    assert pod.automount_service_account_token is False
    assert pod.security_context.run_as_non_root is True
    assert pod.security_context.run_as_user == 1000 and pod.security_context.fs_group == 1000
    assert pod.security_context.seccomp_profile.type == "RuntimeDefault"
    assert c.security_context.allow_privilege_escalation is False
    assert c.security_context.capabilities.drop == ["ALL"]
    assert c.security_context.run_as_non_root is True


def test_resources_come_from_the_config(jobs, monkeypatch):
    monkeypatch.setattr(config, "SANDBOX_RESOURCES", {
        "requests": {"cpu": "100m", "memory": "200Mi", "ephemeral-storage": "512Mi"},
        "limits": {"cpu": "2", "memory": "2Gi", "ephemeral-storage": "8Gi"}})
    sandbox.create_sandbox("s1", "https://github.com/o/r")
    res = jobs[0].spec.template.spec.containers[0].resources
    assert res.requests == {"cpu": "100m", "memory": "200Mi", "ephemeral-storage": "512Mi"}
    assert res.limits == {"cpu": "2", "memory": "2Gi", "ephemeral-storage": "8Gi"}


def test_the_default_resources_include_ephemeral_storage(jobs):
    sandbox.create_sandbox("s1", "https://github.com/o/r")
    res = jobs[0].spec.template.spec.containers[0].resources
    assert {"cpu", "memory", "ephemeral-storage"} == set(res.requests) == set(res.limits)


def bus_env(job):
    return next(e for e in job.spec.template.spec.containers[0].env if e.name == "BUS_URL")


def test_the_bus_url_comes_from_a_secret_when_one_is_named(jobs, monkeypatch):
    monkeypatch.setattr(config, "RUNNER_AMQP_SECRET", "otto-runner-amqp")
    monkeypatch.setattr(config, "RUNNER_AMQP_SECRET_KEY", "url")
    monkeypatch.setattr(config, "SANDBOX_BUS_URL", "amqp://runner:secret@bus:5672/")
    sandbox.create_sandbox("s1", "https://github.com/o/r")
    env = bus_env(jobs[0])
    assert env.value is None
    assert (env.value_from.secret_key_ref.name, env.value_from.secret_key_ref.key) == ("otto-runner-amqp", "url")
    assert "secret@bus" not in str(jobs[0])


def test_without_a_secret_the_bus_url_is_set_directly(jobs, monkeypatch):
    monkeypatch.setattr(config, "RUNNER_AMQP_SECRET", "")
    monkeypatch.setattr(config, "SANDBOX_BUS_URL", "amqp://guest:guest@rabbitmq:5672/")
    sandbox.create_sandbox("s1", "https://github.com/o/r")
    assert bus_env(jobs[0]).value == "amqp://guest:guest@rabbitmq:5672/"


def test_jobs_go_to_the_sandbox_namespace(monkeypatch):
    calls = []

    class FakeBatch:
        def create_namespaced_job(self, body, namespace):
            calls.append(namespace)

    monkeypatch.setattr(sandbox, "_batch_api", lambda: FakeBatch())
    monkeypatch.setattr(config, "K8S_NAMESPACE", "otto-sandboxes")
    sandbox.create_sandbox("s1", "https://github.com/o/r")
    assert calls == ["otto-sandboxes"]


# --- the cluster connection ------------------------------------------------------------------

@pytest.fixture
def fresh_client(monkeypatch):
    monkeypatch.setattr(sandbox, "_client", None)
    monkeypatch.setattr(sandbox, "_batch", None)
    monkeypatch.setattr(sandbox, "_core", None)


def test_the_kubeconfig_file_is_loaded(fresh_client, monkeypatch):
    loaded = []
    monkeypatch.setattr(config, "SANDBOX_KUBECONFIG", "/etc/otto/sandbox.kubeconfig")
    monkeypatch.setattr(sandbox.k8s_config, "new_client_from_config",
                        lambda config_file: loaded.append(config_file) or sandbox.client.ApiClient())
    sandbox._batch_api()
    sandbox._core_api()
    assert loaded == ["/etc/otto/sandbox.kubeconfig"]  # once, shared


def test_no_kubeconfig_in_production_means_not_configured(fresh_client, monkeypatch):
    monkeypatch.setattr(config, "SANDBOX_KUBECONFIG", "")
    monkeypatch.setattr(config, "PRODUCTION", True)
    monkeypatch.setattr(sandbox.k8s_config, "new_client_from_config",
                        lambda **kw: pytest.fail("no default kubeconfig in production"))
    with pytest.raises(sandbox.NotConfigured, match="OTTO_SANDBOX_KUBECONFIG"):
        sandbox._batch_api()
    assert sandbox.reachable() is False


def test_no_kubeconfig_in_development_uses_the_default_one(fresh_client, monkeypatch):
    loaded = []
    monkeypatch.setattr(config, "SANDBOX_KUBECONFIG", "")
    monkeypatch.setattr(config, "PRODUCTION", False)
    monkeypatch.setattr(sandbox.k8s_config, "new_client_from_config",
                        lambda config_file=None: loaded.append(config_file) or sandbox.client.ApiClient())
    sandbox._batch_api()
    assert loaded == [None]


def test_reachable_lists_jobs_in_the_namespace(monkeypatch):
    seen = []

    class FakeBatch:
        def list_namespaced_job(self, namespace, limit, _request_timeout):
            seen.append((namespace, limit))
            return NS(items=[])

    monkeypatch.setattr(sandbox, "_batch_api", lambda: FakeBatch())
    monkeypatch.setattr(config, "K8S_NAMESPACE", "otto-sandboxes")
    assert sandbox.reachable() is True
    assert seen == [("otto-sandboxes", 1)]


def test_an_unreachable_cluster_is_not_reachable(monkeypatch, fresh_client, capsys):
    class FakeBatch:
        def list_namespaced_job(self, **kw):
            raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(sandbox, "_batch_api", lambda: FakeBatch())
    assert sandbox.reachable() is False
    assert "unreachable" in capsys.readouterr().out
