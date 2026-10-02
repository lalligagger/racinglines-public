"""Search queue (racinglines/pipelines/search.py): parsing, the automatic baseline, job identity and
the command lines it runs."""

import pytest

from racinglines.pipelines import search as S
from racinglines.pipelines import sweep_settings as SS

pytestmark = pytest.mark.quick


def _queue(tmp_path, body):
    p = tmp_path / "q.toml"
    p.write_text('[search]\nname = "t"\nparallel = 2\nhours = 0.5\n' + body)
    return p


def test_baseline_is_added_first_for_every_season(tmp_path):
    cfg, jobs, cands = S.load(_queue(tmp_path, '[[job]]\nvariant = "reset"\nyear = 2025\n'
                                               '[[job]]\nvariant = "gridq"\n'))
    assert cfg == dict(name="t", parallel=2, hours=0.5, grace=10.0, grid=0, history_cache=False)
    assert [(j["year"], j["settings"]["variant"]) for j in jobs] == [(2025, "baseline"), (2026, "baseline"),
                                                                     (2025, "reset"), (2026, "gridq")]
    assert cands == []


def test_a_queued_baseline_is_not_duplicated(tmp_path):
    _, jobs, _ = S.load(_queue(tmp_path, '[[job]]\nvariant = "gridq"\n[[job]]\nvariant = "baseline"\nnote = "b"\n'))
    assert [j["settings"]["variant"] for j in jobs] == ["baseline", "gridq"]


def test_job_id_covers_every_setting_but_not_notes():
    a = dict(kind="sweep", year=2026, variant="baseline")
    assert S.job_id(a) == S.job_id(dict(a, note="why"))
    assert S.job_id(a) == S.job_id(dict(a, min_edge=0.05))                 # a default spelled out is the same job
    assert S.job_id(a) != S.job_id(dict(a, min_edge=0.08))
    assert S.job_id(a) != S.job_id(dict(a, half_life_days=90))
    assert S.job_id(a) != S.job_id(dict(a, year=2025))


def test_unknown_keys_and_bad_values_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown keys"):
        S.load(_queue(tmp_path, '[[job]]\nhalf_life = 90\n'))
    with pytest.raises(ValueError):
        S.load(_queue(tmp_path, '[[job]]\ntaker_stages = "after lunch"\n'))


def test_command_lines():
    j = dict(kind="sweep", year=2025, rounds="1-5",
             settings=SS.Settings.from_dict(dict(variant="gridq+pretrain", min_edge=0.03)).to_json())
    assert S.argv(j)[1:] == ["-m", "racinglines", "f1", "--variant", "gridq+pretrain", "sweep", "--year", "2025",
                             "--no-fetch", "--save", "--rounds", "1-5", "--min-edge", "0.03"]
    c = S.argv(dict(kind="checkpoints", year=2026, variants="baseline,reset", entries="0,3,6"))
    assert c[4:] == ["season-checkpoints", "--year", "2026", "--save", "--variants", "baseline,reset",
                     "--entries", "0,3,6"]


def test_candidates_are_parsed_with_full_settings(tmp_path):
    _, _, cands = S.load(_queue(tmp_path, '[[candidate]]\nname = "wide maker"\nstrategy = "maker"\n'
                                          'variant = "gridq"\nhalf_spread = 0.03\nwhy = "x"\n'))
    (c,) = cands
    assert c["settings"]["half_spread"] == 0.03 and c["settings"]["sims"] == 4000
    assert c["settings_key"] == SS.Settings.from_dict(dict(variant="gridq", half_spread=0.03)).key


