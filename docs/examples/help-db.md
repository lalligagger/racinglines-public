<!-- Captured by scripts/docs/capture_examples.py (id help-db, scripts/docs/examples.toml) on 2026-10-14 05:04 UTC, commit 4313bf1+dirty, 0.5 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines db -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
usage: racinglines db [-h] [--db DB]
                      {init,seed,stats,export,snapshot-export,snapshot-import,merge-athletes,changes} ...

racinglines db <command>

    init      Create or upgrade the schema to the latest migration (Alembic), then seed reference data.
    seed      Upsert sports / leagues / competitions / categories / venues from registry.py.
    stats     Row counts and coverage per season and category.
    export    Write the tidy frame (same columns as `racinglines data parse mtb_dh`'s CSV) for a competition to CSV.
    snapshot-export  The tables the models read, with ids, to data/archive/db/ (Parquet).
    snapshot-import  Load that snapshot into a fresh database: an exact replica (same ids, same prices).
    merge-athletes   Merge two athletes that are the same person (e.g. a name change found by UCI ID).
    changes   The data change log: ingests that changed anything, merges, notes (--add "why" for a note).

Connection: $DATABASE_URL, or --db URL (default: docker-compose.yml's database).

positional arguments:
  {init,seed,stats,export,snapshot-export,snapshot-import,merge-athletes,changes}
    init                Migrate schema to latest and seed reference data.
    seed                Upsert reference data from registry.py.
    stats               Row counts and coverage.
    export              Write the tidy frame for a competition to CSV.
    snapshot-export     Model tables with ids -> data/archive/db/.
    snapshot-import     Load data/archive/db/ into a fresh database.
    merge-athletes      Merge athlete DROP into KEEP (same person), then delete DROP.
    changes             The data change log, newest first; --add "why" adds a note.

options:
  -h, --help            show this help message and exit
  --db DB               Database URL (default: $DATABASE_URL or the docker-compose database).
```
<!-- --8<-- [end:output] -->
