"""`racinglines book render` and `book new --from-text` (racinglines/books/render.py, docs/sportsbook/render.md), with no
database: a synthetic `book price --json` result (F1-shaped h2h and winner lines, one tight Kalshi quote per line, one
wide Polymarket quote, one unmapped line) and a synthetic cycling price output. Every name, odds, price, run id and time
here is made up; none is a real result."""

import json
import struct
import zlib

import pytest

from racinglines.books import render as R
from racinglines.books import schema as S

pytestmark = pytest.mark.quick


def _q(exchange, bid, ask, synced="2026-10-09T11:50Z"):
    return dict(exchange=exchange, link_id=1, token_id="tok", prob=(bid + ask) / 2, bid=bid, ask=ask, closed=False,
                synced_utc=synced)


def _line(i, lid, title, sel, odds, kind, model, quotes, opponent=None, box=None, status="mapped", reason=None):
    leg = dict(line=i, leg=str(i), status=status, kind=kind, athlete=sel, opponent=opponent, event="Synthetic GP",
               run_id=1 if status == "mapped" else None, run_source="live forecast" if status == "mapped" else None,
               model_prob=model, quotes=quotes)
    return dict(line=i, id=lid, title=title, selection=sel, kind=kind, status=status, reason=reason, n_legs=1,
                odds=odds, decimal_odds=odds, book_prob=1 / odds, model_prob=model, flags=[], box=box,
                legs=[leg] if status == "mapped" else [])


PRICED = dict(
    book=dict(venue="book_x", event="2026-90", sport="f1", captured_utc="2026-10-09T11:00Z", odds="decimal",
              currency="USD"),
    lines=[
        _line(1, "h2h-ann", "Head to Head", "Ann Alpha", 2.0, "race_h2h", 0.60, [_q("kalshi", 0.54, 0.58)],
              opponent="Bea Beta", box=[20, 100, 600, 60]),
        _line(2, "h2h-bea", "Head to Head", "Bea Beta", 1.7, "race_h2h", 0.40, [_q("kalshi", 0.42, 0.46)],
              opponent="Ann Alpha", box=[20, 160, 600, 60]),
        _line(3, "win-cid", "Race Winner", "Cid Cee", 6.0, "race_win", 0.22, [_q("polymarket", 0.08, 0.30)]),
        _line(4, "win-ann", "Race Winner", "Ann Alpha", 3.2, "race_win", 0.40,
              [_q("polymarket", 0.30, 0.45, "2026-10-09T11:55Z"), _q("kalshi", 0.36, 0.40)]),
        _line(5, "win-dee", "Race Winner", "Dee Delta", 11.0, "race_win", 0.10, [_q("kalshi", 0.095, 0.105)]),
        _line(6, "win-eve", "Race Winner", "Eve Echo", 41.0, "race_win", 0.03, [_q("kalshi", 0.024, 0.028)]),
        _line(7, "rain", "Will it rain?", "Yes", 1.9, None, None, [], status="unmapped",
              reason="the book file marks this line unmapped"),
    ],
    unmapped=["rain"], assumptions=[], blend="none")


