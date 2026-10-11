"""`racinglines book export --ledger` (racinglines/books/ledger.py): a book's staked lines as ledger rows. The row builder
is tested on hand-made price and settle results (no database); the database round trip is in tests/test_book_slips.py.
Every venue, name and price here is made up."""

import csv
import tomllib

import pytest

from racinglines.books import ledger as L
from racinglines.books import schema as S

HEAD = """
[book]
venue = "examplebook"
event = "2026-17"
sport = "f1"
captured_utc = "2026-10-07T09:00:30Z"
source = "paste"
odds = "{odds}"
currency = "{currency}"
"""


def _book(odds, lines, currency="USD"):
    raw = HEAD.format(odds=odds, currency=currency) + "".join(
        "\n[[lines]]\n" + "\n".join(f"{k} = {v!r}" if isinstance(v, str) else f"{k} = {v}" for k, v in ln.items())
        + '\nmarket = { kind = "race_win", driver = "Ann Alpha" }\n' for ln in lines)
    return S.validate_book(tomllib.loads(raw))


def _leg(round_=17):
    return {"race_id": 1, "season": 2026, "round": round_, "sport": "f1", "event": "Testing GP"}


def _out(book, results, model=None):
    """price_book and settle_book shaped results: every line mapped to one race, with the given result and payout."""
    fmt = book["book"]["odds"]
    priced, settled = {"lines": []}, {"lines": []}
    for i, ln in enumerate(book["lines"]):
        result, payout = results[i]
        dec = round(1.0 / S.to_prob(ln["odds"], fmt), 4)
        base = {"id": ln.get("id", str(i + 1)), "title": ln["title"], "selection": ln["selection"], "status": "mapped",
                "reason": None, "legs": [_leg()], "decimal_odds": dec}
        priced["lines"].append(dict(base, model_prob=(model or {}).get(i), flags=[]))
        settled["lines"].append(dict(base, result=result, payout=payout))
    return priced, settled


def test_decimal_odds_from_american_and_fractional():
    for fmt, odds, dec in (("american", -118, "1.8475"), ("american", 150, "2.50"), ("fractional", "7/4", "2.75"),
                           ("decimal", 13.0, "13.00")):
        book = _book(fmt, [dict(id="a", title="Race Winner", selection="Ann Alpha", odds=odds, stake=10)])
        rows, _ = L.rows(book, *_out(book, [("won", float(dec))]))
        assert rows[0]["odds_taken"] == dec
        assert ("odds: " in rows[0]["notes"]) == (fmt != "decimal")


def test_payout_is_the_total_returned():
    book = _book("decimal", [dict(id=x, title="Race Winner", selection="Ann Alpha", odds=2.25, stake=4)
                             for x in ("won", "lost", "void", "pending", "manual")])
    rows, _ = L.rows(book, *_out(book, [("won", 2.25), ("lost", 0.0), ("void", 1.0), ("pending", None),
                                        ("manual", None)]))
    got = {r["notes"].split(";")[0][4:]: (r["result"], r["payout"]) for r in rows}
    assert got == {"won": ("won", "9.00"), "lost": ("lost", "0.00"), "void": ("void", "4.00"),
                   "pending": ("open", ""), "manual": ("open", "")}
    assert all(("settled: ours" in r["notes"]) == (r["result"] != "open") for r in rows)


def test_row_columns_dates_events_and_skipped_lines():
    book = _book("decimal", [dict(id="a", title="Race Winner", selection="Ann Alpha", odds=3.0, stake=5,
                                  placed_utc="2026-10-03T22:32Z"),
                             dict(id="b", title="Race Winner", selection="Ann Alpha", odds=3.0)])
    rows, skipped = L.rows(book, *_out(book, [("won", 3.0), ("won", 3.0)], model={0: 0.4}))
    assert skipped == ["b"] and len(rows) == 1
    r = rows[0]
    assert list(r) == list(L.LEDGER_COLUMNS)
    assert r | {"notes": ""} == dict(date_utc="2026-10-03T22:32Z", sport="f1", event="2026-17 Testing GP",
                                     venue="examplebook", market="Race Winner", selection="Ann Alpha", stake="5.00",
                                     currency="USD", odds_taken="3.00", our_fair_prob="0.40", closing_odds="",
                                     result="won", payout="15.00", follower="", notes="")


