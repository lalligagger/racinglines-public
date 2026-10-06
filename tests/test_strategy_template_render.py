"""Render test for strategy.html (no database): the running strategy's explanation shows to pro and admin only."""

import pytest


def _render(show_fair):
    from racinglines.web.app import templates
    profile = {"name": "T4 · update, gbm", "strategy": "update", "settings": {"variant": "gbm"}}
    kpis = {"total": 12.5, "max_dd": -3.0, "peak_deployed": 100.0, "up": 1, "weekends": 2}
    context = dict(user={"id": 1, "role": "pro" if show_fair else "basic"}, viewer={"id": 1, "username": "ada"},
                   profile=profile, profile_why="x-why", show_fair=show_fair, record=[], seasons=[], acct={"kpis": kpis},
                   mix=[], users=[], sport_options=[], venue="", cur=None, stages=[], signals_nav=None, live_nav=None,
                   storage_ns="")
    return templates.env.get_template("strategy.html").render(**context)


@pytest.mark.parametrize("show_fair", [True, False])
def test_strategy_why_only_for_pro_and_admin(show_fair):
    html = _render(show_fair)
    assert "Running now" in html
    assert ('<p class="legend">x-why</p>' in html) is show_fair
