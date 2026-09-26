"""
House markets: YES/NO markets we quote ourselves for private bets.

Prices are what the counterparty pays per $1 of payout:
    yes_price = fair + spread / 2          (they buy YES from us)
    no_price  = (1 - fair) + spread / 2    (they buy NO from us)
rounded UP to the cent, so rounding only ever widens our margin. A side isn't
offered if its price would be above MAX_PRICE (the payout would be too small
to be worth quoting, and we'd be close to giving away the other side).

Settlement:
    race_win / race_podium   Final results in the database (official ChronoRace).
    race_make_final          The athlete appears on the Final's start list or results.
    rank_up / rank_down      Manual, from the OFFICIAL UCI standings (our points
                             tables are placeholders, so the model's rank is only a hint).
"""

import math
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import select, text

from racedb import models as m

MAX_PRICE = 0.97
MIN_PRICE = 0.01

KINDS = {
    "race_win": "wins the {venue} {cat} Final",
    "race_podium": "finishes on the podium (top 3) in the {venue} {cat} Final",
    "race_make_final": "makes the {venue} {cat} Final",
    "rank_up": "is ranked higher than #{rank} in the {cat} championship after {venue}",
    "rank_down": "is ranked lower than #{rank} in the {cat} championship after {venue}",
}
PROB_FIELD = {"race_win": "win_prob", "race_podium": "podium_prob", "race_make_final": "make_final_prob",
              "rank_up": "rank_up_prob", "rank_down": "rank_down_prob"}
AUTO_SETTLE = ("race_win", "race_podium", "race_make_final")


def quote(fair, spread):
    """(yes_price, no_price); None for a side that isn't offered."""
    def side(p):
        price = math.ceil(round((p + spread / 2) * 100, 6)) / 100
        return price if MIN_PRICE <= price <= MAX_PRICE else None
    return side(fair), side(1 - fair)


def latest_race_predictions(conn, race_id):
    """Latest forecast run's per-athlete predictions for a race (incl. rank-move fields)."""
    df = pd.read_sql(text("""
        SELECT rp.model_run_id, rp.athlete_id, a.display_name AS athlete, rp.win_prob, rp.podium_prob,
               rp.make_final_prob, rp.extra
        FROM race_predictions rp JOIN athletes a ON a.id = rp.athlete_id
        WHERE rp.race_id = :race AND rp.model_run_id = (
            SELECT max(model_run_id) FROM race_predictions rp2 JOIN model_runs mr ON mr.id = rp2.model_run_id
            WHERE rp2.race_id = :race AND mr.kind = 'forecast')"""), conn, params=dict(race=race_id))
    if len(df):
        extra = pd.json_normalize(df.pop("extra").fillna({}).tolist())
        for c in ("rank_up_prob", "rank_down_prob", "current_rank", "exp_rank_after"):
            df[c] = extra[c].to_numpy() if c in extra else None
    return df


def race_label(session, race_id):
    race = session.get(m.Race, race_id)
    venue = race.event.venue.name if race.event.venue else race.event.name
    return venue, race.category.code


def generate(session, conn, race_id, kinds, top_n, spread):
    """Create markets for the top_n athletes (by win probability for race kinds,
    by current championship rank for rank kinds) and reprice open markets that
    still use the model price. Returns (created, repriced)."""
    preds = latest_race_predictions(conn, race_id)
    if preds.empty:
        raise ValueError("no forecast predictions for this race; run predictor.py season --db --save")
    venue, cat = race_label(session, race_id)
    created = repriced = 0
    for kind in kinds:
        if kind.startswith("rank"):
            pool = preds.dropna(subset=["current_rank"]).sort_values("current_rank").head(top_n)
        else:
            pool = preds.sort_values("win_prob", ascending=False).head(top_n)
        for r in pool.itertuples():
            fair = getattr(r, PROB_FIELD[kind])
            if fair is None or pd.isna(fair):
                continue
            fair = float(fair)
            ctx = {"current_rank": int(r.current_rank)} if kind.startswith("rank") and pd.notna(r.current_rank) else None
            mk = session.scalars(select(m.HouseMarket).filter_by(race_id=race_id, athlete_id=int(r.athlete_id),
                                                                  kind=kind)).first()
            if mk is None:
                title = f"{r.athlete} " + KINDS[kind].format(venue=venue, cat=cat, rank=(ctx or {}).get("current_rank"))
                yes, no = quote(fair, spread)
                session.add(m.HouseMarket(race_id=race_id, athlete_id=int(r.athlete_id), kind=kind, title=title,
                                          model_run_id=int(r.model_run_id), fair_prob=fair, spread=spread,
                                          yes_price=yes, no_price=no, context=ctx))
                created += 1
            elif mk.status == "open" and mk.fair_source == "model":
                mk.fair_prob, mk.spread, mk.model_run_id = fair, spread, int(r.model_run_id)
                mk.yes_price, mk.no_price = quote(fair, spread)
                repriced += 1
    session.commit()
    return created, repriced


