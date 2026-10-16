"""Synthetic tests for the Jev desk trader core and CLI: no DB, no network, a stub universe."""
import importlib.util
import json
import math
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from racinglines.research import jev_trader as T

ROOT = Path(__file__).resolve().parents[1]


class StubView:
    def __init__(self, round_no, ids, packages):
        self.round_no, self.shortlist_ids, self.packages = round_no, list(ids), packages


class StubUniverse:
    """Matches the Universe interface. rets[(sid, year)] = {round: float|None}; total() treats None as 0."""

    def __init__(self, rets, profile_a=None, canary_digits=None, untuned=(), short=None):
        self.rets, self.profile_a, self._untuned, self._short = rets, profile_a, set(untuned), short
        self.ids = sorted({s for s, _ in rets})
        self._rounds = sorted({r for (s, y), d in rets.items() if y == 2026 for r in d})

    def rounds(self, year):
        return list(self._rounds) if year == 2026 else []

    def ret(self, sid, year, rnd):
        return self.rets.get((sid, year), {}).get(rnd)

    def total(self, sid, year, upto=None):
        d = self.rets.get((sid, year), {})
        return sum((v or 0.0) for r, v in d.items() if upto is None or r < upto)

    def describe(self, sid):
        sizing = "Kelly fraction 0.25" if sid == "B" else "flat stake"      # the real Universe.describe() format
        return f"variant gridq+pretrain+reset, update mode, {sizing}, venue polymarket, min edge 0.1, n_sims 16000"

    def find_profile_a(self):
        return self.profile_a

    def untuned_ids(self):
        return set(self._untuned)

    def meta(self):
        return {"stub": True}

    def canaries(self, round_no):
        return {repr(v) for s in self.ids for r, v in self.rets.get((s, 2026), {}).items()
                if r >= round_no and v is not None and len(repr(v)) >= 8}

    def view(self, round_no):
        past = {s: {r: v for r, v in self.rets.get((s, 2026), {}).items() if r < round_no} for s in self.ids}
        return StubView(round_no, self.ids if self._short is None else self._short, {"event": {"round": round_no}, "family_summary": {},
                                             "shortlist": [{"id": s, "so_far": past[s]} for s in self.ids],
                                             "notes": {}})


def hand_universe(profile_a="A"):
    return StubUniverse({
        ("A", 2025): {1: 0.2, 2: 0.3}, ("B", 2025): {1: 0.1, 2: 0.1}, ("C", 2025): {1: 0.4, 2: 0.4},
        ("A", 2026): {1: 0.10, 2: 0.05, 3: None},
        ("B", 2026): {1: 0.0, 2: -0.2, 3: 0.5},
        ("C", 2026): {1: -0.1, 2: 0.1, 3: 0.0},
    }, profile_a=profile_a)


def fixed_ask(seq):
    it = iter(seq)

    def ask(state, options):
        c = next(it)
        return {"choice": c, "probabilities": {o: (1.0 if o == c else 0.0) for o in options}}
    return ask


# ---------------------------------------------------------------- lot loop

def test_lot_loop_argmax_and_20_calls():
    u, calls = hand_universe(), []

    def ask(state, options):
        calls.append((state["lots_left"], dict(state["table_so_far"])))
        assert options == ["A", "B", "C", T.CASH]
        return {"choice": "A", "probabilities": {"A": 0.1, "B": 0.5, "C": 0.2, "CASH": 0.2}}

    table, tr = T.allocate_week(u.view(1), u.canaries(1), 10000, ask)
    assert len(calls) == 20 and len(tr) == 20
    assert table == {"B": 20}                       # argmax of the probabilities beats the stated choice
    assert [c[0] for c in calls] == list(range(20, 0, -1))
    assert calls[5][1] == {"B": 5}
    assert sum(table.values()) == 20


