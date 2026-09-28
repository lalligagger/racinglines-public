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
    assert cfg == dict(name="t", parallel=2, hours=0.5, grace=10.0)
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
    assert S.argv(dh)[3:] == ["mtb_dh", "walk-forward", "--db", "--seasons", "2025", "--save", "--half-life-days", "120.0"]
    assert dh["settings"] == DHSettings.from_dict(dict(half_life_days=120)).to_json()
    with pytest.raises(ValueError, match="unknown keys"):
        S.load(_queue(tmp_path, '[[job]]\nsport = "mtb_dh"\nvariant = "gridq"\n'))      # an F1 setting
    with pytest.raises(ValueError, match="job kind"):
        S.load(_queue(tmp_path, '[[job]]\nsport = "mtb_dh"\nkind = "sweep"\n'))


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
