"""Access tokens, refresh tokens (rotation, reuse detection) and WebSocket tickets."""
from datetime import timedelta

import jwt
import pytest
from sqlmodel import select

from gateway import tokens
from shared import config
from shared.db import get_db
from shared.models import RefreshToken, as_utc, utcnow
from tests.fakes import make_user


@pytest.fixture
def user():
    return make_user("u1", token_version=2)


def rows() -> list[RefreshToken]:
    with get_db() as s:
        return list(s.exec(select(RefreshToken).order_by(RefreshToken.created_at)).all())


# --- access tokens --------------------------------------------------------------------

def test_an_access_token_carries_the_user_and_version_and_lasts_15_minutes(user):
    claims = jwt.decode(tokens.access_token(user), config.AUTH_SECRET, algorithms=["HS256"])
    assert (claims["sub"], claims["ver"], claims["type"]) == ("u1", 2, "access")
    assert claims["exp"] - claims["iat"] == 15 * 60 and claims["jti"]
    assert tokens.access_token(user) != tokens.access_token(user)  # each has its own jti


def test_access_token_minutes_is_configurable(user, monkeypatch):
    monkeypatch.setattr(config, "ACCESS_TOKEN_MINUTES", 5)
    claims = tokens.access_claims(tokens.access_token(user))
    assert claims["exp"] - claims["iat"] == 5 * 60


def forged(claims, secret=None) -> str:
    return jwt.encode(claims, secret or config.AUTH_SECRET, algorithm="HS256")


def test_only_valid_unexpired_access_tokens_verify(user):
    now = utcnow()
    good = {"sub": "u1", "ver": 2, "type": "access", "jti": "j", "iat": now, "exp": now + timedelta(minutes=1)}
    assert tokens.access_claims(forged(good))["sub"] == "u1"
    for bad in [None, "", "garbage",
                forged(good, "another secret " * 4),
                forged({**good, "exp": now - timedelta(seconds=1)}),
                forged({**good, "type": "refresh"}),
                forged({k: v for k, v in good.items() if k != "type"}),
                forged({**good, "aud": "github-state"})]:
        assert tokens.access_claims(bad) is None, bad


# --- refresh tokens -------------------------------------------------------------------

def test_a_refresh_token_is_random_stored_only_hashed_and_lasts_30_days(user):
    token = tokens.issue_refresh("u1", user_agent="curl/8")
    [row] = rows()
    assert len(token) >= 60 and token not in row.token_hash
    assert row.token_hash == tokens.sha256(token) and row.user_id == "u1" and row.user_agent == "curl/8"
    assert row.family_id and row.revoked_at is None and row.replaced_by_id is None
    assert timedelta(days=30) - timedelta(minutes=1) < as_utc(row.expires_at) - utcnow() <= timedelta(days=30)


def test_rotating_revokes_the_old_token_and_issues_one_in_the_same_family(user):
    old = tokens.issue_refresh("u1")
    user_id, new = tokens.rotate_refresh(old, user_agent="firefox")
    assert user_id == "u1" and new != old
    first, second = rows()
    assert first.revoked_at is not None and first.replaced_by_id == second.id
    assert second.family_id == first.family_id and second.revoked_at is None and second.user_agent == "firefox"


def backdate_revocations(seconds):
    """As if every revocation so far happened `seconds` earlier."""
    with get_db() as s:
        for row in s.exec(select(RefreshToken).where(RefreshToken.revoked_at.is_not(None))).all():
            row.revoked_at = as_utc(row.revoked_at) - timedelta(seconds=seconds)
            s.add(row)


def reasons() -> list:
    return [r.revoked_reason for r in rows()]


def test_reusing_a_rotated_token_after_the_grace_window_revokes_the_whole_family(user):
    old = tokens.issue_refresh("u1")
    _, new = tokens.rotate_refresh(old)
    other_family = tokens.issue_refresh("u1")
    backdate_revocations(21)

    assert tokens.rotate_refresh(old) is None
    assert reasons() == ["rotated", "reuse", None]
    assert tokens.rotate_refresh(new) is None  # the family is gone
    assert tokens.rotate_refresh(other_family) is not None  # another device is unaffected


def test_a_retry_within_the_grace_window_gets_a_sibling_and_the_family_lives(user):
    old = tokens.issue_refresh("u1")
    _, new = tokens.rotate_refresh(old)
    backdate_revocations(19)

    user_id, sibling = tokens.rotate_refresh(old)

    assert user_id == "u1" and sibling not in (old, new)
    first, second, third = rows()
    assert third.family_id == first.family_id and third.revoked_at is None
    assert tokens.refresh_user(new) == "u1" and tokens.refresh_user(sibling) == "u1"
    assert reasons() == ["rotated", None, None]


def test_the_grace_window_is_configurable(user, monkeypatch):
    monkeypatch.setattr(config, "REFRESH_REUSE_GRACE_SECONDS", 0)
    old = tokens.issue_refresh("u1")
    tokens.rotate_refresh(old)
    assert tokens.rotate_refresh(old) is None


