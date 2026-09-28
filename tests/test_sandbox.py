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
