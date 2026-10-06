"""
Forecast skill by lead time: how well a rain forecast issued N days before an F1 race said whether the race would be
wet, scored against the race's realised weather (props.history(): wet = rain_share > 0, the `race_rain` rule).

The input is the leads fixture, one row per race and lead (tests/fixtures/weather/open_meteo-leads-f1.csv):

    race_id, event_key, venue_slug, lat, lon, race_start_utc, window_end_utc, lead_days,
    precip_prob, precip_mm, temp_c, wind_kph, weather_code, source

lead_days 0 is the archive analysis of the race window (start to start + 2 h), 1..7 the forecast issued that many
days earlier; precip_prob is a 0-1 probability of precipitation in the window, blank when the provider has none at
that lead; precip_mm is summed over the window.

    load(path)                         the frame, columns and types checked
    p_wet(df, lead)                    P(wet) per race_id at one lead: precip_prob, else precip_mm >= mm_threshold
    skill(leads_df, history_df)        per lead: races, Brier, log loss, hit rate at 0.5, and the paired Brier
                                       difference against the circuit's climatology; plus `climatology` and
                                       `analysis` (lead 0) reference rows

p_wet() is what the weather-aware (-WX) props take as their forecast: props.check(..., forecast=) and
dnf_check.check(..., forecast=). Nothing here reads the database or the network.

    racinglines f1 props --forecast-skill --forecast leads.csv --history history.csv
"""

import numpy as np
import pandas as pd

COLUMNS = ("race_id", "event_key", "venue_slug", "lat", "lon", "race_start_utc", "window_end_utc", "lead_days",
           "precip_prob", "precip_mm", "temp_c", "wind_kph", "weather_code", "source")
FLOATS = ("lat", "lon", "precip_prob", "precip_mm", "temp_c", "wind_kph")
TIMES = ("race_start_utc", "window_end_utc")
LEADS = tuple(range(1, 8))
MM_THRESHOLD = 0.1            # mm over the race window counted as wet when the forecast has no probability
EPS = 1e-4                    # log loss clip


def load(path):
    """The leads CSV as a typed frame (validate())."""
    return validate(pd.read_csv(path, dtype={"event_key": str, "venue_slug": str, "source": str}))


def validate(df):
    """The frame with COLUMNS typed (race_id and lead_days int, times UTC, numbers float, weather_code Int64), or
    ValueError naming the first problem: a missing column, a bad type, a lead below 0, a precip_prob outside 0-1 or a
    race and lead given twice."""
    missing = [c for c in COLUMNS if c not in df]
    if missing:
        raise ValueError(f"leads: missing columns {missing}")
    d = df.copy()
    for c in ("race_id", "lead_days"):
        v = pd.to_numeric(d[c], errors="coerce")
        if v.isna().any() or (v != v.round()).any():
            raise ValueError(f"leads.{c}: needs an integer on every row")
        d[c] = v.astype(int)
    for c in FLOATS:
        v = pd.to_numeric(d[c], errors="coerce")
        if (v.isna() & d[c].notna() & (d[c].astype(str).str.strip() != "")).any():
            raise ValueError(f"leads.{c}: not a number")
        d[c] = v.astype(float)
    d["weather_code"] = pd.to_numeric(d["weather_code"], errors="coerce").astype("Int64")
    for c in TIMES:
        d[c] = pd.to_datetime(d[c], utc=True, errors="coerce")
        if d[c].isna().any():
            raise ValueError(f"leads.{c}: needs a timestamp on every row")
    for c in ("event_key", "venue_slug", "source"):
        d[c] = d[c].astype(str)
    if (d["lead_days"] < 0).any():
        raise ValueError("leads.lead_days: below 0")
    p = d["precip_prob"].dropna()
    if ((p < 0) | (p > 1)).any():
        raise ValueError("leads.precip_prob: outside 0-1 (a fraction, not a percent)")
    dup = d.duplicated(["race_id", "lead_days"])
    if dup.any():
        r = d.loc[dup].iloc[0]
        raise ValueError(f"leads: race {r['race_id']} lead {r['lead_days']} given twice")
    return d[list(COLUMNS)]


