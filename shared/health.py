"""Which providers or models can't be used right now, as the brain found out (out of credit, a bad
key, an unknown model), shared with the gateway through Postgres for GET /models."""
from sqlmodel import delete, select

from shared.db import get_db
from shared.models import ProviderHealth, utcnow

HINTS = {
    "quota": "Out of credit right now. Try another model.",
    "auth": "Not set up correctly. Try another model.",
    "model": "Not offered by its provider right now. Try another model.",
}


def mark(key, reason):
    """key: a provider name, or a catalog model id when only that model is the problem."""
    with get_db() as s:
        row = s.get(ProviderHealth, key) or ProviderHealth(key=key, reason=reason)
        row.reason, row.updated_at = reason, utcnow()
        s.add(row)


def unusable() -> dict[str, str]:
    """{key: reason} for everything marked."""
    with get_db() as s:
        return {r.key: r.reason for r in s.exec(select(ProviderHealth))}


def clear():
    with get_db() as s:
        s.exec(delete(ProviderHealth))
