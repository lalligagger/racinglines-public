# Plan: Add UCI Road Cycling Results Source

**Goal:** Move road cycling from tape-only (market data only) to results-backed, enabling race-outcome pricing and modeling.

**Current state:** Road cycling schema exists (`sports/road_cycling.toml`, competition `uci_road_wt`, Kalshi markets `KXCYCLING*`), but with no results source or model (model_family = "none").

**Blocker (from docs/coverage.md):** "road cycling needs a results source whose terms allow it first"

---

## Phase 0: Verify Terms of Use (Read-only, in progress)

### Candidate: First Cycling API (`firstcycling` PyPI package)

**Status:** Package exists on PyPI but not installed in `.venv`

**Probe needed:**
1. [ ] Read First Cycling API **terms of use** 
   - PyPI: https://pypi.org/project/firstcycling/
   - GitHub: https://github.com/TeamWanderlusters/firstcycling (if available)
   - Verify: non-commercial use, automated scraping allowed, data attribution terms
   
2. [ ] Probe API (with User-Agent header):
   - `/races/` — list races by year
   - `/race/{id}/` — race details (course, weather, etc.)
   - `/race/{id}/results` — stage results, general classification
   - Rate limits and history depth

3. [ ] Compare with MotoGP precedent:
   - MotoGP API (`api.motogp.pulselive.com`) was reviewed 2026-09-29 (see `sports/motogp.toml` and `docs/data.md`)
   - Document findings in same format

### If approved:

**Phase 1: Create Results Adapter**
- Path: `racinglines/sources/cycling/` (following `motogp/`, `nascar/`, etc.)
- Files needed:
  - `__init__.py` — export the adapter class
  - `fetch.py` — API calls (races, stages, results, standings)
  - `ingest.py` — normalize results to racinglines schema (`Race`, `Stage`, `Outcome`, `Result`)
  - `links.py` — match results to market links (by rider, team, event)

**Phase 2: Update `sports/road_cycling.toml`**
```toml
[results]
host = "https://api.firstcycling.com/v1"  # (if applicable)
# Add rate limits, history, terms documentation
# Reference: sports/motogp.toml for format
```

**Phase 3: Integrate with pipeline**
- Update `racinglines/sources/__init__.py` to register cycling adapter
- Add cycling to `racinglines.sources.ingest()` dispatcher
- Add tests in `tests/test_cycling_results.py` (fixtures in `tests/fixtures/market/cycling_README.txt`)

**Phase 4: Model (2027 work)**
- Once results are ingested, add a `pricing_model` to `road_cycling.toml`
- Implement position-based model (similar to NASCAR)

---

## Reference: MotoGP source setup (2026-09-29)

**What was probed and documented:**
- API: `api.motogp.pulselive.com/motogp/v1`
- Endpoints: seasons, events, sessions, classification
- Limitations: no lap-by-lap/sector JSON (PDF only)
- History: 78 seasons (1949-2026)
- Terms: restricted, private non-commercial use reviewed for the owner

**How it's documented:**
- `sports/motogp.toml` — [results] section with host, comments on limits, terms
- `docs/data.md` — "MotoGP public results source verified (2026-09-29)" section
- `racinglines/sources/motogp/` — adapter code

---

## Next step

Read-only only: 
1. Check First Cycling API terms on PyPI / GitHub
2. If terms allow automated scraping (at least read-only, non-commercial), pass to owner for review
3. Then proceed to Phase 1 (adapter implementation)

**Do not:** install packages, write to VM, or commit changes until terms are cleared.