def _png(path, w=640, h=480):
    """A plain dark PNG of w x h (a stand-in screenshot)."""
    raw = b"".join(b"\x00" + b"\x10\x14\x19" * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
                     chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


@pytest.fixture()
def st():
    return R.load_settings()


@pytest.fixture()
def rows(st):
    return R.rows_from_priced(json.loads(json.dumps(PRICED)), st)


def _by(sized):
    return {r["id"]: r for r in sized}


def test_market_pick_tightest_two_sided(rows):
    meta, rs = rows
    r = _by(rs)
    assert r["win-ann"]["market_exchange"] == "kalshi" and r["win-ann"]["market_prob"] == pytest.approx(0.38)
    assert r["win-cid"]["market_prob"] is None                       # Polymarket 0.08/0.30: spread 22 points
    assert meta["models"] == ["run 1 (live forecast)"]
    assert meta["syncs"] == {"kalshi": "2026-10-09T11:50Z", "polymarket": "2026-10-09T11:55Z"}


def test_v2_rule_and_cap(rows, st):
    sized, summ = R.size(rows[1], st)
    r = _by(sized)
    k = {"h2h-ann": 1000 * 0.5 * (0.56 * 2.0 - 1) / 1.0,             # 60.00
         "win-ann": 1000 * 0.5 * (0.38 * 3.2 - 1) / 2.2,             # 49.09
         "win-dee": 1000 * 0.5 * (0.10 * 11 - 1) / 10,               # 5.00
         "win-eve": 1000 * 0.5 * (0.026 * 41 - 1) / 40}              # 0.83 -> the $1 floor
    for lid, v in k.items():
        assert r[lid]["kelly_stake"] == pytest.approx(v)
    assert summ["capped"]
    scale = 99 / (k["h2h-ann"] + k["win-ann"] + k["win-dee"])       # $1 kept for the floor line, the rest scaled to 99
    assert r["win-eve"]["stake"] == 1.0
    for lid in ("h2h-ann", "win-ann", "win-dee"):
        assert r[lid]["stake"] == pytest.approx(round(k[lid] * scale, 2))
        assert r[lid]["verdict"] == "BET"
    assert summ["total"] == pytest.approx(100.0, abs=0.02) and summ["n_bets"] == 4
    assert r["h2h-bea"]["verdict"] == "PASS" and "EV vs model" in r["h2h-bea"]["note"]
    assert r["win-cid"]["verdict"] == "PASS" and r["win-cid"]["note"].startswith("no market price")
    assert r["rain"]["verdict"] == "–" and r["rain"]["note"].startswith("unmapped")
    assert r["h2h-ann"]["ev_model"] == pytest.approx(0.2) and r["h2h-ann"]["ev_market"] == pytest.approx(0.12)


def test_min_ev_against_market_blocks(st):
    st["stake"]["min_ev"] = 0.15                                     # h2h-ann: EV 20% on the model, 12% on the market
    sized, _ = R.size(R.rows_from_priced(PRICED, st)[1], st)
    assert _by(sized)["h2h-ann"]["verdict"] == "PASS"
    assert "EV vs market +12.0% < 15.0%" in _by(sized)["h2h-ann"]["note"]


def test_scale_and_drop_under(rows):
    st = R.load_settings(dict(scale=0.1, drop_under=0.5))
    sized, summ = R.size(rows[1], st)
    r = _by(sized)
    assert r["h2h-ann"]["stake"] == pytest.approx(5.21, abs=0.01) and r["win-ann"]["stake"] == pytest.approx(4.26, abs=0.01)
    for lid in ("win-dee", "win-eve"):                               # $4.34 and $1 x 0.1 are under $0.50
        assert r[lid]["stake"] == 0 and r[lid]["verdict"] == "PASS" and "under $0.50" in r[lid]["note"]
    assert summ["n_bets"] == 2


def test_no_cap_when_under(st):
    st["stake"]["cap"] = 1000
    sized, summ = R.size(R.rows_from_priced(PRICED, st)[1], st)
    assert not summ["capped"] and _by(sized)["h2h-ann"]["stake"] == 60.0


def test_unknown_override(st):
    with pytest.raises(R.RenderError):
        R.load_settings(dict(nope=1))


def test_ticks_and_min_odds(rows, st):
    r = _by(rows[1])
    assert R.ticks(r["win-ann"], st) == [("kalshi", pytest.approx(0.38))]          # Polymarket's 15-point spread: no tick
    assert R.ticks(r["win-cid"], st) == []
    assert R.min_odds(r["win-ann"], st) == pytest.approx(1.05 / 0.38)
    assert R.min_odds(r["win-cid"], st) == pytest.approx(1.05 / 0.22)               # the model alone
    assert R.min_odds(r["h2h-ann"], st) == pytest.approx(1.05 / 0.56)


def test_hud_box_and_side_panel(rows, st, tmp_path):
    meta, rs = rows
    page, _, _ = R.render(meta, rs, "hud", st, image=_png(tmp_path / "shot.png"))
    assert page.count('class="box ') == 2
    assert 'left:20px;top:100px;width:600px;height:60px' in page
    side = page.split('class="side"')[1]
    for sel in ("Cid Cee", "Dee Delta", "Eve Echo"):
        assert sel in side
    assert "data:image/png;base64," in page and 'width:1100px' in page          # 640 + the 460 px side panel
    with pytest.raises(R.RenderError):
        R.render(meta, rs, "hud", st)


def test_card_and_footer(rows, st):
    meta, rs = rows
    page, _, _ = R.render(meta, rs, "card", st)
    for s in ("calibration unvalidated", "Not betting advice", "racinglines.bet", "run 1 (live forecast)",
              "Kalshi 2026-10-09T11:50Z", "Our prices on this board", "$52.06"):
        assert s in page


def test_agnostic_has_no_book(rows, st):
    meta, rs = rows
    page, _, _ = R.render(meta, rs, "agnostic", st)
    assert "Matchups and potential winners to watch" in page
    for s in ("book_x", "BET", "PASS", "stake", "Kelly", "EV", "3.20", "Will it rain"):
        assert s not in page
    assert "2.76" in page and "calibration unvalidated" in page                     # min odds for Ann to win


def test_cycling_adapter(tmp_path, st):
    (tmp_path / "futures.csv").write_text(
        "rider,results,gc,on_start_list,win_p,fair,book,edge,top3_p,top10_p,out_p\n"
        "Rider A,20,0,True,0.25,4.0,5.0,0.25,0.5,0.8,0.05\nRider B,12,0,True,0.10,10.0,,,0.3,0.6,0.08\n")
    (tmp_path / "matchups.csv").write_text(
        "a,a_odds,a_p,a_edge,b,b_odds,b_p,b_edge,both_out_p,results\nRider A,1.8,0.62,0.116,Rider B,2.0,0.38,-0.24,0.01,12\n")
    (tmp_path / "settings.csv").write_text("noise_scale,incident_scale\n1.0,1.0\n")
    meta, rs = R.rows_from_cycling(tmp_path)
    assert [r["id"] for r in rs] == ["win-Rider A", "win-Rider B", "h2h-Rider A-Rider B", "h2h-Rider B-Rider A"]
    assert rs[2]["opponent"] == "Rider B" and rs[2]["model_prob"] == 0.62 and rs[3]["decimal_odds"] == 2.0
    assert meta["syncs"] == {} and "noise_scale=1" in meta["models"][0]
    sized, summ = R.size(rs, st)
    assert summ["n_bets"] == 0                                        # no exchange lists it: the rule needs a market
    assert _by(sized)["win-Rider A"]["note"] == "no market price: no bet under the rule"
    assert _by(sized)["win-Rider B"]["note"] == "no book odds"
    page, _, _ = R.render(meta, rs, "agnostic", st)
    assert "Rider A" in page and "Markets: no exchange quote" in page
    st["stake"]["require"] = ["model"]                                # the rule is data: model-only sizing
    sized, summ = R.size(rs, st)
    assert _by(sized)["win-Rider A"]["stake"] > 0


def test_parse_text_decimal():
    text = "Race Winner:\nAnn Alpha 4.35\nHead to Head:\nAnn Alpha over Bea Beta 1.57\nCid Cee vs Dee Delta 1.57 2.25\n" \
           "garbage line\nEve Echo 0.9\n"
    lines, bad = R.parse_text(text, "decimal")
    assert [(ln["title"], ln["selection"], ln["odds"]) for ln in lines] == [
        ("Race Winner", "Ann Alpha", 4.35), ("Head to Head", "Ann Alpha", 1.57),
        ("Head to Head", "Cid Cee", 1.57), ("Head to Head", "Dee Delta", 2.25)]
    assert lines[3]["parsed"] == "h2h: Dee Delta over Cid Cee"
    assert [(n, why.split(" (")[0]) for n, _, why in bad] == [(6, "no pattern matched"), (7, "odds are not valid decimal odds")]


def test_parse_text_american_and_book_file(tmp_path):
    lines, bad = R.parse_text("Ann Alpha +150\nBea Beta -118\nCid Cee 150\n", "american")
    assert [ln["odds"] for ln in lines] == [150, -118] and bad[0][0] == 3
    txt = R.book_toml(lines, bad, "book_x", "2026-90", "american", sport="f1", captured_utc="2026-10-09T11:00Z")
    p = tmp_path / "b.toml"
    p.write_text(txt)
    book = S.load_book(p)
    assert [ln["market"] for ln in book["lines"]] == ["unmapped", "unmapped"]
    assert "line 3: Cid Cee 150" in txt


def test_book_box_validation():
    base = dict(book=dict(venue="book_x", event="2026-90", captured_utc="2026-10-09T11:00Z", source="screenshot",
                          odds="decimal", currency="USD", image="shot.png"),
                lines=[dict(title="T", selection="A", odds=2.0, market="unmapped", box=[1, 2, 3, 4])])
    S.validate_book(base)
    base["lines"][0]["box"] = [1, 2, 3]
    with pytest.raises(S.BookError, match="box"):
        S.validate_book(base)


def test_cli_render_json_in(tmp_path, capsys):
    from racinglines.cli import book as CLI
    src = tmp_path / "priced.json"
    src.write_text(json.dumps(PRICED))
    assert CLI.main(["render", "--json-in", str(src), "--style", "card", "--scale", "0.1", "--drop-under", "0.5"]) == 0
    out = capsys.readouterr().out
    assert "2 bets, $9.47" in out and (tmp_path / "priced-card.html").exists()
    assert CLI.main(["render", "--json-in", str(src), "--style", "hud"]) == 2              # no screenshot


def test_cli_new(tmp_path):
    from racinglines.cli import book as CLI
    t = tmp_path / "in.txt"
    t.write_text("Ann Alpha over Bea Beta 1.57\n")
    out = tmp_path / "b.toml"
    assert CLI.main(["new", "--from-text", str(t), "--venue", "book_x", "--event", "2026-90", "--out", str(out)]) == 0
    assert S.load_book(out)["lines"][0]["selection"] == "Ann Alpha"
    assert CLI.main(["new", "--from-text", str(t), "--venue", "book_x", "--event", "2026-90", "--out", str(out)]) == 2
