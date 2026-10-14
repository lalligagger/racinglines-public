<!-- Captured by scripts/docs/capture_examples.py (id help-live, scripts/docs/examples.toml) on 2026-10-14 05:04 UTC, commit 4313bf1+dirty, 0.5 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines live -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
usage: racinglines live [-h] {new,step,run,auto,agent,status,report,reprice,settle} ...

racinglines live: launch and run a live private-book event, for any sport (pipelines/live.py).

    racinglines live new f1 2026-16                        # write live/f1/2026-16.toml from the schedule
    racinglines live new mtb_dh 20260925_mtb --final 3 --quali 2,91
    racinglines live step live/f1/2026-16.toml             # one idempotent update (F1: acts only when an update is due)
    racinglines live run live/f1/2026-16.toml              # step at the sport's cadence until the event is settled
    racinglines live run live/mtb_dh/20260925_mtb.toml     # downhill: the poll loop, locked (one loop per final)
    racinglines live run live/f1/2026-15.toml --simulate --no-fetch     # a rehearsal on a simulated clock
    racinglines live run kart/demo-2026-09 --demo --simulate --no-fetch   # the kart demo pack's rehearsal (docs/quickstart.md)
    racinglines live agent live/f1/2026-16.toml --install  # a macOS LaunchAgent: one step every 5 minutes, locked
    racinglines live auto                                  # F1: step every event whose window is open (a 5-min timer)
    racinglines live status                                # every event: live / replay / settled, last update, lateness
    racinglines live report live/f1/2026-16.toml           # the event report (Markdown + charts + PDF)
    racinglines live settle live/mtb_dh/20260925_mtb.toml  # record a settled event in the database (live_events)
    racinglines live reprice live/mtb_dh/20260925_mtb.toml --every 10   # re-price from the logged raw feed

A spec is a path or sport/event (live/<sport>/<event>.toml). A demo experiment: play money, nothing is
traded anywhere.

positional arguments:
  {new,step,run,auto,agent,status,report,reprice,settle}
    new                 Write a launch spec from the schedule, with the sport's defaults.
    step                One idempotent update.
    run                 Step at the sport's cadence until the event is settled (downhill: one
                        locked poll loop per final).
    auto                F1: one step of every committed spec whose window is open (from its
                        opening to a day after its results), so no event has to be started by
                        hand.
    agent               Write (and load) a macOS LaunchAgent for a spec: a step every 5 min,
                        locked, logged.
    status              Every event: live / replay / settled, last update, next update, lateness.
    report              The event report: Markdown, charts and a PDF, in the run folder.
    reprice             Re-price an event from its logged raw feed with this code (downhill);
                        scores it against what was quoted live.
    settle              Record a settled event in the database (live_events: dates, the book's
                        P&L).

options:
  -h, --help            show this help message and exit
```
<!-- --8<-- [end:output] -->
