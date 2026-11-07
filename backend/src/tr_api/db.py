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


class _Tx:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql: str, **params) -> None:
        self.conn.execute(text(sql), params)

    def execute_many(self, sql: str, rows: list[dict]) -> None:
        if rows:
            self.conn.execute(text(sql), rows)

    def fetch_one(self, sql: str, **params):
        row = self.conn.execute(text(sql), params).mappings().first()
        return dict(row) if row else None


def transaction():
    """`with transaction() as tx:` runs several statements atomically."""
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        with get_engine().begin() as conn:
            yield _Tx(conn)

    return _cm()