def test_downhill_jobs_get_their_own_settings_baseline_and_command(tmp_path):
    from racinglines.models.timed_runs.settings import DHSettings
    _, jobs, _ = S.load(_queue(tmp_path, '[[job]]\nsport = "mtb_dh"\nyear = 2025\nhalf_life_days = 120\n'
                                         '[[job]]\nvariant = "gridq"\n'))
    assert [(j.get("sport", "f1"), j["kind"], j["year"], j["note"][:8] if "baseline" in j.get("note", "") else "")
            for j in jobs][:2] == [("mtb_dh", "walk_forward", 2025, "baseline"), ("f1", "sweep", 2026, "baseline")]
    dh = next(j for j in jobs if j.get("sport") == "mtb_dh" and j["settings"]["half_life_days"] == 120)
    assert S.argv(dh)[3:] == ["backtest", "walk-forward", "mtb_dh", "--seasons", "2025", "--save", "--half-life-days", "120.0"]
    assert dh["settings"] == DHSettings.from_dict(dict(half_life_days=120)).to_json()
    with pytest.raises(ValueError, match="unknown keys"):
        S.load(_queue(tmp_path, '[[job]]\nsport = "mtb_dh"\nvariant = "gridq"\n'))      # an F1 setting
    with pytest.raises(ValueError, match="job kind"):
        S.load(_queue(tmp_path, '[[job]]\nsport = "mtb_dh"\nkind = "sweep"\n'))


def test_global_model_jobs_get_their_own_settings_baseline_command_and_id(tmp_path):
    q = _queue(tmp_path, '[[job]]\nsport = "nascar"\nmodel = "global"\nyear = 2025\nhalf_life_days = 360\nreplicates = 3\n'
                         '[[job]]\nsport = "f1"\nmodel = "global"\nyear = 2025\nnoise = 1.0\n'
                         '[[job]]\nsport = "nascar"\nyear = 2025\n')          # the sport's own model: another baseline
    _, jobs, _ = S.load(q)
    mine = [j for j in jobs if j.get("model") == "global" and j["sport"] == "nascar"]
    assert sorted((j["settings"]["seed"] or 0, j["settings"]["half_life_days"]) for j in mine) == [
        (0, 240.0), (0, 360.0), (1, 240.0), (1, 360.0), (2, 240.0), (2, 360.0)]
    f1 = [j for j in jobs if j.get("model") == "global" and j["sport"] == "f1"]
    assert {j["kind"] for j in f1} == {"walk_forward"} and len(f1) == 2          # a baseline and its job, no F1 sweep
    own = [j for j in jobs if j.get("sport") == "nascar" and not j.get("model")]
    assert len(own) == 1 and not {j["id"] for j in own} & {j["id"] for j in mine}      # the queued default is its baseline
    job = next(j for j in mine if j["settings"]["half_life_days"] == 360 and not j["settings"]["seed"])
    assert S.argv(job)[3:] == ["backtest", "walk-forward", "nascar", "--seasons", "2025", "--save", "--model", "global",
                               "--half-life-days", "360.0"]
    assert S._title(job).startswith("global ")
    with pytest.raises(ValueError, match="unknown keys"):
        S.load(_queue(tmp_path, '[[job]]\nsport = "nascar"\nmodel = "global"\nvariant = "gridq"\n'))
    with pytest.raises(ValueError, match="unknown model"):
        S.load(_queue(tmp_path, '[[job]]\nsport = "nascar"\nmodel = "nope"\n'))
    with pytest.raises(ValueError, match="job kind"):
        S.load(_queue(tmp_path, '[[job]]\nsport = "f1"\nmodel = "global"\nkind = "sweep"\n'))


def test_f1_job_ids_did_not_move():
    # finished jobs in a restarted search are found by these ids
    assert S.job_id(dict(kind="sweep", year=2026, variant="baseline")) == "720a768f98"
    assert S.job_id(dict(kind="sweep", year=2025, variant="gridq", rounds="1-5", min_edge=0.08)) == "0599d2fcc2"


