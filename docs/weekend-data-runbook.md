# Weekend data and records runbook

A guide to the data and recorders running on the VM during round 16 (Bahrain GP, 2–4 October 2026).

## Recorders and storage

**Polymarket F1 books**: recorded every 60 seconds (racinglines-recorder unit). Books posted to the Polymarket API.

**Kalshi and OG.com books**: recorded every 5 minutes (racinglines-record-venues.timer). Venues recorded:
- Kalshi: F1, NASCAR
- OG.com: F1, NASCAR, MotoGP

Hourly sync from each venue after each book update.

**Storage on the VM**:
- **Hot rows**: Postgres database `racinglines`, tables `market_snapshots` (book state at each update)
- **Archive**: Parquet files in `data/archive/markets/` (VM only; the recorder's hourly archive pass moves cold market rows out of Postgres)
- **Backups**: SQL dumps in `data/backups/db/` (on-demand, not automatic)

## Known gaps this weekend

- **Kalshi**: bid/ask not stored; only trade-able pairs and last price recorded
- **MotoGP**: no calendar events or sprints; forecast stored once, not refreshed after races
- **Polymarket MotoGP**: no markets listed
- **Downhill (UCI DH)**: no exchange records (not in scope for round 16)
- **Polymarket F1**: last listed race was 28 Aug (round 11); no new race markets since
- **NASCAR and MotoGP forecasts**: in-sample, generated once and not refreshed after races

## Event data sources

- **F1**: FastF1 (qualifying, sprint, practice data; race results on 2026-10-04 ~10:00 UTC)
- **NASCAR**: cf.nascar.com (race results; schedule)
- **MotoGP**: pulselive (race results; riders and constructors; no calendar)
- **Downhill (UCI DH)**: ChronoRace web feed (live stage times; results; athletes)

Lake Placid 2026 UCI DH is not yet in the repo calendars (UNKNOWN: needs ingest).

## Live strategies and recommendations

**F1 private book** (disabled this round, T1 only): shared quoter places hype picks at the opening ($25 each, demo taker's picks outside the loss cap), then updates at session ends (FP1, FP2, SQ, Sprint, FP3, Quali, race). No live feed — updates come from the model's stage runs.

**F1 venue strategies** (Kalshi, Polymarket): Strategy A (early), Strategy C (hold), Strategy K (late) run from the signals timer every 5 minutes during book hours (2026-10-02 03:30 to 2026-10-04 07:00 UTC).

**NASCAR and MotoGP paper history**: in-sample from the prior season (stored in `RACINGLINES_SPORT_PAPER` env var on the VM). Not live-refreshed after races.

**Loss cap**: per-market cap `max_loss = 500` (F1 private book only; disabled this round).

## Config changes for this weekend

See the task notes above:
1. **Loss cap enabled** (F1 private book disabled): `[live.quoting] max_loss = 500.0` in `live/f1/2026-16.toml`
2. **H2H pairs source**: `[live.markets] h2h_from = "last_listed"` in `live/f1/2026-16.toml`

## Watch list

- **First 5 minutes after book opens (2026-10-02 03:30 UTC)**: signals timer, venue strategy updates, first update from the model
- **After any deploy**: check `bash scripts/deploy/vm.sh status` to confirm timers resumed
- **Loss cap status**: frozen at the first update; check `data/runs/live/2026-16/meta.json` for the cap and other settings (a later change needs `--unfreeze`)
- **Recorder status**: `bash scripts/deploy/vm.sh record status` shows Polymarket, Kalshi and OG.com book update times

### Status checks (run on the Mac in the repo root)

```
bash scripts/deploy/vm.sh status
```

```
bash scripts/deploy/vm.sh record status
```

```
bash scripts/deploy/vm.sh demo status
```

## References

- [Live events](live-events.md) — event specs and launch procedures
- [VM deploy](vm-deploy.md) — deployment flow and timers
- [F1 roadmap](f1-live-roadmap.md) — decision log and known issues
