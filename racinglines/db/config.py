"""Database connection settings.

Set DATABASE_URL to point somewhere else, e.g.
    export DATABASE_URL=postgresql+psycopg://user:pass@host:5432/racinglines
The default matches docker-compose.yml (host port 5433, so it doesn't clash
with a Postgres already running on 5432).
"""

import os
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DEFAULT_URL = "postgresql+psycopg://racinglines:racinglines@localhost:5433/racinglines"


def database_url(url=None):
    return url or os.environ.get("DATABASE_URL", DEFAULT_URL)


@lru_cache(maxsize=None)
def get_engine(url=None):
    return create_engine(database_url(url), future=True)


def get_session(url=None):
    return sessionmaker(get_engine(url), expire_on_commit=False)()
