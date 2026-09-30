"""Connecting GitHub installations to a user, and listing the user's repos."""
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlmodel import select

from gateway import auth, github_app
from shared import config
from shared.db import get_db
from shared.models import Installation, User
from tests.fakes import log_in_as, repo, signup
from tests.test_github_signin import callback, start

INST = 555


@pytest.fixture
def clock(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(github_app, "now", lambda: t[0])
    return t


@pytest.fixture
def me(client):
    return signup(client, email="taufik@example.com")


def install(client, fake_github, iid=INST, code="c1", setup_action="install", state=None):
    """Go through /github/install and come back as GitHub would."""
    return callback(client, code=code, installation_id=iid, setup_action=setup_action,
                    state=state or start(client, "/github/install"))


def links() -> list[tuple]:
    with get_db() as s:
        return [(i.id, i.user_id, i.account_login) for i in s.exec(select(Installation)).all()]


# --- installing -----------------------------------------------------------------------

def test_install_redirects_to_the_apps_install_page_with_a_state_for_this_user(client, fake_github, me):
    r = client.get("/github/install", follow_redirects=False)
    url = urlsplit(r.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://github.com/apps/ottoci/installations/new"
    claims = auth.verify(parse_qs(url.query)["state"][0], "github-state")
    assert (claims["flow"], claims["uid"]) == ("install", me["id"])


def test_install_needs_a_login_and_the_app_configured(client, fake_github, monkeypatch):
    assert client.get("/github/install", follow_redirects=False).status_code == 401
    signup(client)
    monkeypatch.setattr(config, "GITHUB_APP_SLUG", None)
    assert client.get("/github/install", follow_redirects=False).status_code == 503


def test_a_valid_installation_is_saved(client, fake_github, me):
    token = fake_github.add_user("c1", gid=101, login="Taufik041")
    fake_github.add_installation(INST, "Taufik041", users=[token])

    r = install(client, fake_github)

    assert r.status_code in (302, 307)
    assert r.headers["location"] == "http://localhost:5173/settings/github"
    assert links() == [(INST, me["id"], "Taufik041")]
    after = client.get("/me").json()
    assert (after["github_login"], after["avatar_url"]) == ("Taufik041", "https://avatars.githubusercontent.com/u/101")
    assert client.get("/github").json() == {
        "connected": True, "login": "Taufik041", "avatar_url": "https://avatars.githubusercontent.com/u/101",
        "installations": [{"id": INST, "account_login": "Taufik041"}]}


def test_an_installation_that_isnt_the_users_is_refused(client, fake_github, me):
    fake_github.add_user("c1", gid=101, login="Taufik041")
    someone = fake_github.add_user("c9", gid=999, login="someone")
    fake_github.add_installation(INST, "someone", users=[someone])

    r = install(client, fake_github)

    assert r.status_code == 403
    assert links() == []
    assert "/user/installations" in fake_github.paths("GET")


def test_the_installation_check_follows_pagination(client, fake_github, me):
    token = fake_github.add_user("c1", gid=101, login="Taufik041")
    for iid in (1, 2, 3):
        fake_github.add_installation(iid, f"org{iid}", users=[token])
    fake_github.page_size = 2
    assert install(client, fake_github, iid=3).status_code in (302, 307)
    assert links() == [(3, me["id"], "org3")]


@pytest.mark.parametrize("state", ["missing", "garbage", "signin"])
def test_an_install_callback_without_an_install_state_is_400(client, fake_github, me, state):
    token = fake_github.add_user("c1", gid=101, login="Taufik041")
    fake_github.add_installation(INST, "Taufik041", users=[token])
    params = {"code": "c1", "installation_id": INST, "setup_action": "install"}
    if state == "garbage":
        params["state"] = "garbage"
    elif state == "signin":
        params["state"] = start(client)  # a sign-in state can't confirm an installation
    assert callback(client, **params).status_code == 400
    assert links() == []


def test_an_install_state_cant_be_used_to_sign_in(client, fake_github, me):
    fake_github.add_user("c1", gid=101, login="Taufik041")
    assert callback(client, code="c1", state=start(client, "/github/install")).status_code == 400


def test_an_installation_linked_to_another_otto_user_is_409(client, fake_github, me):
    token = fake_github.add_user("c1", gid=101, login="Taufik041")
    fake_github.add_installation(INST, "some-org", users=[token])
    install(client, fake_github)
    log_in_as(client, signup(client, email="b@example.com")["id"])
    fake_github.add_user("c2", gid=202, login="bee")
    fake_github.user_installations[fake_github.codes["c2"]] = [INST]
    assert install(client, fake_github, code="c2").status_code == 409
    assert links() == [(INST, me["id"], "some-org")]


def test_installing_links_github_to_an_email_account_unless_its_taken(client, fake_github, me):
    fake_github.add_user("c0", gid=101, login="Taufik041")
    callback(client, code="c0", state=start(client))  # links 101 to me
    client.cookies.clear()
    other = signup(client, email="other@example.com")
    token = fake_github.add_user("c1", gid=101, login="Taufik041")
    fake_github.add_installation(INST, "Taufik041", users=[token])

    assert install(client, fake_github).status_code in (302, 307)

    assert links() == [(INST, other["id"], "Taufik041")]
    with get_db() as s:
        assert s.get(User, other["id"]).github_id is None  # 101 stays with its account


def test_setup_action_update_only_refreshes_the_caches(client, fake_github, me, clock):
    token = fake_github.add_user("c1", gid=101, login="Taufik041")
    fake_github.add_installation(INST, "Taufik041", repos=["Taufik041/otto_test"], users=[token])
    install(client, fake_github)
    assert len(client.get("/repos").json()) == 1
    fake_github.repos[INST].append(repo("Taufik041/portfolio"))  # the user picked another repo on GitHub
    state = start(client, "/github/install")
    before = list(fake_github.calls)

    r = install(client, fake_github, code="c2", setup_action="update", state=state)

    assert r.headers["location"] == "http://localhost:5173/settings/github"
    assert fake_github.calls == before  # no code exchange, no checks
    assert len(client.get("/repos").json()) == 2  # within the 60s, but the cache was dropped
    assert len(fake_github.minted) == 2  # and so was the installation token


def test_setup_action_update_for_an_unknown_installation_is_checked_like_an_install(client, fake_github, me):
    someone = fake_github.add_user("c9", gid=999, login="someone")
    fake_github.add_user("c1", gid=101, login="Taufik041")
    fake_github.add_installation(INST, "someone", users=[someone])
    assert install(client, fake_github, setup_action="update").status_code == 403
    assert links() == []


# --- GET /github, DELETE /github/installations/{id} ---------------------------------------

def test_github_when_not_connected(client, me):
    assert client.get("/github").json() == {"connected": False, "login": None, "avatar_url": None,
                                            "installations": []}


def test_unlinking_an_installation(client, fake_github, me):
    token = fake_github.add_user("c1", gid=101, login="Taufik041")
    fake_github.add_installation(INST, "Taufik041", repos=["Taufik041/otto_test"], users=[token])
    fake_github.add_installation(777, "some-org", repos=["some-org/api"], users=[token])
    install(client, fake_github)
    install(client, fake_github, iid=777)
    assert len(client.get("/repos").json()) == 2

    r = client.delete(f"/github/installations/{INST}")
    assert r.status_code == 200
    assert r.json()["uninstall_url"] == f"https://github.com/settings/installations/{INST}"
    assert client.delete("/github/installations/777").json()["uninstall_url"] == \
        "https://github.com/organizations/some-org/settings/installations/777"
    assert links() == [] and client.get("/repos").json() == []
    assert client.get("/github").json()["connected"] is False


def test_unlinking_someone_elses_installation_is_404(client, fake_github, me):
    token = fake_github.add_user("c1", gid=101, login="Taufik041")
    fake_github.add_installation(INST, "Taufik041", users=[token])
    install(client, fake_github)
    log_in_as(client, signup(client, email="b@example.com")["id"])
    assert client.delete(f"/github/installations/{INST}").status_code == 404
    assert len(links()) == 1


# --- GET /repos ----------------------------------------------------------------------------

@pytest.fixture
def connected(client, fake_github, me):
    """me, with two installations: my account's and an org's."""
    token = fake_github.add_user("c1", gid=101, login="Taufik041")
    fake_github.add_installation(INST, "Taufik041", users=[token], repos=[
        repo("Taufik041/otto_test", updated_at="2026-09-29T10:00:00Z"),
        repo("Taufik041/petal", updated_at="2026-09-20T10:00:00Z", default_branch="trunk"),
        repo("Taufik041/portfolio", private=False, updated_at="2026-09-27T10:00:00Z"),
    ])
    fake_github.add_installation(777, "some-org", users=[token], repos=[
        repo("some-org/api", updated_at="2026-09-28T10:00:00Z")])
    install(client, fake_github)
    install(client, fake_github, iid=777)
    return fake_github


def test_repos_merges_every_installation_newest_first(client, connected):
    assert client.get("/repos").json() == [
        {"full_name": "Taufik041/otto_test", "private": True, "updated_at": "2026-09-29T10:00:00Z",
         "default_branch": "main", "installation_id": INST},
        {"full_name": "some-org/api", "private": True, "updated_at": "2026-09-28T10:00:00Z",
         "default_branch": "main", "installation_id": 777},
        {"full_name": "Taufik041/portfolio", "private": False, "updated_at": "2026-09-27T10:00:00Z",
         "default_branch": "main", "installation_id": INST},
        {"full_name": "Taufik041/petal", "private": True, "updated_at": "2026-09-20T10:00:00Z",
         "default_branch": "trunk", "installation_id": INST},
    ]


def test_repos_follows_pagination(client, connected):
    connected.page_size = 2
    assert len(client.get("/repos").json()) == 4
    assert connected.paths("GET").count("/installation/repositories") == 3  # 2 pages + 1


def test_repos_are_cached_for_a_minute_and_tokens_for_50(client, connected, clock):
    client.get("/repos")
    calls, minted = len(connected.calls), len(connected.minted)
    assert minted == 2

    clock[0] += 59
    client.get("/repos")
    assert len(connected.calls) == calls  # the cached list

    clock[0] += 2
    client.get("/repos")
    assert len(connected.calls) > calls and len(connected.minted) == minted  # listed again, same tokens

    clock[0] += 50 * 60
    client.get("/repos")
    assert len(connected.minted) == minted + 2  # tokens renewed


def test_each_user_has_their_own_repo_cache(client, connected):
    client.get("/repos")
    log_in_as(client, signup(client, email="b@example.com")["id"])
    assert client.get("/repos").json() == []


def test_an_installation_github_no_longer_knows_is_skipped(client, connected):
    del connected.installations[777]  # uninstalled on GitHub
    assert [r["installation_id"] for r in client.get("/repos").json()] == [INST, INST, INST]


def test_repos_needs_a_login(client):
    assert client.get("/repos").status_code == 401


def test_repo_access_is_case_insensitive_and_says_which_installation(client, connected, me):
    assert github_app.repo_access(me["id"], "taufik041/OTTO_TEST")["full_name"] == "Taufik041/otto_test"
    assert github_app.repo_access(me["id"], "some-org/api")["installation_id"] == 777
    assert github_app.repo_access(me["id"], "Taufik041/nope") is None