def test_ties_go_to_earlier_option_and_cash_allowed():
    u = hand_universe()
    tie = lambda s, o: {"choice": "CASH", "probabilities": {k: 0.25 for k in o}}
    table, _ = T.allocate_week(u.view(1), set(), 10000, tie)
    assert table == {"A": 20}
    cash = lambda s, o: {"choice": "CASH", "probabilities": {"CASH": 0.9, "A": 0.1}}
    table, tr = T.allocate_week(u.view(1), set(), 10000, cash)
    assert table == {"CASH": 20} and tr[0]["probabilities"]["CASH"] == 0.9
    mixed = fixed_ask(["A"] * 7 + ["CASH"] * 13)
    table, _ = T.allocate_week(u.view(1), set(), 10000, mixed)
    assert table == {"A": 7, "CASH": 13}


def test_state_has_no_current_or_later_return_and_guard_fires():
    u = StubUniverse({("A", 2025): {1: 0.1}, ("A", 2026): {1: 0.123456789012345, 2: 0.0987654321098765}})
    st = T.lot_state(u.view(2), 10000, {"A": 3})
    blob = json.dumps(st)
    assert "0.0987654321098765" not in blob            # round 2 itself
    assert "0.123456789012345" in blob                  # round 1 is the past
    T.guard(st, u.canaries(2))                          # clean
    st["packages"]["notes"] = {"oops": "0.0987654321098765"}
    with pytest.raises(RuntimeError, match="leak guard"):
        T.guard(st, u.canaries(2))
    with pytest.raises(RuntimeError):
        T.allocate_week(StubView(2, ["A"], st["packages"]), u.canaries(2), 10000, fixed_ask(["A"] * 20))
    assert list(st) == ["bankroll", "lot_pct", "lots_left", "table_so_far", "packages"]


def test_question_has_no_advice_and_maps_options():
    q = T.question(["S1", "CASH"])["lot"]
    assert q["type"] == "choice" and q["criteria"] == {"S1": "strategy S1", "CASH": "keep this lot in cash"}
    for w in ("diversif", "steady", "concentrat", "avoid", "prefer", "good strategy", "risk"):
        assert w not in q["instructions"].lower()
    with pytest.raises(ValueError):
        T.question([f"S{i}" for i in range(256)])


# ---------------------------------------------------------------- accounting

@pytest.mark.parametrize("bank", [10000.0, 20000.0])
def test_accounting_hand_computed(bank):
    u = hand_universe()
    tables = {1: {"A": 10, "CASH": 10}, 2: {"B": 20}, 3: {"A": 10, "B": 10}}
    acc = T.account(u, tables, [1, 2, 3], bank)
    k = bank / 10000.0
    assert acc["path"] == pytest.approx([bank, 10500 * k, 8400 * k, 10500 * k])
    assert [w["pnl"] for w in acc["weekly"]] == pytest.approx([500 * k, -2100 * k, 2100 * k])
    assert acc["missing"] == 1                          # A in week 3 has no return: counts 0, tallied
    assert acc["weekly"][2]["rows"][0]["pnl"] == 0.0
    assert acc["weekly"][0]["ret"] == pytest.approx(0.05)   # cash earns 0


# ---------------------------------------------------------------- baselines

def test_baselines():
    u = hand_universe()
    bt = T.baseline_tables(u, [1, 2, 3])
    assert bt["B1"] == {r: {"C": 20} for r in (1, 2, 3)}                      # best 2025 total
    assert bt["B2"] == {1: {"C": 20}, 2: {"A": 20}, 3: {"A": 20}}              # 2025 total in week 1, then trailing
    assert bt["B3"][1] == {s: pytest.approx(20 / 3) for s in "ABC"}
    assert bt["B4"] == {r: {"A": 20} for r in (1, 2, 3)}
    assert bt["B5"] == {1: {"A": 20}, 2: {"C": 20}, 3: {"B": 20}}              # hindsight each week
    assert bt["B6"] == {r: {"B": 20} for r in (1, 2, 3)}                       # hindsight season (B total 0.3)
    assert "B4" not in T.baseline_tables(hand_universe(profile_a=None), [1, 2, 3])
    b3 = T.account(u, bt["B3"], [1, 2, 3], 10000)
    assert b3["weekly"][0]["ret"] == pytest.approx((0.10 + 0.0 - 0.1) / 3)
    assert b3["missing"] == 1