def p_wet(df, lead, mm_threshold=MM_THRESHOLD):
    """P(the race is wet) per race_id from the forecast issued `lead` days before (0: the analysis): the row's
    precip_prob when present, else 1.0 / 0.0 for precip_mm >= / < mm_threshold. Races with neither are left out.
    -> Series indexed by race_id, named p_wet."""
    d = df[df["lead_days"] == int(lead)].set_index("race_id")
    mm = (d["precip_mm"] >= mm_threshold).astype(float).where(d["precip_mm"].notna())
    return d["precip_prob"].fillna(mm).dropna().astype(float).rename("p_wet")


def _scores(p, y):
    p, y = np.asarray(p, float), np.asarray(y, float)
    q = np.clip(p, EPS, 1 - EPS)
    se2 = (p - y) ** 2
    return dict(races=len(p), wet_rate=float(y.mean()), mean_p=float(p.mean()), brier=float(se2.mean()),
                log_loss=float(-(y * np.log(q) + (1 - y) * np.log(1 - q)).mean()),
                hit_rate=float(((p >= 0.5) == (y > 0.5)).mean()))


def climatology(history_df, race_ids, prior_n=None):
    """P(wet) per race_id from the circuit's past only: props.rate(past, venue_id, "wet"), past = the history's races
    that started before it. Races not in the history, or with no race before them, are left out."""
    from racinglines.models.position_sim import props as PR
    prior_n = PR.PRIOR_N if prior_n is None else prior_n
    h = PR.prepare(history_df)
    out = {}
    for r in h[h["race_id"].isin(list(race_ids))].itertuples():
        past = h[h["start"] < r.start]
        p = PR.rate(past, r.venue_id, "wet", prior_n)
        if p is not None:
            out[r.race_id] = p
    return pd.Series(out, dtype=float, name="p_wet")


def skill(leads_df, history_df, leads=LEADS, mm_threshold=MM_THRESHOLD, prior_n=None):
    """One row per lead in `leads`, then `climatology` and `analysis` (lead 0): method, lead_days, races, wet_rate,
    mean_p, brier, log_loss, hit_rate (P >= 0.5 called wet), from_prob (rows that had a precip_prob rather than the
    precip_mm rule) and, for the forecast rows and analysis, brier_vs_clim / se_vs_clim: the mean paired Brier
    difference (this row minus climatology) and its standard error over the races both price. Scored on the races in
    both the leads frame and the history; wet = history rain_share > 0."""
    from racinglines.models.position_sim import props as PR
    h = PR.prepare(history_df).set_index("race_id")
    wet = h["wet"].astype(float)
    clim = climatology(history_df, leads_df["race_id"].unique(), prior_n)
    rows = []

    def score(method, lead, p):
        p = p[p.index.isin(wet.index)]
        if p.empty:
            return
        row = dict(method=method, lead_days=lead, **_scores(p, wet[p.index]))
        if lead is not None:
            sub = leads_df[(leads_df["lead_days"] == lead) & leads_df["race_id"].isin(p.index)]
            row["from_prob"] = int(sub["precip_prob"].notna().sum())
            both = p.index.intersection(clim.index)
            if len(both):
                y = wet[both].to_numpy()
                d = (p[both].to_numpy() - y) ** 2 - (clim[both].to_numpy() - y) ** 2
                row.update(brier_vs_clim=float(d.mean()),
                           se_vs_clim=float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else float("nan"))
        rows.append(row)

    for lead in leads:
        score("forecast", int(lead), p_wet(leads_df, lead, mm_threshold))
    score("climatology", None, clim)
    score("analysis", 0, p_wet(leads_df, 0, mm_threshold))
    cols = ["method", "lead_days", "races", "wet_rate", "mean_p", "brier", "log_loss", "hit_rate", "from_prob",
            "brier_vs_clim", "se_vs_clim"]
    out = pd.DataFrame(rows).reindex(columns=cols)
    out["lead_days"] = out["lead_days"].astype("Int64")
    out["from_prob"] = out["from_prob"].astype("Int64")
    return out
