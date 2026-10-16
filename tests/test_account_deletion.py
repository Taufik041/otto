"""Deleting an account (DELETE /me, python -m scripts.accounts delete): what the Privacy Policy
promises. It is deactivated at once (signed out everywhere, its sandboxes stopped, GitHub dropped,
its email and GitHub login free to sign up again) and its data is purged within 30 days."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import func, select
from starlette.websockets import WebSocketDisconnect

from gateway import app as gateway_app
from gateway import auth, live
from scripts import accounts as accounts_cli
from shared import access, email
from shared.accounts import PURGE_AFTER, deactivate, purge_deleted
from shared.db import get_db
from shared.events import append_event
from shared.models import (
    AccessRequest,
    EmailVerification,
    Installation,
    PasswordReset,
    RefreshToken,
    Session,
    SessionEvent,
    Usage,
    User,
    utcnow,
)
from shared.sessions import create_session, get_session, set_status
from tests.conftest import ORIGIN
from tests.fakes import PASSWORD, connect_github, make_user, sign_out, signup
from tests.test_github_signin import callback, start
from tests.test_usage import spend

REPO = "Taufik041/otto_test"
EMAIL = "taufik@example.com"
CONFIRM = {"confirm": "DELETE", "password": PASSWORD}


def delete_me(client, body=CONFIRM):
    return client.request("DELETE", "/me", json=body)


def count(model, **where) -> int:
    with get_db() as s:
        q = select(func.count()).select_from(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return s.exec(q).one()


def user(uid) -> User | None:
    with get_db() as s:
        return s.get(User, uid)


def busy_account(client, fake_github) -> dict:
    """An account with GitHub, an agent session with a live sandbox, a plain chat, usage, an
    access request, a reset link and a second signed-in device. Returns ids."""
    me = signup(client, email=EMAIL)
    with get_db() as s:
        row = s.get(User, me["id"])
        row.github_id, row.github_login = 101, "Taufik041"
        s.add(row)
    connect_github(fake_github, me["id"], 555, [REPO])
    access.request_access(github_login="Taufik041", note="please")
    access.request_access(email=EMAIL)
    agent = client.post("/sessions", json={"message": "fix", "repo": REPO}).json()["id"]
    chat = client.post("/sessions", json={"message": "hi"}).json()["id"]
    set_status(chat, "done")
    append_event(agent, "note", {})
    spend(me["id"], agent, 100)
    client.post("/auth/forgot", json={"email": EMAIL})
    other_device = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
    return {"id": me["id"], "agent": agent, "chat": chat, "other_device": other_device}


# --- confirming --------------------------------------------------------------------------------

@pytest.mark.parametrize("body", [{}, {"confirm": "delete", "password": PASSWORD}, {"confirm": "yes"}])
def test_it_needs_DELETE_typed(client, body):
    me = signup(client)
    assert delete_me(client, body).status_code == 422
    assert user(me["id"]).deleted_at is None


@pytest.mark.parametrize("password", [None, "", "wrong wrong"])
def test_an_account_with_a_password_must_enter_it(client, password):
    me = signup(client)
    r = delete_me(client, {"confirm": "DELETE", "password": password})
    assert r.status_code == 403 and "password" in r.json()["detail"]
    assert user(me["id"]).deleted_at is None


def test_an_account_without_a_password_just_types_DELETE(client, fake_github):
    fake_github.add_user("c1", gid=101, login="Taufik041")
    callback(client, code="c1", state=start(client))
    uid = client.get("/me").json()["id"]
    assert delete_me(client, {"confirm": "DELETE"}).status_code == 200
    assert user(uid).deleted_at is not None


def test_it_needs_a_login(client):
    assert delete_me(client).status_code == 401


# --- what happens at once ------------------------------------------------------------------------

def test_deleting_deactivates_the_account_at_once(client, env, fake_github):
    _ch, orch, runners = env
    other = signup(client, email="other@example.com")["id"]
    create_session("keep000001", task="theirs", repo=None, model="m", user_id=other)
    sign_out(client)
    ids = busy_account(client, fake_github)
    runners.alive.add(ids["agent"])
    with get_db() as s:
        s.add(EmailVerification(token_hash="h", user_id=ids["id"], email=EMAIL, expires_at=utcnow() + timedelta(days=1)))
    orch.calls.clear()

    r = delete_me(client)

    assert r.status_code == 200 and r.json() == {"ok": True}
    row = user(ids["id"])
    # marked deleted; the email and GitHub login are free, and only hashes for the purge are left
    assert row.deleted_at is not None and row.purged_at is None
    assert (row.email, row.github_id, row.github_login, row.password_hash, row.avatar_url) == (None,) * 5
    assert row.name == "Deleted account" and len(row.purge_keys) == 2
    assert EMAIL not in str(row.purge_keys) and "taufik041" not in str(row.purge_keys).lower()
    # every device signed out: refresh tokens revoked, access tokens void, the cookie dropped
    with get_db() as s:
        refresh = s.exec(select(RefreshToken).where(RefreshToken.user_id == ids["id"])).all()
    assert refresh and all(t.revoked_reason == "deleted" for t in refresh)
    assert auth.REFRESH_COOKIE not in client.cookies
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": f"Bearer {ids['other_device']}"}).status_code == 401
    # its running session stopped and its sandbox destroyed (the plain chat has none)
    assert get_session(ids["agent"]).status == "stopped"
    assert orch.calls == [("destroy", ids["agent"])]
    # its GitHub installations and emailed links are gone at once
    assert count(Installation, user_id=ids["id"]) == 0
    assert count(PasswordReset, user_id=ids["id"]) == 0 and count(EmailVerification, user_id=ids["id"]) == 0
    # the rest waits for the purge; someone else's things are untouched
    assert count(Session, user_id=ids["id"]) == 2 and count(AccessRequest) == 2
    assert user(other).deleted_at is None and count(Session, user_id=other) == 1


def test_the_goodbye_email_goes_to_the_address_it_had(client, fake_github, resend):
    busy_account(client, fake_github)
    resend.sent.clear()
    delete_me(client)
    [msg] = resend.sent
    assert msg["to"] == [EMAIL] and msg["subject"] == "Your Otto account has been deleted"
    for part in (msg["text"], msg["html"]):
        assert "30 days" in part and "stay there" in part and "support@taufi.dev" in part
        # the App stays installed on GitHub: a link to uninstall it there
        assert "https://github.com/settings/installations/555" in part


def test_in_development_the_email_is_logged(client, capsys):
    signup(client)
    capsys.readouterr()
    delete_me(client)
    out = capsys.readouterr().out
    assert "not sent" in out and "Your Otto account has been deleted" in out and EMAIL in out


def test_a_failed_email_doesnt_stop_the_deletion(client, monkeypatch):
    me = signup(client)

    def fails(*a):
        raise email.EmailError("Resend refused the email (500)")

    monkeypatch.setattr(email, "send", fails)
    assert delete_me(client).status_code == 200 and user(me["id"]).deleted_at is not None


def test_github_lists_where_to_uninstall_the_app(client, fake_github):
    me = signup(client)
    connect_github(fake_github, me["id"], 555, [REPO], account="Taufik041")
    connect_github(fake_github, me["id"], 777, ["acme/app"], account="acme")
    with get_db() as s:
        row = s.get(User, me["id"])
        row.github_login = "Taufik041"
        s.add(row)
    assert {i["id"]: i["uninstall_url"] for i in client.get("/github").json()["installations"]} == {
        555: "https://github.com/settings/installations/555",
        777: "https://github.com/organizations/acme/settings/installations/777"}


# --- a deleted account can't sign in ---------------------------------------------------------------

def test_a_deleted_account_cant_sign_in(client, fake_github):
    ids = busy_account(client, fake_github)
    cookie = client.cookies.get(auth.REFRESH_COOKIE)
    delete_me(client)
    sign_out(client)

    assert client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 401
    client.cookies.set(auth.REFRESH_COOKIE, cookie, path=auth.REFRESH_PATH)
    assert client.post("/auth/refresh").status_code == 401
    assert client.post("/auth/email-status", json={"email": EMAIL}).json()["exists"] is False
    client.cookies.clear()
    # GitHub sign-in makes a new account: the deleted one is never signed in again
    fake_github.add_user("c1", gid=101, login="Taufik041")
    callback(client, code="c1", state=start(client))
    assert client.get("/me").json()["id"] != ids["id"]


def test_a_token_of_a_deleted_account_signs_nobody_in(client):
    from gateway import tokens

    make_user("gone", deleted_at=utcnow())
    assert auth.user_from_access(tokens.access_token(user("gone"))) is None
    assert tokens.refresh_user(tokens.issue_refresh("gone")) == "gone"  # the token is live...
    client.cookies.set(auth.REFRESH_COOKIE, tokens.issue_refresh("gone"), path=auth.REFRESH_PATH)
    assert client.post("/auth/refresh").status_code == 401  # ...but the account isn't


# --- signing up again ------------------------------------------------------------------------------

def test_the_same_email_can_sign_up_again_at_once(client):
    old = signup(client)["id"]
    delete_me(client)
    new = signup(client)["id"]
    assert new != old and client.get("/me").json()["email"] == EMAIL


def test_the_same_github_login_can_sign_up_again_at_once(client, fake_github):
    fake_github.add_user("c1", gid=101, login="Taufik041", emails=[(EMAIL, True)])
    callback(client, code="c1", state=start(client))
    old = client.get("/me").json()["id"]
    delete_me(client, {"confirm": "DELETE"})
    sign_out(client)

    fake_github.add_user("c2", gid=101, login="Taufik041", emails=[(EMAIL, True)])
    callback(client, code="c2", state=start(client))

    me = client.get("/me").json()
    assert me["id"] != old and (me["github_login"], me["email"]) == ("Taufik041", EMAIL)


def test_the_purge_leaves_the_new_account_alone(client):
    old = signup(client)["id"]
    delete_me(client)
    new = signup(client)["id"]
    client.post("/sessions", json={"message": "hi"})

    assert purge_deleted(now=utcnow() + timedelta(days=30)) == [old]
    assert user(new).email == EMAIL and count(Session, user_id=new) == 1


# --- the purge -------------------------------------------------------------------------------------

def test_the_purge_deletes_the_data_and_anonymizes_the_rest(client, fake_github):
    other = signup(client, email="other@example.com")["id"]
    spend(other, None, 10)
    access.request_access(github_login="someone-else")
    sign_out(client)
    ids = busy_account(client, fake_github)
    delete_me(client)

    assert purge_deleted(now=utcnow() + timedelta(days=30)) == [ids["id"]]

    for model, where in [(Session, {"user_id": ids["id"]}), (SessionEvent, {"session_id": ids["agent"]}),
                         (Usage, {"user_id": ids["id"]}), (Usage, {"session_id": ids["agent"]}),
                         (RefreshToken, {"user_id": ids["id"]}), (PasswordReset, {"user_id": ids["id"]}),
                         (Installation, {"user_id": ids["id"]})]:
        assert count(model, **where) == 0, model
    with get_db() as s:
        assert [r.github_login for r in s.exec(select(AccessRequest)).all()] == ["someone-else"]
    # what is left is an anonymous row: an id, and when it was made, deleted and purged
    row = user(ids["id"])
    assert row.purged_at is not None and row.purge_keys is None
    assert (row.email, row.github_id, row.github_login, row.name) == (None, None, None, "Deleted account")
    # someone else's things stay
    assert count(Usage, user_id=other) == 1 and user(other).deleted_at is None


def test_the_purge_runs_within_30_days_counting_the_backups(client):
    """Purged by day PURGE_AFTER + 1 (the sweep is daily), and the nightly backups holding it are
    gone 14 days later (BACKUP_KEEP_DAYS): within the 30 days."""
    assert PURGE_AFTER + timedelta(days=1) + timedelta(days=14) <= timedelta(days=30)
    uid = signup(client)["id"]
    delete_me(client)
    deleted = user(uid).deleted_at

    assert purge_deleted(now=utcnow()) == []
    assert purge_deleted(now=deleted + PURGE_AFTER - timedelta(minutes=1)) == []
    assert count(Session, user_id=uid) == 0 and user(uid).purged_at is None
    assert purge_deleted(now=deleted + PURGE_AFTER + timedelta(minutes=1)) == [uid]


def test_the_purge_is_idempotent(client):
    uid = signup(client)["id"]
    client.post("/sessions", json={"message": "hi"})
    delete_me(client)
    later = utcnow() + timedelta(days=30)
    assert purge_deleted(now=later) == [uid]
    purged_at = user(uid).purged_at
    assert purge_deleted(now=later) == [] and purge_deleted(now=later + timedelta(days=1)) == []
    assert user(uid).purged_at == purged_at and count(Session, user_id=uid) == 0


def test_the_purge_skips_live_accounts(client):
    uid = signup(client)["id"]
    client.post("/sessions", json={"message": "hi"})
    assert purge_deleted(now=utcnow() + timedelta(days=365)) == []
    assert count(Session, user_id=uid) == 1


def test_the_gateway_purges_when_it_starts_and_daily(env, monkeypatch):
    make_user("gone", deleted_at=utcnow() - timedelta(days=30))
    create_session("gone000001", task="t", repo=None, model="m", user_id="gone")
    started = []
    monkeypatch.setattr(gateway_app, "daily", lambda fn: started.append(fn.__name__) or _never())
    with TestClient(gateway_app.app):
        assert count(Session, user_id="gone") == 0 and user("gone").purged_at is not None
    assert "_purge_deleted" in started and "_prune_unconfirmed" in started


async def _never():
    import asyncio

    await asyncio.Event().wait()


# --- the support path: python -m scripts.accounts delete -----------------------------------------

@pytest.mark.parametrize("who", [EMAIL, "Taufik@Example.com", "Taufik041", "@taufik041"])
def test_the_cli_deletes_by_email_or_github_login(client, env, fake_github, who, capsys):
    _ch, orch, runners = env
    ids = busy_account(client, fake_github)
    runners.alive.add(ids["agent"])
    orch.calls.clear()
    capsys.readouterr()

    assert accounts_cli.main(["delete", who]) == 0

    row = user(ids["id"])
    assert row.deleted_at is not None and row.email is None and row.github_login is None
    assert get_session(ids["agent"]).status == "stopped" and orch.calls == [("destroy", ids["agent"])]
    assert count(Installation, user_id=ids["id"]) == 0
    assert client.get("/me").status_code == 401
    out = capsys.readouterr().out
    assert f"deleted account {ids['id']}" in out and "Your Otto account has been deleted" in out  # the email


def test_the_cli_says_when_there_is_no_such_account(client, capsys):
    assert accounts_cli.main(["delete", "nobody@example.com"]) == 1
    assert "no account" in capsys.readouterr().err
    signup(client)
    delete_me(client)
    assert accounts_cli.main(["delete", EMAIL]) == 1  # deleted already: its email is no one's


# --- open tabs: WebSockets ---------------------------------------------------------------------

def watch(client, sid):
    ticket = client.post(f"/sessions/{sid}/ws-ticket").json()["ticket"]
    return client.websocket_connect(f"/sessions/{sid}/ws?ticket={ticket}", headers={"origin": ORIGIN})


def until(ws, wanted) -> dict:
    """The first message for which wanted(message) holds."""
    while not wanted(m := ws.receive_json()):
        pass
    return m


def closed_code(ws, most=40) -> int:
    """Read what is left (the replayed events, pings) until the gateway closes the socket; with
    fast heartbeats, a socket left open fails after `most` messages instead of hanging."""
    with pytest.raises(WebSocketDisconnect) as e:
        for _ in range(most):
            ws.receive_json()
    return e.value.code


def test_deleting_closes_every_open_websocket_of_the_account(client, monkeypatch):
    monkeypatch.setattr(gateway_app, "PING_INTERVAL", 0.05)  # fast, so a socket left open fails fast
    monkeypatch.setattr(gateway_app, "_account_gone", lambda uid: False)  # at once, not at a heartbeat
    other = signup(client, email="other@example.com")
    theirs = client.post("/sessions", json={"message": "theirs"}).json()["id"]
    their_token = client.headers["Authorization"]
    sign_out(client)
    me = signup(client)
    chats = [client.post("/sessions", json={"message": m}).json()["id"] for m in ("one", "two")]
    mine_token = client.headers["Authorization"]

    with watch(client, chats[0]) as tab1, watch(client, chats[1]) as tab2:
        client.headers["Authorization"] = their_token
        with watch(client, theirs) as their_tab:
            until(tab1, lambda m: m["type"] == "session.created")
            until(their_tab, lambda m: m["type"] == "session.created")
            client.headers["Authorization"] = mine_token

            assert delete_me(client).status_code == 200

            assert closed_code(tab1) == 4401 and closed_code(tab2) == 4401
            # someone else's tab streams on
            seq = append_event(theirs, "note", {})
            client.portal.call(live.publish, theirs, seq)
            assert until(their_tab, lambda m: m.get("seq") == seq)["type"] == "note"
    assert me["id"] not in gateway_app._sockets and other["id"] not in gateway_app._sockets


def test_deleted_from_another_process_the_next_heartbeat_closes_it(client, monkeypatch):
    """The support CLI runs in its own process: it can't reach the gateway's sockets, so each
    heartbeat checks the account is still there."""
    monkeypatch.setattr(gateway_app, "PING_INTERVAL", 0.05)
    me = signup(client)
    chat = client.post("/sessions", json={"message": "hi"}).json()["id"]
    with watch(client, chat) as tab:
        until(tab, lambda m: m == {"type": "ping"})  # the account is there: heartbeats go out
        deactivate(me["id"])  # as the CLI would, without _end_sockets
        assert closed_code(tab) == 4401