# ---------------------------------------------------------------- CI and decision

def _season(n, good, seed=0):
    rng = random.Random(seed)
    rets = {}
    for s in "ABCDE":
        rets[(s, 2025)] = {r: rng.gauss(0, 0.02) for r in range(1, n + 1)}
        rets[(s, 2026)] = {r: rng.gauss(0, 0.02) for r in range(1, n + 1)}
    if good:
        rets[("G", 2025)] = {r: -0.05 for r in range(1, n + 1)}      # worst in 2025, so B1 never picks it
        rets[("G", 2026)] = {r: 0.05 + 0.002 * (r % 3) for r in range(1, n + 1)}
    return StubUniverse(rets)


def test_planted_advantage_lower_ci_positive():
    u = _season(16, good=True)
    rounds = u.rounds(2026)
    res = T.analyse(u, rounds, {r: {"G": 20} for r in rounds}, 10000)
    assert res["diff"]["B1"][1][0] > 0 and res["beats"]["B1"] == "YES"
    assert res["beats"]["B3"] == "YES"
    text = T.format_report(res)
    assert "beats B1: YES" in text and "adds value over simple rules:" in text
    assert text.rstrip().endswith(T.NOT_SHOWN[-1])


def test_noise_not_shown():
    u = _season(16, good=False, seed=3)
    rounds = u.rounds(2026)
    rng = random.Random(9)
    tables = {r: {rng.choice(u.ids): 20} for r in rounds}
    res = T.analyse(u, rounds, tables, 10000)
    assert res["adds_value"] == "NOT SHOWN"
    assert "adds value over simple rules: NOT SHOWN" in T.format_report(res)
    assert set(res["desc"]) == {"Jev", "B1", "B2", "B3", "B5", "B6", "B7"}      # B4 skipped, no profile A
    assert res["skipped"] == ["B4"]
    assert not math.isnan(res["table_stats"]["turnover"])


# ---------------------------------------------------------------- cache, client, CLI

def _fake_client(log):
    class C:
        def system_one(self, state, questions, model):
            log.append(1)
            ch = SimpleNamespace(choice="A", confidence=0.9, probabilities={"A": 0.7, "CASH": 0.3})
            return SimpleNamespace(choices={"lot": ch}, model="jev-1.0",
                                   usage=SimpleNamespace(input_tokens=11, output_tokens=2))
    return C()


def test_cache_hit_on_repeated_state(tmp_path):
    log = []
    st = T.lot_state(hand_universe().view(1), 10000, {})
    a = T.ask_choice(st, ["A", "CASH"], client=_fake_client(log), cache_dir=tmp_path)
    b = T.ask_choice(st, ["A", "CASH"], client=None, cache_dir=tmp_path)    # no client needed on a hit
    assert len(log) == 1 and a["cached"] is False and b["cached"] is True
    assert b["probabilities"] == {"A": 0.7, "CASH": 0.3} and b["usage"] == {"input_tokens": 11, "output_tokens": 2}
    assert b["answered_by"] == "jev-1.0"
    T.ask_choice(T.lot_state(hand_universe().view(1), 10000, {"A": 1}), ["A", "CASH"], client=_fake_client(log),
                 cache_dir=tmp_path)
    assert len(log) == 2                                                    # a different state is a miss
    T.ask_choice(st, ["A", "CASH"], client=_fake_client(log), model="other", cache_dir=tmp_path)
    assert len(log) == 3                                                    # so is a different model