def test_a_token_revoked_by_logout_gets_no_grace(user):
    token = tokens.issue_refresh("u1")
    tokens.revoke_family(token)
    assert tokens.rotate_refresh(token) is None
    assert reasons() == ["logout"]


def test_no_grace_in_a_family_with_a_token_revoked_for_another_reason(user):
    old = tokens.issue_refresh("u1")
    _, new = tokens.rotate_refresh(old)
    tokens.revoke_family(new)  # logged out right after rotating
    assert tokens.rotate_refresh(old) is None


def test_no_grace_in_a_family_killed_for_reuse(user):
    a = tokens.issue_refresh("u1")
    _, b = tokens.rotate_refresh(a)
    backdate_revocations(21)
    _, c = tokens.rotate_refresh(b)  # b was rotated just now
    assert tokens.rotate_refresh(a) is None  # stale: the family dies
    assert tokens.rotate_refresh(b) is None  # within b's grace window, but the family is dead
    assert tokens.refresh_user(c) is None


def test_revoking_everything_records_why(user):
    tokens.issue_refresh("u1")
    tokens.revoke_all("u1", reason="password")
    tokens.issue_refresh("u1")
    tokens.revoke_all("u1", reason="logout_all")
    assert reasons() == ["password", "logout_all"]


def test_expired_unknown_or_missing_refresh_tokens_dont_rotate(user, monkeypatch):
    monkeypatch.setattr(config, "REFRESH_TOKEN_DAYS", -1)
    expired = tokens.issue_refresh("u1")
    for token in (expired, "made-up", "", None):
        assert tokens.rotate_refresh(token) is None


def test_refresh_user_peeks_without_rotating(user):
    token = tokens.issue_refresh("u1")
    assert tokens.refresh_user(token) == "u1" and tokens.refresh_user(token) == "u1"
    assert tokens.refresh_user("made-up") is None and tokens.refresh_user(None) is None
    tokens.revoke_family(token)
    assert tokens.refresh_user(token) is None


def test_revoking_a_family_and_everything_of_a_user(user):
    make_user("u2")
    a = tokens.issue_refresh("u1")
    _, a2 = tokens.rotate_refresh(a)
    b = tokens.issue_refresh("u1")
    theirs = tokens.issue_refresh("u2")

    tokens.revoke_family(a2)
    assert tokens.refresh_user(a2) is None and tokens.refresh_user(b) == "u1"
    tokens.revoke_family("made-up")  # nothing to do

    tokens.revoke_all("u1", reason="logout_all")
    assert tokens.refresh_user(b) is None and tokens.refresh_user(theirs) == "u2"


def test_the_user_agent_is_trimmed(user):
    tokens.issue_refresh("u1", user_agent="x" * 1000)
    assert len(rows()[0].user_agent) == tokens.USER_AGENT_MAX


def test_prune_deletes_tokens_that_expired_over_a_week_ago(user):
    keep = [tokens.issue_refresh("u1") for _ in range(2)]
    with get_db() as s:
        s.add(RefreshToken(id="old", user_id="u1", family_id="f", token_hash="h1",
                           expires_at=utcnow() - timedelta(days=7, minutes=1)))
        s.add(RefreshToken(id="recent", user_id="u1", family_id="f", token_hash="h2",
                           expires_at=utcnow() - timedelta(days=6)))
    assert tokens.prune_refresh() == 1
    assert sorted(r.id for r in rows() if r.id in ("old", "recent")) == ["recent"] and len(rows()) == 3
    assert all(tokens.refresh_user(t) == "u1" for t in keep)


# --- WebSocket tickets ----------------------------------------------------------------

@pytest.fixture
def clock(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(tokens, "now", lambda: t[0])
    return t


def test_a_ticket_works_once_for_its_session(clock):
    ticket = tokens.issue_ticket("u1", "s1")
    assert len(ticket) >= 30
    assert tokens.take_ticket(ticket, "s1") == "u1"
    assert tokens.take_ticket(ticket, "s1") is None


def test_a_ticket_for_another_session_is_refused_and_used_up(clock):
    ticket = tokens.issue_ticket("u1", "s1")
    assert tokens.take_ticket(ticket, "s2") is None
    assert tokens.take_ticket(ticket, "s1") is None


def test_a_ticket_lasts_30_seconds(clock):
    fresh, stale = tokens.issue_ticket("u1", "s1"), tokens.issue_ticket("u1", "s1")
    clock[0] += 29.9
    assert tokens.take_ticket(fresh, "s1") == "u1"
    clock[0] += 0.2
    assert tokens.take_ticket(stale, "s1") is None
    assert tokens.take_ticket(None, "s1") is None and tokens.take_ticket("made-up", "s1") is None


def test_expired_tickets_are_dropped(clock):
    tokens.issue_ticket("u1", "s1")
    clock[0] += 31
    tokens.issue_ticket("u1", "s2")
    assert len(tokens._tickets) == 1
