"""Refusals the frontend tells apart by a code: {"error": "<code>", "detail": "<a sentence>"}.

The detail keeps the shape the frontend already shows for any refusal ({"detail": "..."}); the
code is for the states that get their own screen (invite-only, paused, workers offline).
"""
from fastapi import Request
from fastapi.responses import JSONResponse


class Refused(Exception):
    def __init__(self, status, error, detail, headers=None):
        self.status, self.error, self.detail, self.headers = status, error, detail, headers


async def handle(request: Request, e: Refused) -> JSONResponse:
    return JSONResponse({"error": e.error, "detail": e.detail}, e.status, headers=e.headers)
