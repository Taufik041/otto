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
