"""Downhill data items that don't need ChronoRace: unraced rounds in the category's own format (women and juniors
race smaller finals than the 2026 elite men's default), and canonical venue slugs. Synthetic data only."""

import numpy as np
import pandas as pd
import pytest

from racinglines.db import registry
from racinglines.models import timed_runs as P
from racinglines.models.timed_runs import model as TM
from racinglines.sources.chronorace.parse import parse_markdown_tables_file
from racinglines.testing import synthetic as SY


def _women(tmp_path, n_riders=24):
    """Synthetic Elite Women: 24 riders, finals of 20 (the generator's), relabelled from its Men Elite files."""
    for name, text in SY.mtb_results_md(n_events=4, n_riders=n_riders).items():
        if "elite" in name:
            (tmp_path / name.replace("men", "women")).write_text(text.replace("Category: Men Elite", "Category: Women Elite"))
    raw = pd.concat([pd.DataFrame(parse_markdown_tables_file(f)) for f in sorted(tmp_path.glob("*.md"))], ignore_index=True)
    return raw[raw["round"].isin(P.RUN_WEIGHTS)]


@pytest.mark.quick
def test_unraced_rounds_in_the_categorys_own_format(tmp_path):
    raw = _women(tmp_path)
    assert set(raw["category"]) == {"WE"}
    tgt = P.select_target(raw, 2026, "WE")
    done = P.completed_events(tgt)
    last = P.event_order(tgt)[-1]
    assert TM.unraced_format(tgt, done) is TM.DEFAULT_FORMAT                          # today's behaviour
    assert TM.unraced_format(tgt, done, "last") == TM.event_format(tgt, last) == dict(kind="q1q2", q1_to_final=20, q2_to_final=0)
    assert TM.unraced_format(tgt, [], "last") == TM.CATEGORY_FORMAT.get("WE", TM.DEFAULT_FORMAT)
    with pytest.raises(ValueError):
        TM.unraced_format(tgt, done, "men")
    kw = dict(n_remaining=2, n_sims=400, attend_window=1)
    _, _, per0, st0 = P.forecast_season(raw, tgt, rng=np.random.default_rng(5), **kw)
    _, _, per1, st1 = P.forecast_season(raw, tgt, rng=np.random.default_rng(5), unraced="last", **kw)
    # the men's default puts all 24 women in the final (20 from Q1 + the Q2 top 10); their own format, 20
    assert per0["make_final_prob"].min() == pytest.approx(1.0)
    assert per1["make_final_prob"].sum() == pytest.approx(20.0, abs=0.01)
    assert st1["champion_prob"].sum() == pytest.approx(1.0, abs=0.02)
    _, _, per_d, _ = P.forecast_season(raw, tgt, rng=np.random.default_rng(5), unraced="default", **kw)
    pd.testing.assert_frame_equal(per0, per_d)                                        # the default is unchanged


@pytest.mark.quick
def test_canonical_venue_slugs():
    assert registry.canonical_venue("mont-ste-anne") == "mont-sainte-anne"
    assert registry.canonical_venue("vallnord") == registry.canonical_venue("vallnord-pal-arinsal") == "pal-arinsal"
    assert registry.canonical_venue("les-gets") == "les-gets" and registry.canonical_venue("new-venue") == "new-venue"
    assert set(registry.VENUE_ALIASES.values()) <= set(registry.VENUES)               # every alias points at a venue
