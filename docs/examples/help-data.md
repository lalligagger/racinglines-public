<!-- Captured by scripts/docs/capture_examples.py (id help-data, scripts/docs/examples.toml) on 2026-10-14 05:04 UTC, commit 4313bf1+dirty, 1.5 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines data -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
racinglines data <command> SPORT [options]   (results, sessions, feeds and market links into the database)

    fetch              f1 nascar motogp cycling     Download the sport's source data (results, sessions or feeds) to data/raw/.
    download           mtb_dh                       Download Chronorace result files (see: racinglines data download mtb_dh -h).
    parse              mtb_dh                       Parse result files into a tidy CSV (see: racinglines data parse mtb_dh -h).
    ingest             f1 mtb_dh nascar motogp cycling Load the downloaded data into the database.
    schedule           f1 nascar cycling            Store the start times of sessions still to run as scheduled rounds (db/schedule.py), so markets on upcoming sessions have a close.
    link               nascar                       Identify the driver, race and contract of stored market links.
    events             cycling                      list the event files
    startlist          cycling                      fetch an event's start list (Mac only)
    probe              cycling                      fetch one PCS page, save it and show what parses (Mac only)
    points             mtb_dh                       Championship points tables: import, show, check against official standings.
    record             f1                           Live F1 session recorder: fetch current session via FastF1 and store snapshot to database.
    inrace-backfill    f1                           After a race: the Live tab's in-race win chart from the race's laps, one point per lap, as if the live-timing relay had run all race.
    pm-sync            f1
    pm-links-export    f1                           Write market links to data/archive/markets/<exchange>/links/ (stable keys).
    pm-links-import    f1                           Load that file into this database (no exchange access needed).
    pm-history         f1
    pm-trades          f1
    pm-record          f1
    pm-archive         f1
    pull               any sport                    One sport's shared data from the hosted server into the local database (racinglines data pull -h).

`racinglines data <command> SPORT -h` for a command's options.
```
<!-- --8<-- [end:output] -->