def test_unmapped_line_keeps_the_book_event_key_and_stays_open():
    book = _book("decimal", [dict(id="a", title="Race Winner", selection="Ann Alpha", odds=3.0, stake=5)])
    priced, settled = _out(book, [(None, None)])
    for o in (priced, settled):
        o["lines"][0].update(status="unmapped", reason="no f1 race", legs=[])
    r = L.rows(book, priced, settled)[0][0]
    assert (r["event"], r["result"], r["date_utc"]) == ("2026-17", "open", "2026-10-07T09:00Z")
    assert "unmapped: no f1 race" in r["notes"] and "the book's key 2026-17" in r["notes"]


def test_exchange_quotes_note_contracts_and_a_cents_book_stakes_in_dollars():
    book = _book("cents", [dict(id="k", title="Race Winner", selection="Ann Alpha", odds=40, stake=10)])
    r = L.rows(book, *_out(book, [("won", 2.5)]))[0][0]
    assert (r["odds_taken"], r["payout"], r["currency"]) == ("2.50", "25.00", "USD")
    assert "odds: 40 cents" in r["notes"] and "contracts: 25.00" in r["notes"]
    bad = _book("cents", [dict(id="k", title="Race Winner", selection="Ann Alpha", odds=40, stake=1000)],
                currency="cents")
    with pytest.raises(L.LedgerError, match="stakes are in USD"):
        L.rows(bad, *_out(bad, [("won", 2.5)]))
    pm = _book("dollars", [dict(id="p", title="Race Winner", selection="Ann Alpha", odds=0.25, stake=5)],
               currency="USDC")
    r = L.rows(pm, *_out(pm, [("lost", 0.0)]))[0][0]
    assert (r["odds_taken"], r["payout"], r["currency"]) == ("4.00", "0.00", "USDC")   # never converted


def test_schema_checks_stake_and_placed_utc():
    ok = dict(id="a", title="Race Winner", selection="Ann Alpha", odds=3.0)
    _book("decimal", [dict(ok, stake=2.5, placed_utc="2026-10-03T22:32Z")])
    for extra, field in ((dict(stake=0), "stake"), (dict(stake='"5"'), "stake"), (dict(stake="true"), "stake"),
                         (dict(placed_utc="unknown"), "placed_utc"), (dict(placed_utc="2026-10-03"), "placed_utc")):
        raw = HEAD.format(odds="decimal", currency="USD") + "\n[[lines]]\n" + "\n".join(
            f"{k} = {v!r}" if isinstance(v, str) and k != "stake" else f"{k} = {v}" for k, v in dict(ok, **extra).items()
        ) + '\nmarket = { kind = "race_win", driver = "Ann Alpha" }\n'
        with pytest.raises(S.BookError, match=f"lines\\[0\\].{field}"):
            S.validate_book(tomllib.loads(raw))


def test_write_csv_refuses_an_existing_file_and_never_appends(tmp_path):
    book = _book("decimal", [dict(id="a", title="Race Winner", selection="Ann Alpha", odds=3.0, stake=5)])
    rows, _ = L.rows(book, *_out(book, [("won", 3.0)]))
    out = tmp_path / "bets.csv"
    L.write_csv(rows, out)
    with pytest.raises(L.LedgerError, match="--force"):
        L.write_csv(rows, out)
    L.write_csv(rows + rows, out, force=True)
    with open(out, newline="") as f:
        got = list(csv.DictReader(f))
    assert len(got) == 2 and tuple(got[0]) == L.LEDGER_COLUMNS