def set_price(session, market_id, fair, spread):
    mk = session.get(m.HouseMarket, market_id)
    mk.fair_prob, mk.spread, mk.fair_source = fair, spread, "manual"
    mk.yes_price, mk.no_price = quote(fair, spread)
    session.commit()


def record_bet(session, market_id, counterparty, side, stake, price=None, note=None):
    mk = session.get(m.HouseMarket, market_id)
    if mk.status != "open":
        raise ValueError(f"market is {mk.status}")
    quoted = mk.yes_price if side == "YES" else mk.no_price
    price = price or quoted
    if price is None:
        raise ValueError(f"{side} is not offered on this market")
    if not (0 < price < 1) or stake <= 0:
        raise ValueError("price must be between 0 and 1 and stake positive")
    bet = m.HouseBet(market_id=market_id, counterparty=counterparty.strip(), side=side, price=price, stake=stake,
                     payout=round(stake / price, 2), note=note or None)
    session.add(bet)
    session.commit()
    return bet


def settle(session, market_id, outcome, note):
    """outcome: True (YES happened), False, or None to void (all stakes returned)."""
    mk = session.get(m.HouseMarket, market_id)
    mk.outcome = outcome
    mk.status = "void" if outcome is None else "settled"
    mk.settled_at = datetime.now(timezone.utc)
    mk.settle_note = note
    for bet in session.scalars(select(m.HouseBet).filter_by(market_id=market_id)):
        if outcome is None:
            bet.status = "void"
        else:
            bet.status = "won" if (bet.side == "YES") == outcome else "lost"
    session.commit()


def auto_settle(session, conn, race_id):
    """Settle open race_* markets for a race from its Final. Returns [(market_id, outcome, note)]."""
    fin = pd.read_sql(text("""
        SELECT r.athlete_id, r.position, r.status FROM results r JOIN rounds ro ON ro.id = r.round_id
        WHERE ro.race_id = :race AND ro.kind = 'final'"""), conn, params=dict(race=race_id))
    finished = fin[fin["status"] == "OK"]
    done = []
    for mk in session.scalars(select(m.HouseMarket).where(
            m.HouseMarket.race_id == race_id, m.HouseMarket.status.in_(["open", "closed"]),
            m.HouseMarket.kind.in_(AUTO_SETTLE))).all():
        row = fin[fin["athlete_id"] == mk.athlete_id]
        if mk.kind == "race_make_final":
            if len(fin) < 20:          # Final start list not published yet
                continue
            outcome, note = len(row) > 0, "Final start list/results"
        else:
            if len(finished) < 10:     # Final not raced yet
                continue
            pos = row["position"].iloc[0] if len(row) and pd.notna(row["position"].iloc[0]) else None
            limit = 1 if mk.kind == "race_win" else 3
            outcome = pos is not None and pos <= limit
            note = f"Final position {int(pos)}" if pos is not None else "not classified in the Final"
        settle(session, mk.id, outcome, f"auto: {note}")
        done.append((mk.id, outcome, note))
    return done


def book(conn, race_id=None):
    """Markets with bet totals and P&L if YES / if NO (our side), plus EV at fair."""
    df = pd.read_sql(text("""
        SELECT hm.*, a.display_name AS athlete,
               count(hb.id) FILTER (WHERE hb.status <> 'void') AS bets,
               coalesce(sum(hb.stake) FILTER (WHERE hb.status <> 'void'), 0) AS staked,
               coalesce(sum(CASE WHEN hb.side = 'YES' THEN hb.stake - hb.payout ELSE hb.stake END)
                        FILTER (WHERE hb.status <> 'void'), 0) AS pnl_if_yes,
               coalesce(sum(CASE WHEN hb.side = 'NO' THEN hb.stake - hb.payout ELSE hb.stake END)
                        FILTER (WHERE hb.status <> 'void'), 0) AS pnl_if_no
        FROM house_markets hm JOIN athletes a ON a.id = hm.athlete_id
        LEFT JOIN house_bets hb ON hb.market_id = hm.id
        WHERE (CAST(:race AS int) IS NULL OR hm.race_id = CAST(:race AS int))
        GROUP BY hm.id, a.display_name
        ORDER BY hm.kind, hm.fair_prob DESC"""), conn, params=dict(race=race_id))
    df["ev"] = df["fair_prob"] * df["pnl_if_yes"] + (1 - df["fair_prob"]) * df["pnl_if_no"]
    df["worst"] = df[["pnl_if_yes", "pnl_if_no"]].min(axis=1)
    df["settled_pnl"] = [(r.pnl_if_yes if r.outcome else r.pnl_if_no) if r.status == "settled" else None
                         for r in df.itertuples()]
    return df


def bets(conn, market_id):
    return pd.read_sql(text("SELECT * FROM house_bets WHERE market_id = :m ORDER BY id"), conn,
                       params=dict(m=market_id))
