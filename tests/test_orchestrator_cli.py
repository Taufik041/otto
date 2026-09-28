from types import SimpleNamespace as NS

import pytest
from kubernetes.client.exceptions import ApiException

from orchestrator import cli, sandbox
from shared import config

LISTENING = "[runner] Listening for actions on otto.s1.actions"
STARTS_OK = [("Pending", None), ("Running", "cloning"), ("Running", LISTENING)]


class FakeCluster:
    """Just enough of BatchV1Api + CoreV1Api. Deletes and pod start-up take a few polls."""

    def __init__(self, old_job=False, new_pod=STARTS_OK):
        self.jobs = {}   # name -> None while alive, or polls left until a delete completes
        self.pods = {}   # name -> {"states": [(phase, logs)], "i": current state}
        self.calls = []
        self.new_pod = new_pod
        if old_job:
            self.jobs["otto-s1"] = None
            self._add_pod("otto-s1-old", [("Running", LISTENING)])

    def _add_pod(self, name, states):
        self.pods[name] = {"states": list(states), "i": 0}

    def _state(self, name):
        p = self.pods[name]
        return p["states"][min(p["i"], len(p["states"]) - 1)]

    # BatchV1Api
    def create_namespaced_job(self, body, namespace):
        name = body.metadata.name
        if name in self.jobs:
            raise ApiException(status=409, reason="AlreadyExists")
        self.calls.append(("create", name))
        self.jobs[name] = None
        self._add_pod(f"{name}-new", self.new_pod)

    def delete_namespaced_job(self, name, namespace, body):
        if self.jobs.get(name, "gone") is not None:
            raise ApiException(status=404, reason="NotFound")
        self.calls.append(("delete", name))
        self.jobs[name] = 2

    def read_namespaced_job(self, name, namespace):
        if name not in self.jobs:
            raise ApiException(status=404, reason="NotFound")
        left = self.jobs[name]
        if left is not None:  # foreground delete in progress
            if left == 0:
                del self.jobs[name]
                self.pods = {p: s for p, s in self.pods.items() if not p.startswith(name + "-")}
                raise ApiException(status=404, reason="NotFound")
            self.jobs[name] = left - 1
        return NS(metadata=NS(name=name))

    # CoreV1Api
    def list_namespaced_pod(self, namespace, label_selector):
        job = label_selector.removeprefix("job-name=")
        items = []
        for name, p in self.pods.items():
            if name.startswith(job + "-"):
                items.append(NS(metadata=NS(name=name), status=NS(phase=self._state(name)[0])))
                p["i"] += 1  # time passes
        return NS(items=items)

    def read_namespaced_pod_log(self, name, namespace, **kw):
        phase, logs = self._state(name)
        if phase == "Pending":
            raise ApiException(status=400, reason="container is waiting to start")
        return logs


@pytest.fixture
def cluster(monkeypatch):
    monkeypatch.setattr(cli, "POLL", 0)
    monkeypatch.setattr(config, "GITHUB_APP_ID", None)  # no token minting in tests

    def install(c):
        monkeypatch.setattr(sandbox, "_batch_api", lambda: c)
        monkeypatch.setattr(sandbox, "_core_api", lambda: c)
        return c
    return install


def test_create_replaces_the_old_job_and_waits_for_the_runner(cluster, capsys):
    c = cluster(FakeCluster(old_job=True))
    assert cli.main(["create", "s1", "--repo", "https://github.com/o/r"]) == 0
    assert c.calls == [("delete", "otto-s1"), ("create", "otto-s1")]
    assert list(c.pods) == ["otto-s1-new"]
    assert c._state("otto-s1-new")[1] == LISTENING
    assert "listening" in capsys.readouterr().out


def test_create_without_an_old_job(cluster):
    c = cluster(FakeCluster())
    assert cli.main(["create", "s1", "--repo", "https://github.com/o/r"]) == 0
    assert c.calls == [("create", "otto-s1")]


def test_create_fails_when_the_pod_dies(cluster, capsys):
    cluster(FakeCluster(new_pod=[("Pending", None), ("Failed", "fatal: repository not found")]))
    assert cli.main(["create", "s1", "--repo", "https://github.com/o/r"]) == 1
    err = capsys.readouterr().err
    assert "Failed" in err and "repository not found" in err


def test_create_times_out(cluster, monkeypatch, capsys):
    cluster(FakeCluster(new_pod=[("Running", "still cloning")]))
    monkeypatch.setattr(cli, "READY_TIMEOUT", 0.05)
    assert cli.main(["create", "s1", "--repo", "https://github.com/o/r"]) == 1
    assert "Listening for actions" in capsys.readouterr().err


def test_destroy_waits_until_the_job_is_gone(cluster):
    c = cluster(FakeCluster(old_job=True))
    assert cli.main(["destroy", "s1"]) == 0
    assert c.calls == [("delete", "otto-s1")]
    assert c.jobs == {} and c.pods == {}


def test_destroy_missing_job_is_fine(cluster, capsys):
    cluster(FakeCluster())
    assert cli.main(["destroy", "s1"]) == 0
    assert "no job" in capsys.readouterr().out


def test_bad_session_id(cluster, capsys):
    cluster(FakeCluster())
    assert cli.main(["destroy", "S_1"]) == 1
    assert "session id" in capsys.readouterr().err
