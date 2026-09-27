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
