"""racinglines database layer (PostgreSQL via SQLAlchemy 2).

    python -m racedb init                         # create / migrate tables (Alembic)
    python -m racedb ingest data/script-generated # load downloaded event files
    python -m racedb stats                        # what's in the database

See docs/database.md.
"""
