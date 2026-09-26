# TODO

## Summary

<!-- readme: todo-summary -->

**Points validation (highest priority)**

- [ ] Get the official UCI DHI points scales (Final and qualifying), for 2026 and
      for past formats.
- [ ] Replace `FINAL_POINTS` / `QUAL_POINTS` / `QUAL_POINTS_ROUND`, per era if needed.
- [ ] Settle the edge cases: DNF/DSQ in the Final, ties, protected riders, bonus rounds.
- [ ] Check our 2026 totals after round 7 against the official standings, and add a
      test that pins them.
- [ ] Re-run and refresh the published numbers.

**Data**

- [ ] Key riders by UCI ID. It's in ChronoRace's JSON; names change across seasons.
- [ ] Parse the readable 2021 PDFs (Leogang, Les Gets). 2019–20 would need OCR.
- [ ] Build rounds missing from Wikipedia (probing) into the downloader. Clean up
      venue names.
- [ ] Add Women's categories, start order and weather.

**Model**

- [ ] Check calibration: win probabilities look too flat.
- [ ] Tune over all 43 backtest rounds. Add rider × venue effects.

**Engineering**

- [ ] Tests (turn the web-app and house-book smoke tests into a pytest suite).
- [ ] Refuse house markets (and market links) for junior categories (`categories.age_group = 'junior'`).
- [ ] Persist login throttling across restarts (it's in memory now), and add a stable named tunnel with Cloudflare Access.
- [ ] Condition in-weekend forecasts on completed rounds (Q1 results, split times).

<!-- /readme -->

Details for each item are in the sections below.

## Points validation

The points tables in `predictor.py` (`FINAL_POINTS`, `QUAL_POINTS`,
`QUAL_POINTS_ROUND`) are **placeholders**, and the same tables are used for every
season. Until they're fixed, every number measured in points (expected points,
standings, champion odds, `spearman_points`) is approximate.

- [ ] Get the official UCI DHI World Cup points scales, from the UCI MTB regulations
      (Part 4) or the standings PDFs on ChronoRace. Get the 2026 table first, then
      earlier eras for backtests (2021–22 single qualifier, 2023–24 semi-final,
      2025–26 Q1/Q2).
- [ ] Replace `FINAL_POINTS` with the official Final points for every scoring place.
      Check how many places score: currently 30, but the 2021–22 Finals had 60+ riders.
- [ ] Confirm which qualifying round pays points in each format, and how many places
      score. Also check whether riders who get through Q2 score. Update `QUAL_POINTS`
      and `QUAL_POINTS_ROUND`. If more than one round pays, extend
      `actual_event_points` and `simulate_weekend`.
- [ ] Store the tables in the `points_schemes` database table (per competition,
      era and round kind), and have the model read them from there instead of the
      constants.
- [ ] Check the edge cases:
  - [ ] DNF/DSQ in the Final: zero points, or last-place points?
  - [ ] Ties
  - [ ] Protected or wildcard riders
  - [ ] Bonus or double-points rounds
- [ ] **Reconcile:** run `actual_event_points(select_target(raw, 2026, "ME"))` and
      compare each rider's cumulative total after round 7 with the official
      standings. Every rider should match exactly. Repeat for one past season.
- [ ] Add a test that pins those totals, so a points change or bad data file is
      caught right away.
- [ ] Re-run `season` and `backtest`, and refresh the tables in the docs and README.

## Data

- [ ] **Use UCI rider IDs.** The results JSON has `UciRiderId` for every rider.
      Write it as a column in the downloaded markdown, re-download, and add
      `athlete_identifiers(scheme="uci")` at ingest, matched before names. This
      merges name changes such as `WILLIAMS Robert Jordan` / `WILLIAMS Jordan`
      (existing athletes need a one-off merge).
- [ ] **Parse the 2021 PDFs** (Leogang, Les Gets). The text layer is readable but has
      repeated letters from bold text (`BBBBRRRROOOO`), and each rider spans two
      lines. The PDFs also have UCI ID, year of birth, weather, temperature and
      track length.
- [ ] 2019–2020 PDFs: the text layer is unreadable font codes, so they'd need OCR.
      Low priority.
- [ ] Build **slug probing** into the downloader (`--probe START END`) for rounds
      missing from Wikipedia, like 2021 Snowshoe.
- [ ] Canonical venue names (`mont-ste-anne` → `mont-sainte-anne`,
      `vallnord`/`vallnord-pal-arinsal` → `pal-arinsal`).
- [ ] Elite Women and Junior Women: download, and check the model works for
      smaller fields.
- [ ] Start order: it's in ChronoRace's start-list PDFs and possibly the JSON.
      Needed for track-evolution and weather effects.
- [ ] Weather and track conditions (the PDFs have weather; `--conditions-file`
      exists but is empty).

## Model

- [ ] **Calibration check:** reliability curves for win, podium, top-10 and
      make-Final across all 43 backtest rounds. Win probabilities look too flat. Try
      a lower `INCIDENT_THRESHOLD`, per-round-type incident rates (Finals vs
      qualifying), or a heavier-tailed ε.
- [ ] A tuning sweep over all 43 rounds, not just 2026 rounds 2–7: half-life,
      junior weight, `prior_n`, practice weight.
- [ ] Rider × venue effects: shrink a rider's past residuals at the venue into the
      simulation instead of a fresh `u` every time.
- [ ] Time trends within a season, e.g. rider form or rookies improving fast.
- [ ] Protected-rider rules in older formats.
- [ ] Remaining 2026 venues: once rounds 8–9 are announced, use venue history in the
      forecast.
- [ ] Decide whether to retire or rebuild the older `fit`/`predict` Elo/GBR model.
      It hasn't been checked against the multi-season data.

## Engineering

- [x] Admin web app (`webapp/`): predictions, histories, backtests, Polymarket maker orders.
- [ ] Public/JSON API endpoints next to the admin pages.
- [ ] **Condition in-weekend forecasts on completed rounds.** Once Q1 has run, fix
      who has qualified and use the Q1 times. Also use split times from disrupted
      Timed Training sessions.
- [ ] Market-making loop: re-quote linked markets automatically when the model or
      book moves, within per-market and total exposure limits.
- [ ] Find a venue that lists downhill markets. Polymarket has none as of 2026-09.
- [x] In-progress events are forecast with their real start lists and saved against their race.
- [ ] Have `forecast_season` read `scheduled` events (no start list yet) as named rounds instead of `remaining_round`.
- [ ] Ingest on a schedule: download, then `racedb ingest` for new rounds.
- [ ] Ingest the other input formats (copy/paste, HTML, JSON) into the database.

- [x] Pinned `requirements.txt` (pipeline) and `requirements-docs.txt` (mkdocs).
- [ ] Optionally, a `pyproject.toml`, so the scripts can be installed as a package.
- [ ] Run `python build_readme.py --check` in CI or a pre-commit hook, so the README
      can't drift from the docs.
- [ ] Tests: parser fixtures (one file per format era), `event_format`,
      `actual_event_points`, the rider-ID normalization check.
- [x] PostgreSQL database instead of re-parsing files every run.
- [x] `.gitignore` (ignores `data/`, generated outputs, `site/`, Python and editor files).