def _load_cli():
    spec = importlib.util.spec_from_file_location("jev_trader_cli", ROOT / "scripts" / "research" / "jev_trader.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_dry_run_makes_no_client_and_no_network(tmp_path):
    cli, lines = _load_cli(), []

    def boom():
        raise AssertionError("client requested on a dry run")

    res = cli.run_trader(hand_universe(), bankroll=10000, dry_run=True, cache_dir=tmp_path, out_dir=tmp_path / "o",
                         client_factory=boom, confirm=boom, out=lines.append)
    assert res is None and not (tmp_path / "o").exists()
    assert any("3 weeks x 20 lots = 60 requests; 0 cached" in x and "60 to make" in x for x in lines)
    assert "typesafe_sdk" not in sys.modules


def test_full_run_with_fake_client_writes_outputs(tmp_path):
    cli, log, lines = _load_cli(), [], []
    res = cli.run_trader(hand_universe(), bankroll=10000, yes=True, cache_dir=tmp_path / "c", out_dir=tmp_path / "o",
                         client_factory=lambda: _fake_client(log), out=lines.append, argv=["x"])
    assert len(log) == 60 and res["jev"]["weekly"][0]["rows"][0]["sid"] == "A"
    for f in ("results.txt", "weeks.csv", "transcript.jsonl", "SOURCES.md"):
        assert (tmp_path / "o" / f).exists()
    assert len((tmp_path / "o" / "transcript.jsonl").read_text().splitlines()) == 60
    assert any("tokens: input 660 output 120" in x for x in lines)
    # second run replays from the cache: zero API calls
    cli.run_trader(hand_universe(), bankroll=10000, yes=True, cache_dir=tmp_path / "c", out_dir=tmp_path / "o",
                   client_factory=lambda: _fake_client(log), out=lines.append, argv=["x"])
    assert len(log) == 60


def test_breakdown_reads_the_real_describe_strings():
    assert T._attrs("variant v, hold mode, Kelly fraction 0.5, venue kalshi, n_sims 16000") == ("hold", "kelly")
    assert T._attrs("variant v, early mode, flat stake, venue polymarket") == ("early", "flat")
    assert T._attrs(None) == ("?", "flat")


def test_b7_is_equal_weight_over_each_weeks_own_shortlist_and_gates_adds_value():
    u = _season(8, good=True, seed=2)
    rounds = u.rounds(2026)
    bt = T.baseline_tables(u, rounds)
    for r in rounds:
        sl = u.view(r).shortlist_ids
        assert set(bt["B7"][r]) == set(sl) and all(abs(v - 20 / len(sl)) < 1e-12 for v in bt["B7"][r].values())
        assert abs(sum(bt["B7"][r].values()) - 20) < 1e-9
    # B7 is part of the decision: a Jev that only matches the shortlist's equal-weight does not "add value"
    res = T.analyse(u, rounds, bt["B7"], 10000)
    assert "B7" in T.DECISION_BASELINES and res["beats"]["B7"] == "NOT SHOWN" and res["adds_value"] == "NOT SHOWN"
    assert "beats B7: NOT SHOWN" in T.format_report(res)


# ---------------------------------------------------------------- static ranking

def static_universe(**kw):
    # A +10%/+10%, B flat, C -10%/-10%; D is a Kelly strategy (per the describe() stub, only the id "B" is Kelly)
    return StubUniverse({
        ("A", 2025): {1: 0.0}, ("B", 2025): {1: 0.0}, ("C", 2025): {1: 0.0}, ("D", 2025): {1: 0.0},
        ("A", 2026): {1: 0.10, 2: 0.10}, ("B", 2026): {1: 0.30, 2: 0.30},
        ("C", 2026): {1: -0.10, 2: -0.10}, ("D", 2026): {1: 0.0, 2: 0.0}}, **kw)


def test_static_rank_is_one_plus_number_better_and_drawdown_ranks_the_other_way():
    u, rounds = static_universe(), [1, 2]
    jev = {r: {"A": 10, "D": 10} for r in rounds}          # +5% a week: final 11,025
    st = T.static_ranking(u, rounds, 10000, jev)
    assert st["statics"]["A"]["final"] == pytest.approx(12100) and st["statics"]["B"]["final"] == pytest.approx(16900)
    g = st["groups"]["all"]
    assert g["n"] == 4
    assert g["ranks"]["final"] == 3                         # A and B are better
    assert g["ranks"]["weeks_up"] == 1 and g["ranks"]["worst_drawdown"] == 1   # ties are not "strictly better"
    # drawdown the other way: E ends higher than F but draws down; F is strictly lower on drawdown
    u2 = StubUniverse({("E", 2026): {1: 0.3, 2: -0.2}, ("F", 2026): {1: 0.0, 2: 0.0}})
    r2 = T.static_ranking(u2, rounds, 10000, {r: {"E": 20} for r in rounds})["groups"]["all"]["ranks"]
    assert r2["final"] == 1 and r2["worst_drawdown"] == 2 and r2["weeks_up"] == 1


def test_static_peer_groups_filter_correctly():
    u = static_universe(untuned={"C", "D", "Z"}, short=["A", "C"])
    jev = {r: {"A": 10, "D": 10} for r in [1, 2]}
    g = T.static_ranking(u, [1, 2], 10000, jev)["groups"]
    assert g["flat"]["n"] == 3 and g["flat"]["ranks"]["final"] == 2         # B is Kelly in the stub; only A beats Jev
    assert g["shortlisted"]["n"] == 2 and g["shortlisted"]["ranks"]["final"] == 2
    assert g["untuned"]["n"] == 2 and g["untuned"]["ranks"]["final"] == 1   # Z is not in the universe


def test_static_report_section_ranks_b_rules_top5_caveats_and_none_group():
    u, rounds = static_universe(), [1, 2]
    res = T.analyse(u, rounds, {r: {"A": 10, "D": 10} for r in rounds}, 10000)
    assert "static" in res
    b = res["static"]["b_rank"]
    assert set(b) == set(T.DECISION_BASELINES)
    assert b["B1"]["rank"] == 2 and b["B3"]["rank"] == 3 and b["B1"]["of"] == 5   # A is B1; only B beats it
    assert [t["sid"] for t in res["static"]["top5"]] == ["B", "A", "D", "C"]
    text = T.format_report(res)
    assert "JEV VS EVERY STATIC STRATEGY (hindsight leaderboard; descriptive, no decision attached)" in text
    assert "ranked with the whole season known, so only B1 and B2 were choosable in advance" in text
    assert "Kelly strategies dominate raw final bankroll" in text and "read the flat and untuned groups first" in text
    assert "group untuned: none in this universe" in text
    assert "rank 3 of 5 (top 60%)" in text
    for k in T.DECISION_BASELINES:
        assert T.BASELINE_NAMES[k] in text


def test_position_cap_removes_a_full_strategy_from_the_options_and_keeps_cash():
    # opt-in cap: once "A" holds max_lots, it is no longer offered; CASH always is
    u = hand_universe()
    seen = []

    def always_a(state, options):
        seen.append(list(options))
        if "A" in options:
            return {"choice": "A", "probabilities": {k: (0.9 if k == "A" else 0.05) for k in options}}
        return {"choice": "CASH", "probabilities": {k: (0.9 if k == "CASH" else 0.05) for k in options}}

    table, _ = T.allocate_week(u.view(1), set(), 10000, always_a, max_lots=5)
    assert table.get("A", 0) == 5 and table["CASH"] == 15
    assert "A" not in seen[-1] and T.CASH in seen[-1]          # the last request no longer offers A


def test_no_cap_is_identical_to_the_pre_registered_options():
    u = hand_universe()
    seen = []

    def record(state, options):
        seen.append(list(options))
        return {"choice": "A", "probabilities": {k: (0.9 if k == "A" else 0.05) for k in options}}

    T.allocate_week(u.view(1), set(), 10000, record)            # default: max_lots None
    assert all(o == ["A", "B", "C", T.CASH] for o in seen)
