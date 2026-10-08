"""Per-IP rate limits for the routes anyone can call without signing in (signing in, signing up,
asking whether an email has an account, asking for access).

Each limit is a sliding window kept in this process's memory: one gateway process, so that's the
whole picture; a restart forgets it. The client's IP is the connection's, or Cloudflare's
CF-Connecting-IP when OTTO_TRUST_PROXY=1 (only then: anyone can send the header).
"""
import threading, time
from collections import deque

from fastapi import Request

from gateway.errors import Refused
from shared import config

LIMITS = {  # name -> (requests, per seconds), per IP
    "login": (10, 60),            # POST /auth/login and /auth/token together
    "signup": (5, 3600),
    "email_status": (30, 600),
    "access_request": (5, 3600),
    "wake": (1, 3600),            # POST /wake-requests, per user (not per IP)
}
MAX_KEYS = 10_000  # past this many (limit, IP) pairs, idle ones are dropped
TOO_MANY = "Too many attempts. Wait a minute and try again."

_hits: dict[tuple[str, str], deque] = {}
_lock = threading.Lock()  # sync routes run in a thread pool


def client_ip(request: Request) -> str:
    if config.TRUST_PROXY and (ip := request.headers.get("cf-connecting-ip", "").strip()):
        return ip
    return request.client.host if request.client else "unknown"


def _prune(now):
    for key in [k for k, q in _hits.items() if not q or q[-1] <= now - LIMITS[k[0]][1]]:
        del _hits[key]


def hit(name, ip, now=None):
    """Count one request from ip against the limit `name`; Refused (429, with Retry-After) once
    it's used up. A refused request doesn't count."""
    allowed, window = LIMITS[name]
    now = time.monotonic() if now is None else now
    with _lock:
        if len(_hits) > MAX_KEYS:
            _prune(now)
        q = _hits.setdefault((name, ip), deque())
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= allowed:
            retry = max(1, int(q[0] + window - now + 1))
            raise Refused(429, "rate_limited", TOO_MANY, headers={"Retry-After": str(retry)})
        q.append(now)


def refund(name, key):
    """Take back key's latest hit on `name` (the request it allowed didn't happen after all)."""
    with _lock:
        q = _hits.get((name, key))
        if q:
            q.pop()


def limit(name):
    """A route dependency: count the request against the limit `name`."""
    def check(request: Request):
        hit(name, client_ip(request))
    return check


def reset():
    with _lock:
        _hits.clear()
