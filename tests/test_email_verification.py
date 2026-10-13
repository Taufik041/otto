"""Confirming an email sign-up's address: the emailed link, what an unconfirmed account may do,
resending, changing the address, take-overs of unconfirmed addresses, and the cleanup."""
import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import select, update

from gateway import app as gateway_app
from shared import config, email
from shared.accounts import UNCONFIRMED_TTL, prune_unconfirmed
from shared.db import get_db
from shared.models import EmailVerification, User, as_utc, utcnow
from tests.fakes import PASSWORD, make_user, sign_out, signup
from tests.test_auth import token_from as reset_token
from tests.test_github_signin import callback, failed, start, users

EMAIL = "taufik@example.com"


def sign_up(client, email=EMAIL, password=PASSWORD, name="Taufik"):
    return client.post("/auth/signup", json={"name": name, "email": email, "password": password})


def links(capsys) -> list[str]:
    """The confirmation tokens emailed since the last call (development logs them)."""
    out = capsys.readouterr().out
    return [l.split("verify-email?token=")[1].split()[0] for l in out.splitlines() if "verify-email?token=" in l]


def log_in(client, email=EMAIL, password=PASSWORD) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return r.json()["user"]


def row(email=EMAIL) -> User | None:
    with get_db() as s:
        return s.exec(select(User).where(User.email == email)).first()


# --- 1. signing up sends the link ------------------------------------------------------------

def test_signup_emails_a_confirmation_link_that_lasts_24_hours(client, capsys):
    capsys.readouterr()
    assert sign_up(client).status_code == 201
    out = capsys.readouterr().out
    assert "Confirm your email for Otto" in out and f"to: {EMAIL}" in out and "24 hours" in out
    with get_db() as s:
        [v] = s.exec(select(EmailVerification)).all()
    assert v.email == EMAIL and timedelta(hours=23, minutes=59) < as_utc(v.expires_at) - utcnow() <= timedelta(hours=24)
    assert row().email_verified is False


