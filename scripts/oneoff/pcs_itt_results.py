"""One-off, local only (do not commit): men's elite ITT results from PCS, 2024-2026."""
import csv, re, sys, time
from pathlib import Path
from procyclingstats import Stage, Race, RaceStartlist

OUT = Path("data/raw/road_cycling")
COLS = ["race", "date", "distance_km", "vert_m", "profile_score", "rider", "rider_url", "nationality",
        "position", "gap_s", "winner_time_s", "status", "source_url"]
BASE = "https://www.procyclingstats.com/"
last = [0.0]


def polite():
    wait = 2.0 - (time.time() - last[0])
    if wait > 0:
        time.sleep(wait)
    last[0] = time.time()


def secs(t):
    if not t:
        return None
    parts = [int(float(x)) for x in str(t).split(":")]
    out = 0
    for p in parts:
        out = out * 60 + p
    return out


STATUS = {"DF": "OK", "DNF": "DNF", "DNS": "DNS", "DSQ": "DSQ", "OTL": "DNF", "NR": "DNS"}
YEARS = (2024, 2025, 2026)
NATIONS = ["belgium", "denmark", "france", "great-britain", "switzerland", "spain", "italy", "slovenia",
           "netherlands", "czech-republic", "portugal", "sweden", "hungary", "luxembourg"]
STAGE_RACES = {"giro-d-italia": YEARS, "tour-de-france": YEARS, "vuelta-a-espana": YEARS,
               "paris-nice": YEARS[1:], "tirreno-adriatico": YEARS[1:], "tour-de-romandie": YEARS[1:],
               "criterium-du-dauphine": YEARS[1:], "tour-de-suisse": YEARS[1:],
               "renewi-tour": YEARS[1:], "tour-of-britain": YEARS[1:]}


def build(mode):
    items = []  # (label, [candidate stage slugs])

    def nc(n, y):
        return (f"nc-{n}-itt-{y}", [f"race/nc-{n}/{y}/result"] if n == "portugal"
                else [f"race/nc-{n}-itt/{y}/result", f"race/nc-{n}/{y}/result"])
    if mode == "default":
        for y in YEARS:
            items.append((f"worlds-itt-{y}", [f"race/world-championship-itt/{y}/result"]))
        for y in YEARS[:2]:
            items.append((f"euro-itt-{y}", [f"race/uec-road-european-championships-itt/{y}/result"]))
        for y in YEARS[1:]:
            items += [nc(n, y) for n in NATIONS]
        for race, years in STAGE_RACES.items():
            for y in years:
                items.append((f"STAGES:{race}-{y}", [f"race/{race}/{y}"]))
    elif mode == "older":  # 2020-2023, everything
        for y in range(2020, 2024):
            items.append((f"worlds-itt-{y}", [f"race/world-championship-itt/{y}/result"]))
            items.append((f"euro-itt-{y}", [f"race/uec-road-european-championships-itt/{y}/result"]))
            items += [nc(n, y) for n in NATIONS]
            for race in STAGE_RACES:
                items.append((f"STAGES:{race}-{y}", [f"race/{race}/{y}"]))
    elif mode == "backfill":  # what the first run left out of 2024-2026
        items += [nc(n, 2024) for n in NATIONS]
        for race in STAGE_RACES:
            if race not in ("giro-d-italia", "tour-de-france", "vuelta-a-espana"):
                items.append((f"STAGES:{race}-2024", [f"race/{race}/2024"]))
        for y in YEARS:
            items.append((f"PROLOGUES:tour-de-romandie-{y}", [f"race/tour-de-romandie/{y}"]))
    return items


def is_itt(name, prologues_only=False):
    if "(TTT)" in name:
        return False
    prologue = bool(re.match(r"\s*Prologue", name))
    return prologue if prologues_only else ("(ITT)" in name or prologue)


def rows_for(label, slugs):
    slugs = [slugs] if isinstance(slugs, str) else slugs
    for slug in slugs:
        polite()
        try:
            s = Stage(slug)
            res = [r for r in s.results() if r.get("rider_name")]
        except Exception:
            if slug == slugs[-1]:
                raise
            continue
        break
    if not res:
        return None
    times = [secs(r.get("time")) for r in res if r.get("rank") and r.get("time")]
    win = min(times) if times else None
    dist, vert, ps, date = s.distance(), s.vertical_meters(), s.profile_score(), s.date()
    out = []
    for r in res:
        t = secs(r.get("time")) if r.get("rank") else None
        out.append([label, date, dist, vert, ps, r["rider_name"], r["rider_url"], r.get("nationality"),
                    r.get("rank"), (t - win) if (t is not None and win is not None) else None, win,
                    STATUS.get(r.get("status"), r.get("status")), BASE + slug])
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else "default"
    outname = {"default": "itt_results_pcs.csv", "older": "itt_results_pcs_2020_2023.csv",
               "backfill": "itt_results_pcs_backfill_2024_2026.csv"}[mode]
    items = build(mode)
    total, n, t0, tprog, failed = len(items), 0, time.time(), time.time(), []
    with open(OUT / outname, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for label, slugs in items:
            n += 1
            slug = slugs[0]
            try:
                if label.startswith(("STAGES:", "PROLOGUES:")):
                    polite()
                    name = label.split(":", 1)[1]
                    only_pro = label.startswith("PROLOGUES:")
                    sts = [x for x in Race(slug).stages() if is_itt(x["stage_name"], only_pro)]
                    for x in sts:
                        rows = rows_for(f"{name}-{x['stage_name'].split('|')[0].strip()}", x["stage_url"] + "/result")
                        print(f"{name} {x['stage_url']} | {len(rows) if rows else 0}", flush=True)
                        if rows:
                            w.writerows(rows)
                    if not sts:
                        print(f"{name} | no ITT stages", flush=True)
                else:
                    rows = rows_for(label, slugs)
                    print(f"{label} | {len(rows) if rows else 0}", flush=True)
                    if rows:
                        w.writerows(rows)
                f.flush()
            except Exception as e:
                failed.append(label)
                print(f"FAILED {label}: {type(e).__name__} {str(e)[:80]}", flush=True)
            if time.time() - tprog >= 300:
                print(f"progress: {n} of {total} races, {(time.time() - t0) / 60:.0f} min elapsed", flush=True)
                tprog = time.time()
    if mode != "default":
        print(f"done: {total} race items, {len(failed)} failed: {failed}", flush=True)
        return
    # 2026 Euro ITT start list
    try:
        polite()
        sl = RaceStartlist("race/uec-road-european-championships-itt/2026/startlist").startlist()
        with open(OUT / "euro_itt_2026_startlist.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["rider", "rider_url", "nationality", "team"])
            for r in sl:
                w.writerow([r.get("rider_name"), r.get("rider_url"), r.get("nationality"), r.get("team_name")])
        print(f"euro_itt_2026_startlist | {len(sl)}", flush=True)
    except Exception as e:
        failed.append("euro-2026-startlist")
        print(f"FAILED startlist: {type(e).__name__} {str(e)[:80]}", flush=True)
    print(f"done: {total} race items, {len(failed)} failed: {failed}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
