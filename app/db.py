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
    return create_engine(url, pool_pre_ping=True)


def get_session():
    with Session(get_engine()) as session:
        yield session
