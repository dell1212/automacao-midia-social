import os
from functools import lru_cache

from sqlmodel import Session, create_engine

_DATABASE_URL_ENV = "DATABASE_URL"


@lru_cache(maxsize=1)
def get_engine():
    url = os.environ.get(_DATABASE_URL_ENV)
    if not url:
        raise RuntimeError(
            f"{_DATABASE_URL_ENV} is not set. Set it to a Postgres connection "
            "string (e.g. the Supabase project's connection string)."
        )
    # prepare_threshold=None disables psycopg3's server-side prepared
    # statements. Supabase's pooled connection string (port 6543) runs
    # pgbouncer in transaction mode, which hands a different backend to each
    # checkout — a prepared statement created on one is missing on the next,
    # and the reused name then collides:
    #   psycopg.errors.DuplicatePreparedStatement: prepared statement
    #   "_pg3_0" already exists
    # It surfaced as intermittent 500s and "publish dispatcher tick failed"
    # under concurrent load. Harmless on a direct connection, which simply
    # gives up the prepared-statement cache.
    return create_engine(
        url, pool_pre_ping=True, connect_args={"prepare_threshold": None}
    )


def get_session():
    with Session(get_engine()) as session:
        yield session