def test_signup_goes_through_resend_when_it_has_a_key(client, monkeypatch):
    sent = []
    monkeypatch.setattr(config, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(email, "post", lambda p: sent.append(p) or type("R", (), {"status_code": 200, "text": ""})())
    assert sign_up(client).status_code == 201
    [message] = sent
    assert message["to"] == [EMAIL] and message["subject"] == "Confirm your email for Otto"
    assert f"{config.FRONTEND_URL}/verify-email?token=" in message["text"]


def test_a_failed_send_still_makes_the_account(client, monkeypatch):
    monkeypatch.setattr(config, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(email, "post", lambda p: type("R", (), {"status_code": 500, "text": "down"})())
    assert sign_up(client).status_code == 201 and row() is not None  # "Resend" sends another


def test_signup_without_email_set_up_is_503(client, monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION", True)
    r = sign_up(client)
    assert r.status_code == 503 and r.json()["error"] == "email_unavailable"
    assert row() is None


def test_the_email_reads_well_and_escapes_the_link():
    subject, text_body, html = email.verify_email('https://otto.dev/verify-email?token=a"b')
    assert subject == "Confirm your email for Otto"
    assert "expires in 24 hours" in text_body and "token=a\"b" in text_body
    assert "token=a&quot;b" in html and "Confirm your email" in html


# --- 2. until it's confirmed --------------------------------------------------------------

def test_an_unconfirmed_account_can_log_in_but_not_chat(client, capsys):
    sign_up(client)
    me = log_in(client)
    assert me["email_verified"] is False and client.get("/me").json()["email_verified"] is False
    for r in (client.get("/sessions"), client.post("/sessions", json={"message": "hi"}),
              client.post("/sessions/c1/ws-ticket"), client.get("/sessions/c1")):
        assert r.status_code == 403 and r.json()["error"] == "email_unverified", r.text
    assert EMAIL in client.get("/sessions").json()["detail"]


def test_email_status_still_offers_the_password_step(client):
    sign_up(client)
    assert client.post("/auth/email-status", json={"email": EMAIL}).json() == {"exists": True, "password": True}


def test_the_link_confirms_the_email_and_signs_in(client, capsys):
    capsys.readouterr()
    sign_up(client)
    [token] = links(capsys)

    r = client.post("/auth/verify", json={"token": token})

    assert r.status_code == 200 and r.json()["user"]["email_verified"] is True
    assert "otto_refresh=" in r.headers["set-cookie"]
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    assert client.get("/sessions").status_code == 200


def test_the_link_works_once(client, capsys):
    capsys.readouterr()
    sign_up(client)
    [token] = links(capsys)
    assert client.post("/auth/verify", json={"token": token}).status_code == 200
    r = client.post("/auth/verify", json={"token": token})
    assert r.status_code == 400 and "invalid or has expired" in r.json()["detail"]


def test_an_expired_or_made_up_link_is_400(client, capsys):
    capsys.readouterr()
    sign_up(client)
    [token] = links(capsys)
    with get_db() as s:
        s.exec(update(EmailVerification).values(expires_at=utcnow() - timedelta(seconds=1)))
    assert client.post("/auth/verify", json={"token": token}).status_code == 400
    assert client.post("/auth/verify", json={"token": "nope"}).status_code == 400
    assert row().email_verified is False


def test_confirming_uses_up_the_other_links(client, capsys):
    capsys.readouterr()
    sign_up(client)
    client.post("/auth/verify/resend", json={"email": EMAIL})
    first, second = links(capsys)
    assert client.post("/auth/verify", json={"token": second}).status_code == 200
    assert client.post("/auth/verify", json={"token": first}).status_code == 400


def test_a_github_account_is_confirmed_already(client, fake_github):
    fake_github.add_user("c1", gid=101, login="Taufik041", emails=[(EMAIL, True)])
    callback(client, code="c1", state=start(client))
    assert client.get("/me").json()["email_verified"] is True
    assert client.get("/sessions").status_code == 200


def test_a_github_account_without_an_email_can_chat(client, fake_github):
    fake_github.add_user("c1", gid=101, login="Taufik041")
    callback(client, code="c1", state=start(client))
    assert client.get("/sessions").status_code == 200


# --- resending ----------------------------------------------------------------------------------

def test_resend_from_the_dialog_sends_another_link(client, capsys):
    sign_up(client)
    capsys.readouterr()
    assert client.post("/auth/verify/resend", json={"email": " Taufik@Example.com"}).json() == {"ok": True}
    [token] = links(capsys)
    assert client.post("/auth/verify", json={"token": token}).status_code == 200


def test_resend_is_three_an_hour_per_address(client, capsys):
    sign_up(client)
    for _ in range(3):
        assert client.post("/auth/verify/resend", json={"email": EMAIL}).status_code == 200
    r = client.post("/auth/verify/resend", json={"email": EMAIL})
    assert r.status_code == 429 and "retry-after" in r.headers
    log_in(client)
    assert client.post("/me/email/verify").status_code == 429  # the screen's button shares it
    sign_up(client, email="other@example.com")
    assert client.post("/auth/verify/resend", json={"email": "other@example.com"}).status_code == 200


@pytest.mark.parametrize("confirmed", [True, False])
def test_resend_for_a_confirmed_or_unknown_email_says_the_same_and_sends_nothing(client, capsys, confirmed):
    if confirmed:
        signup(client)
        sign_out(client)
    capsys.readouterr()
    r = client.post("/auth/verify/resend", json={"email": EMAIL})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert links(capsys) == []


def test_resend_from_the_confirm_screen(client, capsys):
    sign_up(client)
    log_in(client)
    capsys.readouterr()
    assert client.post("/me/email/verify").json() == {"ok": True, "email": EMAIL}
    assert len(links(capsys)) == 1


def test_a_confirmed_account_has_nothing_to_resend(client):
    signup(client)
    assert client.post("/me/email/verify").status_code == 400


# --- changing the address -----------------------------------------------------------------------

def test_change_email_moves_the_account_and_voids_the_old_link(client, capsys):
    capsys.readouterr()
    sign_up(client, email="typo@exmaple.com")
    [old] = links(capsys)
    log_in(client, email="typo@exmaple.com")

    r = client.post("/me/email", json={"email": " Taufik@Example.com"})

    assert r.status_code == 200 and (r.json()["email"], r.json()["email_verified"]) == (EMAIL, False)
    [new] = links(capsys)
    assert client.post("/auth/verify", json={"token": old}).status_code == 400
    assert client.post("/auth/verify", json={"token": new}).json()["user"]["email"] == EMAIL


def test_change_email_voids_reset_links_sent_to_the_old_address(client, capsys):
    sign_up(client, email="typo@exmaple.com")
    client.post("/auth/forgot", json={"email": "typo@exmaple.com"})
    token = reset_token(next(l for l in capsys.readouterr().out.splitlines() if "reset-password?token=" in l))
    log_in(client, email="typo@exmaple.com")
    client.post("/me/email", json={"email": EMAIL})
    assert client.post("/auth/reset", json={"token": token, "password": "a brand new password"}).status_code == 400
    assert row().email_verified is False


def test_change_email_to_a_confirmed_accounts_is_409(client):
    signup(client, email="taken@example.com")
    sign_out(client)
    sign_up(client)
    log_in(client)
    assert client.post("/me/email", json={"email": "taken@example.com"}).status_code == 409
    assert row().email == EMAIL


def test_change_email_takes_an_unconfirmed_accounts_address(client):
    sign_up(client, email="taken@example.com", name="Squatter")
    sign_up(client)
    me = log_in(client)
    assert client.post("/me/email", json={"email": "taken@example.com"}).status_code == 200
    assert [(u.id, u.email) for u in users()] == [(me["id"], "taken@example.com")]


def test_a_confirmed_email_cant_be_changed_here(client):
    signup(client)
    assert client.post("/me/email", json={"email": "new@example.com"}).status_code == 400


def test_change_email_follows_the_allowlist(client, monkeypatch):
    sign_up(client)
    log_in(client)
    monkeypatch.setattr(config, "SIGNUP_MODE", "allowlist")
    r = client.post("/me/email", json={"email": "stranger@example.com"})
    assert r.status_code == 403 and r.json()["error"] == "invite_only"


# --- 3. unconfirmed addresses reserve nothing ---------------------------------------------------

def test_signing_up_again_replaces_an_unconfirmed_account(client):
    sign_up(client, password="the squatter's password")
    old = row().id
    assert sign_up(client).status_code == 201
    assert row().id != old and len(users()) == 1
    assert client.post("/auth/login", json={"email": EMAIL, "password": "the squatter's password"}).status_code == 401
    log_in(client)


def test_signing_up_with_a_confirmed_accounts_email_is_still_409(client):
    signup(client)
    sign_out(client)
    assert sign_up(client).status_code == 409


def test_github_email_in_use_only_counts_confirmed_accounts(client, fake_github):
    sign_up(client, email="other@example.com")
    fake_github.add_user("c1", gid=101, login="Taufik041", emails=[(EMAIL, True), ("other@example.com", True)])
    callback(client, code="c1", state=start(client))
    me = client.get("/me").json()
    assert me["github_login"] == "Taufik041" and me["email"] == EMAIL


def test_a_github_sign_up_takes_its_email_from_an_unconfirmed_account(client, fake_github):
    sign_up(client, name="Squatter")
    squatter = row().id
    fake_github.add_user("c1", gid=101, login="Taufik041", emails=[("Taufik@Example.com", True)])

    callback(client, code="c1", state=start(client))

    me = client.get("/me").json()
    assert (me["email"], me["email_verified"], me["github_login"]) == (EMAIL, True, "Taufik041")
    assert [u.id for u in users()] == [me["id"]] and me["id"] != squatter
    with get_db() as s:
        assert s.exec(select(EmailVerification)).all() == []  # its links went with it


def test_a_confirmed_account_still_blocks_a_github_sign_up(client, fake_github):
    signup(client)
    sign_out(client)
    fake_github.add_user("c1", gid=101, login="Taufik041", emails=[(EMAIL, True)])
    failed(callback(client, code="c1", state=start(client)), "github_email_in_use")
    assert len(users()) == 1


# --- 4. accounts from before ----------------------------------------------------------------

def test_the_migration_confirms_existing_accounts_with_a_password_or_github(tmp_path, monkeypatch):
    from alembic import command

    from shared import db as shared_db
    from shared.db import alembic_config, init_db

    url = f"sqlite:///{tmp_path / 'old.db'}"
    monkeypatch.setattr(shared_db, "_engine", None)
    engine = shared_db._make_engine(url)
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0017")
        for uid, mail, pw, gid in [("pw", "pw@example.com", "$argon2id$x", None), ("gh", "gh@example.com", None, 7),
                                   ("ghonly", None, None, 8)]:
            conn.execute(text("INSERT INTO users (id, name, email, password_hash, github_id, daily_token_limit, "
                              "created_at, token_version) VALUES (:id, :id, :mail, :pw, :gid, 1, '2026-01-01', 0)"),
                         {"id": uid, "mail": mail, "pw": pw, "gid": gid})
    engine.dispose()

    init_db(url)

    with shared_db.get_db() as s:
        got = {u.id: u.email_verified for u in s.exec(select(User))}
    assert got == {"pw": True, "gh": True, "ghonly": False}
    shared_db.get_engine().dispose()


# --- 5. a reset link proves the address too -----------------------------------------------------

def test_resetting_the_password_confirms_the_email(client, capsys):
    sign_up(client)
    capsys.readouterr()
    client.post("/auth/forgot", json={"email": EMAIL})
    token = reset_token(next(l for l in capsys.readouterr().out.splitlines() if "reset-password?token=" in l))
    r = client.post("/auth/reset", json={"token": token, "password": "a brand new password"})
    assert r.status_code == 200 and r.json()["user"]["email_verified"] is True
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    assert client.get("/sessions").status_code == 200


def test_reclaiming_an_address_by_reset_signs_the_squatter_out_everywhere(client, capsys):
    sign_up(client, password="the squatter's password")
    squatter = client.post("/auth/login", json={"email": EMAIL, "password": "the squatter's password"})
    access, refresh = squatter.json()["access_token"], client.cookies["otto_refresh"]
    client.cookies.clear()
    capsys.readouterr()
    client.post("/auth/forgot", json={"email": EMAIL})  # the address's real owner
    token = reset_token(next(l for l in capsys.readouterr().out.splitlines() if "reset-password?token=" in l))

    r = client.post("/auth/reset", json={"token": token, "password": "the owner's password"})

    assert r.status_code == 200 and r.json()["user"]["email_verified"] is True
    assert client.get("/me", headers={"Authorization": f"Bearer {access}"}).status_code == 401
    client.cookies.clear()
    client.cookies.set("otto_refresh", refresh, path="/auth")
    assert client.post("/auth/refresh").status_code == 401
    assert client.post("/auth/login", json={"email": EMAIL, "password": "the squatter's password"}).status_code == 401


# --- cleanup ----------------------------------------------------------------------------------

def age(email, days):
    with get_db() as s:
        s.exec(update(User).where(User.email == email).values(created_at=utcnow() - timedelta(days=days)))


def test_unconfirmed_accounts_older_than_a_week_are_deleted(client):
    sign_up(client, email="old@example.com")
    sign_up(client, email="new@example.com")
    signup(client, email="confirmed@example.com")
    make_user("gh", github_id=5)  # GitHub, no email
    for mail in ("old@example.com", "confirmed@example.com"):
        age(mail, 8)
    with get_db() as s:
        s.exec(update(User).where(User.id == "gh").values(created_at=utcnow() - timedelta(days=30)))
    old = row("old@example.com").id

    assert prune_unconfirmed() == [old]
    assert sorted(u.email or u.id for u in users()) == ["confirmed@example.com", "gh", "new@example.com"]


def test_a_week_is_the_line(client):
    sign_up(client)
    age(EMAIL, 0)
    assert prune_unconfirmed(now=utcnow() + UNCONFIRMED_TTL - timedelta(minutes=1)) == []
    assert len(prune_unconfirmed(now=utcnow() + UNCONFIRMED_TTL + timedelta(minutes=1))) == 1


def test_the_gateway_cleans_up_when_it_starts(env, db):
    make_user("old", email="old@example.com", email_verified=False, password_hash="x",
              created_at=utcnow() - timedelta(days=8))
    with TestClient(gateway_app.app):
        assert users() == []


def test_and_then_once_a_day(monkeypatch):
    slept, ran = [], []

    async def sleep(seconds):
        slept.append(seconds)
        if len(slept) > 2:
            raise asyncio.CancelledError

    def fn():
        ran.append(1)
        if len(ran) == 1:
            raise RuntimeError("the database blinked")  # logged; the next day tries again

    monkeypatch.setattr(gateway_app.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(gateway_app.daily(fn))
    assert slept == [24 * 3600] * 3 and len(ran) == 2
