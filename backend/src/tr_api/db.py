"""Database access: a SQLAlchemy engine and small helpers. Queries are plain SQL using PostGIS functions."""

from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True, future=True)


def fetch_one(sql: str, **params):
    with get_engine().begin() as conn:
        row = conn.execute(text(sql), params).mappings().first()
        return dict(row) if row else None


def fetch_all(sql: str, **params):
    with get_engine().begin() as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def execute(sql: str, **params) -> None:
    with get_engine().begin() as conn:
        conn.execute(text(sql), params)
