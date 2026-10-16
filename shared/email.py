"""Email through Resend's HTTP API (https://resend.com/docs/api-reference/emails/send-email).

Four kinds go out: password-reset and "Confirm your email" links and "Your Otto account has been
deleted" (to the account's own email), and "bring it back up" requests (only ever to OTTO_NOTIFY_TO, with the asker as reply_to).
Without RESEND_API_KEY, development prints each email instead of sending it, and production
refuses (EmailUnavailable), so the caller can say so.
"""
import html as html_lib
import re
from datetime import UTC, datetime, timedelta, timezone

import requests

from shared import config

RESEND_URL = "https://api.resend.com/emails"
TIMEOUT = 10  # seconds
IST = timezone(timedelta(hours=5, minutes=30), "IST")
# one plain address: no display name, no list, no whitespace or line breaks (header injection)
ADDRESS = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+")
WAKE_SUBJECT = "Someone wants to try Otto"
SUPPORT_EMAIL = "support@taufi.dev"


class EmailError(Exception):
    """Resend refused the message or didn't answer."""


class EmailUnavailable(EmailError):
    """Production without RESEND_API_KEY: nothing can be sent."""


def available() -> bool:
    """Whether email works here: a key, or development (which prints instead)."""
    return bool(config.RESEND_API_KEY) or not config.PRODUCTION


def single_address(value) -> str | None:
    """value if it is exactly one valid email address (at most 254 characters), else None."""
    if not isinstance(value, str) or len(value) > 254 or not ADDRESS.fullmatch(value):
        return None
    return value


