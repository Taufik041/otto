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
    monkeypatch.setattr(config, "GITHUB_INSTALLATION_ID", "456")
    monkeypatch.setattr(config, "GITHUB_APP_KEY_PATH", "/keys/app.pem")
    minted = []

    def mint():
        minted.append(1)
        return TOKEN

    monkeypatch.setattr(github_app, "get_installation_token", mint)
    return minted


def test_token_is_minted_and_injected(jobs, app_configured, capsys):
    sandbox.create_sandbox("s1", "https://github.com/o/r")
    env = env_of(jobs[0])
    assert env["GITHUB_TOKEN"] == TOKEN
    assert env["SESSION_ID"] == "s1" and env["REPO_URL"] == "https://github.com/o/r"
    assert app_configured == [1]
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err


def test_given_token_is_used_as_is(jobs, app_configured):
    sandbox.create_sandbox("s1", "https://github.com/o/r", token="ghs_given")
    assert env_of(jobs[0])["GITHUB_TOKEN"] == "ghs_given"
    assert app_configured == []


def test_no_github_app_means_no_token(jobs, monkeypatch):
    monkeypatch.setattr(config, "GITHUB_APP_ID", None)
    monkeypatch.setattr(github_app, "get_installation_token",
                        lambda: pytest.fail("must not mint without GitHub App config"))
    sandbox.create_sandbox("s1", "https://github.com/o/r")
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
