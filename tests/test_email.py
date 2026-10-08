"""Email through Resend: password resets, and "bring it back up" requests (POST /wake-requests)."""
import json
from datetime import datetime, timezone

import pytest
from sqlmodel import select

from gateway import app as gateway_app
from shared import config, email
from shared.db import get_db
from shared.models import PasswordReset
from tests.fakes import sign_out, signup


class FakeResend:
    """Stands in for email.post: records each message Resend would send."""

    def __init__(self, status=200):
        self.sent, self.status = [], status

    def __call__(self, payload):
        self.sent.append(payload)
        return type("R", (), {"status_code": self.status, "text": "{}"})()


@pytest.fixture
def resend(monkeypatch):
    fake = FakeResend()
    monkeypatch.setattr(config, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(config, "OTTO_NOTIFY_TO", "taufik@example.com")
    monkeypatch.setattr(config, "EMAIL_FROM", "Otto <noreply@taufi.dev>")
    monkeypatch.setattr(email, "post", fake)
    return fake


# --- the client ------------------------------------------------------------------------------

def test_resend_gets_one_message_with_reply_to(resend):
    email.send(["a@example.com"], "Hi", "text body", "<p>html</p>", reply_to="b@example.com")
    assert resend.sent == [{"from": "Otto <noreply@taufi.dev>", "to": ["a@example.com"], "subject": "Hi",
                            "text": "text body", "html": "<p>html</p>", "reply_to": "b@example.com"}]


def test_a_refusal_from_resend_is_an_error(resend):
    resend.status = 422
    with pytest.raises(email.EmailError):
        email.send(["a@example.com"], "Hi", "t", "<p>t</p>")


def test_without_a_key_development_logs_the_email(monkeypatch, capsys):
    monkeypatch.setattr(email, "post", lambda payload: pytest.fail("no key: nothing is sent"))
    email.send(["a@example.com"], "Subject here", "the body\nline 2", "<p>x</p>")
    out = capsys.readouterr().out
    assert "Subject here" in out and "the body" in out and "not sent" in out


def test_without_a_key_production_refuses(monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION", True)
    assert email.available() is False
    with pytest.raises(email.EmailUnavailable):
        email.send(["a@example.com"], "s", "t", "<p>t</p>")


@pytest.mark.parametrize("bad", ["a@example.com\r\nBcc: x@evil.com", "a@example.com, b@example.com", "not-an-email",
                                 "<a@example.com>", "a@example.com\n", ""])
def test_header_injection_and_lists_are_not_addresses(bad):
    assert email.single_address(bad) is None


def test_the_wake_email_names_who_and_escapes_everything():
    when = datetime(2026, 10, 8, 18, 45, tzinfo=timezone.utc)
    subject, text, html = email.wake_email("v@example.com", "<script>alert(1)</script> hi", "app", "Mozilla <b>", when)
    assert subject == "Someone wants to try Otto"
    assert "v@example.com" in text and "<script>alert(1)</script> hi" in text  # plain text, as written
    assert "<script>" not in html and "&lt;script&gt;" in html and "Mozilla &lt;b&gt;" in html
    assert "2026-10-08 18:45 UTC" in text and "2026-10-09 00:15 IST" in text  # UTC+5:30


# --- password resets -------------------------------------------------------------------------

def test_a_reset_link_is_emailed_and_expires_in_an_hour(client, resend):
    signup(client, email="taufik@example.com")
    sign_out(client)
    resend.sent.clear()
    r = client.post("/auth/forgot", json={"email": "Taufik@Example.com"})
    assert r.json() == {"ok": True}
    [msg] = resend.sent
    assert msg["to"] == ["taufik@example.com"] and "reply_to" not in msg
    assert "/reset-password?token=" in msg["text"] and "1 hour" in msg["text"]
    assert "/reset-password?token=" in msg["html"]
    with get_db() as s:
        assert len(s.exec(select(PasswordReset)).all()) == 1


def test_an_unknown_email_answers_the_same_and_sends_nothing(client, resend):
    r = client.post("/auth/forgot", json={"email": "nobody@example.com"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert resend.sent == []


def test_a_failed_send_still_answers_the_same(client, resend):
    signup(client, email="taufik@example.com")
    sign_out(client)
    resend.status = 500
    assert client.post("/auth/forgot", json={"email": "taufik@example.com"}).json() == {"ok": True}


def test_production_without_a_key_has_no_reset(client, monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION", True)
    monkeypatch.setattr(email, "post", lambda p: pytest.fail("nothing is sent"))
    assert client.get("/health").json()["password_reset"] is False
    r = client.post("/auth/forgot", json={"email": "taufik@example.com"})
    assert r.status_code == 503 and r.json()["error"] == "email_unavailable"


def test_health_says_reset_works(client, resend):
    assert client.get("/health").json()["password_reset"] is True


def test_development_without_a_key_prints_the_link(client, capsys):
    signup(client, email="taufik@example.com")
    sign_out(client)
    client.post("/auth/forgot", json={"email": "taufik@example.com"})
    assert "/reset-password?token=" in capsys.readouterr().out


# --- POST /wake-requests ----------------------------------------------------------------------

def test_a_signed_in_user_can_ask_taufik_once_an_hour(client, resend):
    signup(client, email="user@example.com", name="Ada <Lovelace>")
    resend.sent.clear()
    r = client.post("/wake-requests", json={"message": "Could you <b>bring it up</b>?"})
    assert r.status_code == 202 and r.json() == {"ok": True}
    [msg] = resend.sent
    assert msg["to"] == ["taufik@example.com"]  # never the user
    assert msg["reply_to"] == "user@example.com"
    assert msg["subject"] == "Someone wants to try Otto"
    assert "Could you <b>bring it up</b>?" in msg["text"] and "&lt;b&gt;" in msg["html"]

    again = client.post("/wake-requests", json={})
    assert again.status_code == 429 and again.json()["error"] == "rate_limited"
    assert int(again.headers["retry-after"]) > 3000
    assert len(resend.sent) == 1


def test_the_limit_is_per_user(client, resend):
    signup(client, email="one@example.com")
    assert client.post("/wake-requests", json={}).status_code == 202
    sign_out(client)
    signup(client, email="two@example.com")
    assert client.post("/wake-requests", json={}).status_code == 202


def test_wake_requests_need_a_sign_in_and_a_short_message(client, resend):
    assert client.post("/wake-requests", json={}).status_code == 401
    signup(client)
    assert client.post("/wake-requests", json={"message": "x" * 1001}).status_code == 422
    assert resend.sent == [] or all(m["subject"] != "Someone wants to try Otto" for m in resend.sent)


def test_a_github_only_account_has_no_reply_to_but_is_named(client, resend, monkeypatch):
    from tests.fakes import log_in_as, make_user

    make_user("u9", name="GH User", github_login="gh-user")
    log_in_as(client, "u9")
    assert client.post("/wake-requests", json={}).status_code == 202
    [msg] = resend.sent
    assert "reply_to" not in msg and "@gh-user" in msg["text"]


def test_wake_requests_in_production_without_a_key_are_503(client, monkeypatch):
    signup(client)
    monkeypatch.setattr(config, "PRODUCTION", True)
    r = client.post("/wake-requests", json={})
    assert r.status_code == 503 and r.json()["error"] == "email_unavailable"


def test_development_without_a_key_logs_the_wake_email(client, capsys):
    signup(client, email="user@example.com")
    assert client.post("/wake-requests", json={"message": "hello"}).status_code == 202
    out = capsys.readouterr().out
    assert "Someone wants to try Otto" in out and "user@example.com" in out


def test_a_failed_wake_email_is_502_and_may_be_retried(client, resend):
    signup(client, email="user@example.com")
    resend.status = 500
    r = client.post("/wake-requests", json={})
    assert r.status_code == 502 and r.json()["error"] == "email_failed"
    resend.status = 200
    assert client.post("/wake-requests", json={}).status_code == 202