def test_replicates_run_the_job_and_its_baseline_at_several_seeds(tmp_path):
    _, jobs, _ = S.load(_queue(tmp_path, '[[job]]\nsport = "mtb_dh"\nyear = 2026\nprior_n = 1.5\nreplicates = 3\n'
                                         '[[job]]\nsport = "mtb_dh"\nyear = 2025\nprior_n = 1.5\n'))
    seeds = lambda pn, y: sorted((j["settings"]["seed"] or 0) for j in jobs                         # noqa: E731
                                 if j["year"] == y and j["settings"]["prior_n"] == pn)
    assert seeds(1.5, 2026) == [0, 1, 2] and seeds(0.5, 2026) == [0, 1, 2]       # the baseline too
    assert seeds(1.5, 2025) == [0] and seeds(0.5, 2025) == [0]
    assert len({j["id"] for j in jobs}) == len(jobs)


def test_a_kalshi_sweep_job_gets_its_own_id_baseline_and_command(tmp_path):
    """A job's `venue` (off by default: Polymarket) is part of its id, adds a baseline on the same venue,
    and turns into `f1 sweep --venue kalshi`; Polymarket ids and commands don't move."""
    a = dict(kind="sweep", year=2026, variant="gbm")
    assert S.job_id(a) == S.job_id(dict(a, venue="polymarket"))
    assert S.job_id(a) != S.job_id(dict(a, venue="kalshi"))
    _, jobs, cands = S.load(_queue(tmp_path, '[[job]]\nvariant = "gbm"\nvenue = "kalshi"\n[[job]]\nvariant = "gbm"\n'
                                             '[[candidate]]\nname = "k"\nstrategy = "maker"\nvariant = "gbm"\n'
                                             'venue = "kalshi"\n'))
    assert [(j["settings"]["variant"], j.get("venue", "polymarket")) for j in jobs] == \
        [("baseline", "kalshi"), ("baseline", "polymarket"), ("gbm", "kalshi"), ("gbm", "polymarket")]
    assert S.argv(jobs[2])[6:] == ["sweep", "--year", "2026", "--no-fetch", "--save", "--venue", "kalshi"]
    assert "--venue" not in S.argv(jobs[3]) and "venue" not in jobs[3]
    assert cands[0]["venue"] == "kalshi" and S._title(jobs[2]).endswith(" · kalshi")
    with pytest.raises(ValueError, match="venue"):
        S.load(_queue(tmp_path, '[[job]]\nvariant = "gbm"\nvenue = "betfair"\n'))
    with pytest.raises(ValueError, match="venue"):
        S.load(_queue(tmp_path, '[[job]]\nkind = "checkpoints"\nvenue = "kalshi"\n'))


def test_grid_groups_sweeps_of_one_season_and_model(tmp_path):
    """[search] grid: sweeps of the same season, rounds and model share a process; each keeps its own
    settings (a job's venue included) for `f1 sweep --grid`."""
    q = _queue(tmp_path, '[[job]]\nvariant = "gbm"\nsize = 25\nvenue = "kalshi"\n'
                         '[[job]]\nvariant = "gbm"\nmax_disagree = 0.1\n[[job]]\nvariant = "gridq"\n'
                         '[[job]]\nyear = 2025\nvariant = "gbm"\n')
    q.write_text(q.read_text().replace("hours = 0.5\n", "hours = 0.5\ngrid = 4\n"))
    cfg, jobs, _ = S.load(q)
    assert cfg["grid"] == 4 and not cfg["history_cache"]
    keys = {j["id"]: S._grid_key(j) for j in jobs}
    gbm = [j for j in jobs if j["year"] == 2026 and j["settings"]["variant"] == "gbm"]
    assert len(gbm) == 2 and keys[gbm[0]["id"]] == keys[gbm[1]["id"]]
    assert S._grid_settings(gbm[0]) == {"variant": "gbm", "size": 25.0, "venue": "kalshi"}
    other = [j for j in jobs if j["settings"]["variant"] == "gridq" or j["year"] == 2025]
    assert all(keys[j["id"]] != keys[gbm[0]["id"]] for j in other)
