# Read-only strategy opening preview

`scripts/strategy_preview.py` is a standalone **F1** diagnostic, not a trading command.
It compares T1–T10 and TB's 50:50 T1/T8 opening blend, using an existing model run's
forecast cutoff and cached Polymarket bid/ask quotes. Choose any F1 event with an
existing diagnostic; there is no default source run or hardcoded event.

It never fetches market data, saves forecasts/signals, changes active profiles, or
places orders. PostgreSQL connections use repeatable-read transactions with
`default_transaction_read_only=on`, verified before reading. Model inputs are loaded
through that same transaction. No migration or database write is involved.

## Run and freeze inputs

Run from the repository root in the installed project environment. Replace
`EVENT_KEY` and `RUN_ID` below with an existing event/source diagnostic pair.
Store generated outputs under ignored `reports/`, never commit them.

**LOCAL (Mac)** — create the 4k preview (reads the configured database):

```bash
mkdir -p reports/strategy-preview
PYTHONPATH=. .venv/bin/python -m scripts.strategy_preview \
  --event EVENT_KEY --source-run RUN_ID --sims 4000 \
  > reports/strategy-preview/4k.json
```

**LOCAL (Mac)** — compare 16k simulations with the same frozen inputs:

```bash
PYTHONPATH=. .venv/bin/python -m scripts.strategy_preview \
  --event EVENT_KEY --source-run RUN_ID --sims 16000 \
  --snapshot reports/strategy-preview/4k.json \
  > reports/strategy-preview/16k.json
```

**LOCAL (Mac)** — render saved JSON, without a database connection:

```bash
PYTHONPATH=. .venv/bin/python -m scripts.strategy_preview \
  --render reports/strategy-preview/4k.json \
  --output-dir reports/strategy-preview/4k
```

The renderer writes Markdown and CSV: a candidate comparison, per-profile
`picked.csv` / `considered-not-picked.csv`, and combined decision tables.
Every supported market appears in each HK/QK decision table, including excluded,
illiquid, stale, incoherent, or unpriced markets. A rejected decision has zero
allocated cost/shares; any standalone watchlist size is a separate hypothetical
target, without the portfolio cap, not an approved allocation.

HK/QK default to a fresh **$1,000** balance, **$50** per market, **$250** total.
Override them with `--bankroll`, `--max-market`, and `--max-total`; keep those values
identical in frozen simulation comparisons. Original sizing retains the profile's
supported sizing fields. These are empty-position opening allocations, not rolling
season bankrolls.

Frozen JSON pins quotes, recorded 24-hour liquidity (including explicitly empty
venues), observation time, source run, event, cutoff, code commit, sizing and model
input fingerprint. A mismatch fails rather than mixing old/current inputs.
The fingerprint covers the repository model's cutoff view; it is not a full database
backup. A 16k run may reuse a matching stored diagnostic model; other variants are
computed in memory with each profile's seed (default 42). A flushed heartbeat runs
every five minutes during computation. Ad-hoc snapshots predating this version's
schema must be recreated.

## What this does and does not show

- Timing gates alone are bypassed: “enter now” is hypothetical, even when a profile
  would normally wait for another stage. Other model settings and market filters apply.
- Buys use cached asks, or `1 - bid` for NO, plus strategy slippage and venue fees.
  This differs from historical Polymarket sweeps that execute at the midpoint.
- Quotes must be valid two-sided quotes no more than ten minutes old. Touch depth
  and live fee schedules have not been verified.
- Zero recorded tape is **not** evidence of zero live trading activity.
- Linked Kalshi markets, unknown prediction kinds/market parameters, maker settings,
  and thin-market exceptions are explicitly unsupported and fail closed. No linked
  Kalshi markets is reported as empty coverage, not a successful Kalshi strategy test.
- This is not an execution recommendation. There is no trade execution or active
  configuration change.

Publishing this script requires focused synthetic tests and lint. A merge is not
proposed until the usual local `racinglines check`, non-live pytest, and strict MkDocs
gates have also been run. Merging code deploys code only: no migration or data step.
