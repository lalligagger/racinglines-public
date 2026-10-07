"""Small read-only probe of a candidate golf results source, run from the owner's Mac.

CLAUDE.md: "Probe a data source from the owner's machine before any full run." This makes a handful of GET
requests to ESPN's public site API (no key), saves the raw responses and prints what it found: does it answer, the
shape, whether per-round scores are present, and how far back history goes. Nothing here has been verified from
the cloud; the endpoint paths are the commonly cited ones and may be wrong, which is what the probe is for.

The terms of use are NOT settled by this probe: ESPN's site API is unofficial and undocumented. The owner checks the
terms (https://disneytermsofuse.com/) before any full import, as was done for MotoGP.

    # LOCAL (Mac)
    python scripts/probes/golf_results_probe.py            # saves to data/raw/golf/probe/ (gitignored)
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OUT = Path("data/raw/golf/probe")
BASE = "https://site.api.espn.com/apis/site/v2/sports/golf"
# One date per season back to 2015, to see how deep the scoreboard's history goes (all mid-season Sundays).
DATES = ["20260920", "20250921", "20240922", "20220925", "20190922", "20150920"]
PAUSE_SEC = 2.0  # stay gentle: about a dozen requests in total


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "racinglines-probe (read-only, owner's machine)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()
    except Exception as e:  # network refusal, DNS, TLS
        return None, {}, repr(e).encode()


def save(name, body):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_bytes(body)


def summarize_scoreboard(doc):
    """Events, competitors and whether each competitor carries per-round scores (linescores)."""
    rows = []
    for ev in doc.get("events", []):
        comps = (ev.get("competitions") or [{}])[0].get("competitors", [])
        with_rounds = sum(1 for c in comps if c.get("linescores"))
        rows.append({"id": ev.get("id"), "name": ev.get("name"), "date": ev.get("date"),
                     "competitors": len(comps), "with_round_scores": with_rounds})
    return rows


def main():
    print(f"probe start {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}", flush=True)
    first_event = None
    for tour in ("pga",):
        for d in DATES:
            url = f"{BASE}/{tour}/scoreboard?dates={d}"
            status, headers, body = get(url)
            save(f"{tour}-scoreboard-{d}.json", body)
            print(f"\n{url}\n  status {status}, {len(body)} bytes, "
                  f"rate headers: {[k for k in headers if 'rate' in k.lower() or 'limit' in k.lower()]}", flush=True)
            try:
                doc = json.loads(body)
            except ValueError:
                print("  not JSON", flush=True)
                time.sleep(PAUSE_SEC)
                continue
            for row in summarize_scoreboard(doc):
                print(f"  {row}", flush=True)
                first_event = first_event or row["id"]
            time.sleep(PAUSE_SEC)

    # Other tours' scoreboards: do they exist under the same path? (DP World Tour, LIV, Korn Ferry.)
    for tour in ("eur", "liv", "ntw"):
        url = f"{BASE}/{tour}/scoreboard"
        status, _, body = get(url)
        save(f"{tour}-scoreboard-current.json", body)
        print(f"\n{url}\n  status {status}, {len(body)} bytes", flush=True)
        time.sleep(PAUSE_SEC)

    # One event's full leaderboard, if the scoreboard gave an id: per-round scores, cut, ties, withdrawals.
    if first_event:
        url = f"https://site.web.api.espn.com/apis/site/v2/sports/golf/leaderboard?event={first_event}"
        status, _, body = get(url)
        save(f"leaderboard-{first_event}.json", body)
        print(f"\n{url}\n  status {status}, {len(body)} bytes", flush=True)

    print(f"\nSaved raw responses under {OUT}/ (gitignored). Send the printed summary back to the thread.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
