"""Token usage: one row per LLM call, each user's daily limit (UTC days), and estimated costs."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlmodel import select

from shared import config
from shared.db import get_db
from shared.models import Session, Usage, User, as_utc

DAILY_DAYS = 14  # the chart on the Usage page


def utcnow():
    return datetime.now(timezone.utc)


def day_start(now) -> datetime:
    return now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def resets_at(now=None) -> str:
    """When today's tokens stop counting: the next midnight UTC."""
    return (day_start(now or utcnow()) + timedelta(days=1)).isoformat()


def record(session_id, user_id, provider, model, prompt_tokens, completion_tokens):
    with get_db() as s:
        s.add(Usage(user_id=user_id, session_id=session_id, provider=provider, model=model,
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, created_at=utcnow()))


def _tokens():
    return func.coalesce(func.sum(Usage.prompt_tokens + Usage.completion_tokens), 0)


def used_today(user_id, now=None) -> int:
    with get_db() as s:
        return s.exec(select(_tokens()).where(Usage.user_id == user_id,
                                              Usage.created_at >= day_start(now or utcnow()))).one()


def limit_status(user_id, now=None) -> dict | None:
    """{used, limit, resets_at} once the user has used their daily tokens, else None."""
    now = now or utcnow()
    with get_db() as s:
        user = s.get(User, user_id)
    if user is None:
        return None
    used = used_today(user_id, now)
    if used < user.daily_token_limit:
        return None
    return {"used": used, "limit": user.daily_token_limit, "resets_at": resets_at(now)}


def cost(model, prompt_tokens, completion_tokens) -> float:
    """Estimated USD, from MODEL_PRICES; a model without a price costs 0."""
    p = config.MODEL_PRICES.get(model) or {}
    return prompt_tokens / 1e6 * p.get("input_per_1m", 0) + completion_tokens / 1e6 * p.get("output_per_1m", 0)


def summary(user_id, now=None) -> dict:
    """Today against the limit, this (UTC) month, the last DAILY_DAYS days and this month by model."""
    now = now or utcnow()
    today = day_start(now)
    month = today.replace(day=1)
    first_day = today - timedelta(days=DAILY_DAYS - 1)
    with get_db() as s:
        limit = s.get(User, user_id).daily_token_limit
        by_model = s.exec(select(Usage.model, func.sum(Usage.prompt_tokens), func.sum(Usage.completion_tokens))
                          .where(Usage.user_id == user_id, Usage.created_at >= month)
                          .group_by(Usage.model)).all()
        recent = s.exec(select(Usage.created_at, Usage.prompt_tokens + Usage.completion_tokens)
                        .where(Usage.user_id == user_id, Usage.created_at >= min(first_day, month))).all()
        sessions = s.exec(select(func.count()).select_from(Session)
                          .where(Session.user_id == user_id, Session.created_at >= month)).one()
    daily = {(first_day + timedelta(days=i)).date(): 0 for i in range(DAILY_DAYS)}
    for ts, tokens in recent:
        day = as_utc(ts).date()
        if day in daily:
            daily[day] += tokens
    models = sorted(({"model": m, "tokens": p + c, "est_cost_usd": round(cost(m, p, c), 6)} for m, p, c in by_model),
                    key=lambda m: m["tokens"], reverse=True)
    return {
        "today": {"tokens": daily[today.date()], "limit": limit, "resets_at": resets_at(now)},
        "month": {"sessions": sessions, "tokens": sum(m["tokens"] for m in models),
                  "est_cost_usd": round(sum(m["est_cost_usd"] for m in models), 6)},
        "daily": [{"date": d.isoformat(), "tokens": t} for d, t in daily.items()],
        "by_model": models,
    }