def post(payload) -> requests.Response:
    """The request to Resend (tests replace it)."""
    return requests.post(RESEND_URL, json=payload, timeout=TIMEOUT,
                         headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"})


def send(to: list[str], subject: str, text: str, html: str, reply_to: str | None = None):
    """Send one email (EmailError if Resend refuses). Without a key: print it (development), or
    EmailUnavailable (production)."""
    if not config.RESEND_API_KEY:
        if config.PRODUCTION:
            raise EmailUnavailable("RESEND_API_KEY is not set")
        print(f"[email] not sent (no RESEND_API_KEY)\n  to: {', '.join(to)}\n  reply-to: {reply_to or '-'}\n"
              f"  subject: {subject}\n" + "\n".join("  | " + line for line in text.splitlines()), flush=True)
        return
    payload = {"from": config.EMAIL_FROM, "to": to, "subject": subject, "text": text, "html": html}
    if reply_to:
        payload["reply_to"] = reply_to
    try:
        r = post(payload)
    except requests.RequestException as e:
        raise EmailError(f"Resend didn't answer ({type(e).__name__})") from None
    if r.status_code >= 300:
        raise EmailError(f"Resend refused the email ({r.status_code}): {r.text[:200]}")


def _html(paragraphs: list[str]) -> str:
    body = "".join(f'<p style="margin:0 0 12px">{p}</p>' for p in paragraphs)
    return (f'<div style="font-family:-apple-system,BlinkMacSystemFont,Helvetica,Arial,sans-serif;'
            f'font-size:15px;line-height:1.5;color:#15171C">{body}</div>')


def reset_email(link: str) -> tuple[str, str, str]:
    """(subject, text, html) for a password-reset link."""
    text = (f"Someone (hopefully you) asked to reset your Otto password.\n\n"
            f"Choose a new one here (the link expires in 1 hour and works once):\n{link}\n\n"
            f"If you didn't ask, ignore this email: your password stays the same.\n")
    e = html_lib.escape
    html = _html([
        "Someone (hopefully you) asked to reset your Otto password.",
        f'<a href="{e(link, quote=True)}">Choose a new password</a>. The link expires in 1 hour and works once.',
        "If you didn't ask, ignore this email: your password stays the same.",
    ])
    return "Reset your Otto password", text, html


VERIFY_SUBJECT = "Confirm your email for Otto"


def verify_email(link: str) -> tuple[str, str, str]:
    """(subject, text, html) for the link that confirms an email sign-up's address."""
    text = (f"Someone (hopefully you) made an Otto account with this email.\n\n"
            f"Confirm it here (the link expires in 24 hours and works once):\n{link}\n\n"
            f"If it wasn't you, ignore this email: the account goes away in a week.\n")
    e = html_lib.escape
    html = _html([
        "Someone (hopefully you) made an Otto account with this email.",
        f'<a href="{e(link, quote=True)}">Confirm your email</a>. The link expires in 24 hours and works once.',
        "If it wasn't you, ignore this email: the account goes away in a week.",
    ])
    return VERIFY_SUBJECT, text, html


def set_password_email(link: str, address: str) -> tuple[str, str, str]:
    """(subject, text, html) for a link that sets a first password, on an account made with GitHub."""
    text = (f"Someone (hopefully you) asked to set a password on your Otto account, so you can also log in\n"
            f"with {address} and a password.\n\n"
            f"Choose one here (the link expires in 1 hour and works once):\n{link}\n\n"
            f"If you didn't ask, ignore this email: you keep signing in with GitHub.\n")
    e = html_lib.escape
    html = _html([
        (f"Someone (hopefully you) asked to set a password on your Otto account, so you can also log in "
         f"with {e(address)} and a password."),
        f'<a href="{e(link, quote=True)}">Choose a password</a>. The link expires in 1 hour and works once.',
        "If you didn't ask, ignore this email: you keep signing in with GitHub.",
    ])
    return "Set your Otto password", text, html


DELETED_SUBJECT = "Your Otto account has been deleted"


def deleted_email(uninstall_urls: list[str]) -> tuple[str, str, str]:
    """(subject, text, html) confirming an account's deletion. uninstall_urls: where on GitHub to
    uninstall each installation it had (Otto can't do that for them)."""
    gone = ("Your Otto account has been deleted. You're signed out everywhere, and nobody can sign in to it again. "
            "Its chats and the rest of its data are permanently deleted, or anonymized, within 30 days.")
    prs = ("Pull requests Otto already opened live in your own repositories on GitHub, and they stay there.")
    app = "The Otto GitHub App stays installed until you uninstall it on GitHub:"
    ask = f"If you didn't ask for this, write to {SUPPORT_EMAIL}."
    text = f"{gone}\n\n{prs}\n\n" + (f"{app}\n" + "".join(f"{u}\n" for u in uninstall_urls) + "\n"
                                       if uninstall_urls else "") + f"{ask}\n"
    e = html_lib.escape
    links = "<br>".join(f'<a href="{e(u, quote=True)}">{e(u)}</a>' for u in uninstall_urls)
    html = _html([gone, prs] + ([f"{app}<br>{links}"] if uninstall_urls else []) +
                 [f'If you didn\'t ask for this, write to <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a>.'])
    return DELETED_SUBJECT, text, html


def wake_email(who: str, message: str, page: str, user_agent: str, when: datetime | None = None) -> tuple[str, str, str]:
    """(subject, text, html) asking Taufik to bring Otto up. Everything in the HTML is escaped."""
    when = (when or datetime.now(UTC)).astimezone(UTC)
    utc = when.strftime("%Y-%m-%d %H:%M UTC")
    ist = when.astimezone(IST).strftime("%Y-%m-%d %H:%M IST")
    fields = [("From", who), ("Message", message or "(none)"), ("Time", f"{utc} ({ist})"), ("Page", page),
              ("User agent", user_agent or "(unknown)")]
    text = "Someone asked to bring Otto back up.\n\n" + "".join(f"{k}: {v}\n" for k, v in fields)
    e = html_lib.escape
    html = _html(["Someone asked to bring Otto back up."] +
                 [f"<strong>{k}</strong><br>{e(v).replace(chr(10), '<br>')}" for k, v in fields])
    return WAKE_SUBJECT, text, html
