"""The user opens Otto's proposed pull request (POST /sessions/{id}/pr), or declines it. The gateway
opens it through the GitHub API with the installation's token: no sandbox, no model."""
import pytest

from shared.events import append_event, load_events
from shared.sessions import get_session, set_status
from tests.fakes import connect_github, log_in_as, make_user, signup

REPO = "Taufik041/otto_test"
PROPOSAL = {"title": "Fix the bulk discount threshold", "body": "Root cause, fix, tests.", "head": None,
            "base": "main", "additions": 1, "deletions": 1, "files": 1, "tests": {"passed": 9, "failed": 0, "text": "9 passed"}}


@pytest.fixture
def client(client, fake_github):
    client.user_id = signup(client)["id"]
    connect_github(fake_github, client.user_id, 555, [REPO])
    return client


def chat(client, status="done", propose=True):
    """A repo chat whose turn ended with a proposal (as the brain's finish leaves it)."""
    sid = client.post("/sessions", json={"message": "fix the tests", "repo": REPO}).json()["id"]
    set_status(sid, status)
    if propose:
        append_event(sid, "pr.proposed", {**PROPOSAL, "head": f"otto/{sid}"})
    return sid


def types(sid):
    return [e.type for e in load_events(sid)]


def opened(sid):
    return [e.payload for e in load_events(sid) if e.type == "pr.opened"]


def pull_posts(gh):
    return [p for m, p in gh.calls if m == "POST" and p.endswith("/pulls")]


def test_create_opens_the_proposed_pr_through_github(client, env, fake_github):
    sid = chat(client)

    r = client.post(f"/sessions/{sid}/pr")

    assert r.status_code == 201, r.text
    url = f"https://github.com/{REPO}/pull/1"
    assert r.json() == {"number": 1, "url": url, "title": PROPOSAL["title"], "created": True}
    [pr] = fake_github.pulls[REPO]
    assert (pr["title"], pr["body"], pr["head"], pr["base"]) == (PROPOSAL["title"], PROPOSAL["body"], f"otto/{sid}", "main")
    assert fake_github.minted and fake_github.minted[-1][0] == 555  # the installation's token
    assert opened(sid) == [{"number": 1, "html_url": url}]
    assert get_session(sid).pr_url == url
    assert env[1].calls == [("create", sid, "https://github.com/Taufik041/otto_test", 555)]  # no other sandbox work


def test_create_takes_a_title(client, env, fake_github):
    sid = chat(client)
    assert client.post(f"/sessions/{sid}/pr", json={"title": "My title"}).json()["title"] == "My title"
    assert fake_github.pulls[REPO][0]["title"] == "My title"


def test_create_is_idempotent(client, env, fake_github):
    sid = chat(client)
    first = client.post(f"/sessions/{sid}/pr").json()

    again = client.post(f"/sessions/{sid}/pr")  # a double click, another tab

    assert again.status_code == 200 and again.json() == {**first, "created": False}
    assert len(pull_posts(fake_github)) == 1 and len(opened(sid)) == 1


def test_a_pr_github_already_has_for_the_branch_is_returned_not_duplicated(client, env, fake_github):
    sid = chat(client)
    fake_github.pulls[REPO] = [{"number": 7, "html_url": f"https://github.com/{REPO}/pull/7", "title": "Earlier",
                                "body": "", "head": f"otto/{sid}", "base": "main", "state": "open"}]

    r = client.post(f"/sessions/{sid}/pr")

    assert r.status_code == 201 and r.json()["number"] == 7
    assert len(fake_github.pulls[REPO]) == 1
    assert opened(sid) == [{"number": 7, "html_url": f"https://github.com/{REPO}/pull/7"}]


@pytest.mark.parametrize("status", ["provisioning", "queued", "running"])
def test_create_while_otto_works_is_409(client, env, fake_github, status):
    sid = chat(client, status=status)
    r = client.post(f"/sessions/{sid}/pr")
    assert r.status_code == 409 and "working" in r.json()["detail"]
    assert pull_posts(fake_github) == []


def test_create_without_a_proposal_is_409(client, env, fake_github):
    sid = chat(client, propose=False)
    r = client.post(f"/sessions/{sid}/pr")
    assert r.status_code == 409 and "nothing to open" in r.json()["detail"].lower()
    assert pull_posts(fake_github) == []


def test_decline_then_create_later(client, env, fake_github):
    sid = chat(client)

    r = client.post(f"/sessions/{sid}/pr/decline")

    assert r.status_code == 200 and types(sid)[-1] == "pr.declined"
    assert pull_posts(fake_github) == [] and get_session(sid).pr_url is None
    assert client.post(f"/sessions/{sid}/pr").status_code == 201  # the proposal still stands


def test_decline_without_a_proposal_is_409(client, env):
    sid = chat(client, propose=False)
    assert client.post(f"/sessions/{sid}/pr/decline").status_code == 409


def test_a_github_failure_is_a_clean_502(client, env, fake_github):
    sid = chat(client)
    fake_github.pull_error = (422, {"message": "Validation Failed", "errors": [
        {"resource": "PullRequest", "code": "custom", "message": "No commits between main and otto/x"}]})

    r = client.post(f"/sessions/{sid}/pr")

    assert r.status_code == 502
    assert r.json()["detail"] == "GitHub didn't open the pull request: Validation Failed; No commits between main and otto/x"
    assert "ghs_" not in r.text
    assert opened(sid) == [] and get_session(sid).pr_url is None


def test_github_unreachable_is_a_clean_502(client, env, fake_github, monkeypatch):
    import requests
    from gateway import github_app

    sid = chat(client)
    token = github_app.installation_token(555)

    def down(method, url, **kw):
        if url.endswith("/pulls"):
            raise requests.ConnectionError(f"connection refused (Authorization: Bearer {token})")
        return fake_github(method, url, **kw)

    monkeypatch.setattr(github_app, "request", down)
    r = client.post(f"/sessions/{sid}/pr")
    assert r.status_code == 502 and token not in r.text and "GitHub didn't open the pull request" in r.text


def test_only_the_owner_can_open_or_decline(client, env):
    sid = chat(client)
    make_user("u2", email="other@example.com")
    log_in_as(client, "u2")
    assert client.post(f"/sessions/{sid}/pr").status_code == 404
    assert client.post(f"/sessions/{sid}/pr/decline").status_code == 404
