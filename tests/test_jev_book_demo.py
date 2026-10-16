"""Jev book demo: mocked client only, no network, no database."""
import json
from types import SimpleNamespace as NS

import pytest

from racinglines.research import jev_book_demo as D


def line(i, d, pf, pm, status="mapped"):
    return {"id": i, "status": status, "kind": "race_win", "n_legs": 1, "decimal_odds": d, "book_prob": round(1 / d, 6),
            "model_prob": pf, "market_prob": pm, "title": "SECRET NAME", "selection": "SECRET NAME"}


PRICED = {"lines": [line("a", 3.0, 0.40, 0.38), line("b", 2.5, 0.50, 0.45), line("c", 5.0, 0.3, 0.3, status="unmapped"),
                    line("d", 4.0, 0.30, 0.28)]}
SETTLED = {"lines": [{"id": "a", "result": "won", "profit": 2.0}, {"id": "b", "result": "lost", "profit": -1.0},
                     {"id": "d", "result": "pending", "profit": None}]}


class Fake:
    def __init__(self, noul=0.9, trust="trust_fair", sizing="kelly_quarter", final="place", conf=0.9):
        self.a = dict(plus_ev=noul, trust=trust, sizing=sizing, final=final)
        self.conf, self.calls, self.states = conf, [], []

    def system_one(self, state, questions, model):
        (layer,) = questions
        self.calls.append(layer)
        self.states.append(state)
        if layer == "plus_ev":
            return NS(model=model, nouls={layer: NS(noul=self.a[layer])})
        return NS(model=model, choices={layer: NS(choice=self.a[layer], confidence=self.conf, probabilities={})})


def ask_for(tmp_path, fake, budget=100):
    return D.Asker(fake, "m", tmp_path, budget)


def test_state_hides_names_and_outcomes():
    s = D.line_state(PRICED["lines"][0])
    assert "SECRET" not in json.dumps(s) and "result" not in s and s["ev_fair"] == 0.2


def test_eligibility_and_join():
    rows = D.join(PRICED, SETTLED)
    assert [r["ok"] for r in rows] == [True, True, False, True]
    assert rows[3]["profit"] is None and rows[0]["profit"] == 2.0


def test_stake_routines():
    assert D.stake("flat_1u", 0.4, 3.0) == 1.0
    assert D.stake("kelly_eighth", 0.4, 3.0) == pytest.approx(100 * 0.125 * 0.1, abs=1e-4)
    assert D.stake("kelly_half", 0.9, 3.0) == D.STAKE_CAP          # capped
    assert D.stake("kelly_quarter", 0.3, 3.0) == 0.0               # not +EV at p


def test_full_chain_places_and_scores(tmp_path):
    fake = Fake()
    res = D.run(PRICED, SETTLED, ask_for(tmp_path, fake))
    assert res["funnel"]["placed"] == 3 and res["funnel"]["asked_final"] == 3
    assert res["jev"]["bets"] == 2 and res["unsettled"] == 1          # pending line excluded from P&L
    assert "c" in res["skipped"]
    assert fake.calls[:4] == list(D.LAYERS)


def test_gates_stop_chain(tmp_path):
    res = D.run(PRICED, SETTLED, ask_for(tmp_path, Fake(noul=0.2)))
    assert res["stopped_at"] == {"plus_ev": 3} and res["funnel"]["asked_trust"] == 0 and res["funnel"]["placed"] == 0
    res = D.run(PRICED, SETTLED, ask_for(tmp_path / "x", Fake(trust="neither")))
    assert res["stopped_at"] == {"trust": 3}
    res = D.run(PRICED, SETTLED, ask_for(tmp_path / "y", Fake(final="pass")))
    assert res["stopped_at"] == {"final": 3} and res["jev"]["bets"] == 0
    res = D.run(PRICED, SETTLED, ask_for(tmp_path / "z", Fake(conf=0.1)))
    assert res["stopped_at"] == {"trust": 3}


def test_cache_warm_start_and_budget(tmp_path):
    fake = Fake()
    first = D.run(PRICED, SETTLED, ask_for(tmp_path, fake, budget=5))
    assert first["halted"].startswith("BudgetExhausted") and len(fake.calls) == 5
    fake2 = Fake()
    again = D.run(PRICED, SETTLED, ask_for(tmp_path, fake2))              # resumes: the first 5 are cached
    assert again["halted"] is None and len(fake2.calls) == 12 - 5
    fake3 = Fake()
    D.run(PRICED, SETTLED, ask_for(tmp_path, fake3, budget=0))
    assert fake3.calls == []


def test_cache_only_without_client_halts(tmp_path):
    res = D.run(PRICED, SETTLED, D.Asker(None, "m", tmp_path, 0))
    assert res["halted"].startswith("MissingCache") and res["funnel"]["scored"] == 0


def test_plan_and_baselines(tmp_path):
    p = D.plan(PRICED, "m", tmp_path, 10)
    assert p["eligible_lines"] == 3 and p["layer1_calls"] == 3 and p["max_calls"] == 12 and p["budget_covers_layer1"]
    b = D.baselines(D.join(PRICED, SETTLED))
    assert b["take_all_flat_1u"]["bets"] == 2 and b["take_all_flat_1u"]["profit"] == 1.0


def test_dry_run_writes_nothing(tmp_path, capsys):
    from scripts.research import jev_book_demo as S
    pj = tmp_path / "p.json"
    pj.write_text(json.dumps(PRICED))
    out = tmp_path / "out"
    before = sorted(tmp_path.rglob("*"))
    assert S.main(["--priced", str(pj), "--dry-run", "--out", str(out), "--cache-dir", str(tmp_path / "c")]) == 0
    assert json.loads(capsys.readouterr().out)["eligible_lines"] == 3
    assert sorted(tmp_path.rglob("*")) == before


def test_report_renders(tmp_path):
    res = D.run(PRICED, SETTLED, ask_for(tmp_path, Fake()))
    text = D.format_report(res)
    assert "## Funnel" in text and "jev chain" in text and "SECRET" not in text


def test_fill_pm_uses_only_trades_before_asof():
    leg = {"side": "yes", "quotes": [{"token_id": "T"}]}
    now = {"lines": [{"id": "a", "legs": [leg]}]}
    priced = {"lines": [{"id": "a", "status": "mapped", "legs": [{"side": "yes"}], "decimal_odds": 4.0, "market_prob": None}]}
    trades = [{"token_id": "T", "ts": "2026-10-04 10:00:00+00:00", "price": "0.20"},
              {"token_id": "T", "ts": "2026-10-09 10:00:00+00:00", "price": "0.90"}]
    out, n = D.fill_pm(priced, now, trades, "2026-10-06T05:33Z")
    assert n == 1 and out["lines"][0]["market_prob"] == 0.2 and out["lines"][0]["ev_market"] == pytest.approx(-0.2)


def test_no_pm_mode(tmp_path):
    priced = {"lines": [dict(r, market_prob=None) for r in PRICED["lines"]]}
    assert D.plan(priced, "m", tmp_path, 10)["eligible_lines"] == 0
    assert D.plan(priced, "m", tmp_path, 10, need_pm=False)["eligible_lines"] == 3
    s = D.line_state(priced["lines"][0])
    assert "pm_price" not in s and "ev_pm" not in s
    assert "trust_pm" not in D.question("trust", s)["criteria"] and "trust_pm" in D.question("trust", {"pm_price": 1})["criteria"]
    fake = Fake()
    res = D.run(priced, SETTLED, ask_for(tmp_path, fake), need_pm=False)
    assert res["funnel"]["placed"] == 3
