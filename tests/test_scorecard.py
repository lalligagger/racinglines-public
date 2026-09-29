"""The exchange-weekend pricing scorecard (racinglines/pipelines/scorecard.py): scoring, the coherence and
open-market rules, the tables, and the files, from synthetic rows (no database)."""

import math

import pandas as pd
import pytest

from racinglines.pipelines import scorecard as SC

pytestmark = pytest.mark.quick


def _rows():
    r = []
    # race_win at two stages, three markets; the third has no mid at the first stage
    for stage, fairs, mids in (("pre-weekend", (0.6, 0.3, 0.1), (0.5, 0.4, None)),
                               ("after Quali", (0.8, 0.15, 0.05), (0.7, 0.2, 0.1))):
        for i, (f, m) in enumerate(zip(fairs, mids)):
            r.append(dict(stage=stage, cutoff=None, kind="race_win", subject=f"d{i}", token_id=f"w{i}", fair=f, mid=m,
                          coherent=True, open=True, y=1.0 if i == 0 else 0.0))
    # a pole market: open pre-weekend, closed after qualifying; incoherent group after quali
    r.append(dict(stage="pre-weekend", cutoff=None, kind="race_pole", subject="d0", token_id="p0", fair=0.4, mid=0.35,
                  coherent=True, open=True, y=1.0))
    r.append(dict(stage="after Quali", cutoff=None, kind="race_pole", subject="d0", token_id="p0", fair=1.0, mid=0.99,
                  coherent=False, open=False, y=1.0))
    # a podium market the venue priced while its group was incoherent: counted, but without a mid
    r.append(dict(stage="pre-weekend", cutoff=None, kind="race_podium", subject="d0", token_id="q0", fair=0.5, mid=0.5,
                  coherent=False, open=True, y=0.0))
    # unpriced by the model, and unsettled: left out
    r.append(dict(stage="pre-weekend", cutoff=None, kind="race_h2h", subject="x", token_id="h0", fair=None, mid=0.5,
                  coherent=True, open=True, y=1.0))
    r.append(dict(stage="pre-weekend", cutoff=None, kind="race_h2h", subject="y", token_id="h1", fair=0.5, mid=0.5,
                  coherent=True, open=True, y=None))
    return r


def test_scores_model_on_all_and_venue_on_paired():
    sc = SC.score(_rows()).set_index(["stage", "kind"])
    pre = sc.loc[("pre-weekend", "race_win")]
    assert pre["n"] == 3 and pre["paired"] == 2
    assert pre["brier"] == pytest.approx(((0.6 - 1) ** 2 + 0.3 ** 2 + 0.1 ** 2) / 3)
    assert pre["logloss"] == pytest.approx(-(math.log(0.6) + math.log(0.7) + math.log(0.9)) / 3)
    assert pre["brier_model"] == pytest.approx(((0.6 - 1) ** 2 + 0.3 ** 2) / 2)
    assert pre["brier_venue"] == pytest.approx(((0.5 - 1) ** 2 + 0.4 ** 2) / 2)
    assert pre["logloss_venue"] == pytest.approx(-(math.log(0.5) + math.log(0.6)) / 2)
    assert pre["gap"] == pytest.approx(0.1)
    q = sc.loc[("after Quali", "race_win")]
    assert q["n"] == q["paired"] == 3 and q["brier_venue"] < q["brier_model"] or q["brier_model"] < q["brier_venue"]


def test_closed_incoherent_and_unscorable_rows():
    sc = SC.score(_rows())
    keys = set(zip(sc["stage"], sc["kind"]))
    assert ("after Quali", "race_pole") not in keys                  # closed kinds are not scored
    assert ("pre-weekend", "race_h2h") not in keys                   # no fair, or no result
    pod = sc.set_index(["stage", "kind"]).loc[("pre-weekend", "race_podium")]
    assert pod["n"] == 1 and pod["paired"] == 0 and pod["brier"] == pytest.approx(0.25)
    assert pd.isna(pod["brier_venue"])
    # stages come in weekend order, whatever the input order
    assert list(sc["stage"].unique()) == ["pre-weekend", "after Quali"]


def test_pooled_and_empty():
    by_kind = SC.score(_rows(), by=("kind",)).set_index("kind")
    assert by_kind.loc["race_win", "n"] == 6 and by_kind.loc["race_win", "paired"] == 5
    total = SC.score(_rows(), by=())
    assert len(total) == 1 and total["n"].iloc[0] == 8
    assert len(SC.score([])) == 0 and "brier" in SC.score([]).columns


def test_tables_and_files(tmp_path):
    rows = pd.DataFrame(_rows())
    res = dict(event_key="2026-15", name="Test GP", venue="polymarket", rows=rows, scores=SC.score(rows), note="",
               runs=[("pre-weekend", pd.Timestamp("2026-09-24 07:30"), 7), ("after Quali", pd.Timestamp("2026-09-25 13:30"), 11)])
    md = SC.markdown(res, "abc123")
    assert md.startswith("# Pricing scorecard: 2026-15 Test GP on polymarket")
    assert "| pre-weekend | race_win | 3 |" in md and "run #11" in md and "All stages pooled" in md
    assert "–" in SC.format_table(SC.score(rows))                    # missing venue scores are dashes
    text = SC.format_text(res["scores"])
    assert "brier_venue" in text and "race_pole" in text
    files = SC.write(res, "abc123", tmp_path)
    assert {f.name for f in tmp_path.iterdir()} == {"2026-15_polymarket.md", "2026-15_polymarket.csv",
                                                     "2026-15_polymarket_markets.csv"}
    assert len(pd.read_csv(files["csv"])) == len(res["scores"])
    out = dict(year=2026, venue="polymarket", weekends=pd.DataFrame([dict(event_key="2026-15", event="Test GP", stages=2,
               **SC.score(rows, by=()).iloc[0].to_dict())]), rows=rows.assign(event_key="2026-15"),
               by_stage=SC.score(rows), by_kind=SC.score(rows, by=("kind",)), results=[res])
    smd = SC.season_markdown(out, "abc123")
    assert "## Per weekend" in smd and "| 2026-15 | Test GP | 8 |" in smd
    files = SC.write_season(out, "abc123", tmp_path)
    assert files["md"].exists() and files["weekends"].exists() and files["markets"].exists()


def test_notes_name_unpriced_kinds_and_incoherent_stages():
    rows = pd.DataFrame(_rows() + [dict(stage="pre-weekend", cutoff=None, kind="race_top10", subject="d0", token_id="t0",
                                        fair=0.9, mid=None, coherent=True, open=True, y=1.0)])
    n = SC.notes(rows, "kalshi")
    assert len(n) == 2
    assert n[0] == "no kalshi price recorded for race_top10"
    assert n[1].startswith("mid not scored where") and "race_podium at pre-weekend" in n[1]
    assert "race_pole" not in n[1]                                            # the incoherent pole row is closed
    assert SC.notes(pd.DataFrame(columns=SC.EMPTY), "kalshi") == []


def test_default_model_key_matches_the_sweep():
    from racinglines.pipelines import sweep_settings as SS
    assert SC.default_model_key() == SS.Settings.from_dict().model_key
    assert SC.default_model_key("gbm") != SC.default_model_key()


def test_cli_registers_scorecard():
    from racinglines.cli import f1
    with pytest.raises(SystemExit):
        f1.main(["scorecard", "--venue", "nowhere", "--event", "2026-15"])
