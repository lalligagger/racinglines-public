"""
SQLAlchemy models for the racinglines database (PostgreSQL).

Built for many sports and leagues, not just downhill:

    Sport            what is raced            mtb_dh (mountain bike downhill)
    League           who organizes it         uci_mtb (UCI Mountain Bike World Series)
    Competition      league x sport           uci_dhi_wc (UCI Downhill World Cup)
      Category       per competition          ME, MJ, WE, WJ
      Season         per competition          2026
        Event        one weekend / meeting    Les Gets 2026 (source key 20260821_mtb)
          Race       event x category         Les Gets 2026, Men Elite  (+ weekend format)
            Round    a session of the race    practice / qual1 / qual2 / final ...
              Result one athlete in a round   position, status, time
                Split intermediate times  cumulative time at split n

Athletes are global (one person can race several sports) and are matched
through AthleteIdentifier rows (scheme, value): "name" = normalized name key
today; "uci" (or any other federation / source ID) later.

Times are stored as integer milliseconds so nothing is lost to float rounding.
Anything sport-specific that doesn't deserve a column goes in a JSONB field
(Race.format, Result.extra, ModelRun.params / metrics, *.extra).
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Date, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Sport(Base):
    __tablename__ = "sports"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)          # mtb_dh
    name: Mapped[str] = mapped_column(String(120))                      # Mountain bike downhill
    result_kind: Mapped[str] = mapped_column(String(20), default="time", server_default="time")  # time | score | ...


class League(Base):
    __tablename__ = "leagues"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)          # uci_mtb
    name: Mapped[str] = mapped_column(String(200))
    organizer: Mapped[str | None] = mapped_column(String(120))          # UCI


class Competition(Base):
    """A league's championship in one sport, e.g. the UCI Downhill World Cup."""
    __tablename__ = "competitions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)          # uci_dhi_wc
    name: Mapped[str] = mapped_column(String(200))
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    sport_id: Mapped[int] = mapped_column(ForeignKey("sports.id"))

    league: Mapped[League] = relationship()
    sport: Mapped[Sport] = relationship()


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("competition_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"))
    code: Mapped[str] = mapped_column(String(20))                       # ME
    name: Mapped[str] = mapped_column(String(120))                      # Men Elite
    gender: Mapped[str | None] = mapped_column(String(1))               # M / W / X
    age_group: Mapped[str | None] = mapped_column(String(20))           # elite / junior / u23


class Season(Base):
    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("competition_id", "year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"))
    year: Mapped[int] = mapped_column(Integer)
    label: Mapped[str | None] = mapped_column(String(40))               # e.g. "2025/26" for winter sports


class Venue(Base):
    __tablename__ = "venues"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)          # les-gets
    name: Mapped[str] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(3))              # IOC/UCI code, FRA


class VenueAlias(Base):
    """Other spellings of a venue seen in source data -> the canonical venue."""
    __tablename__ = "venue_aliases"
    alias: Mapped[str] = mapped_column(String(80), primary_key=True)    # mont-ste-anne
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"))


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("season_id", "source", "source_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"))
    source: Mapped[str] = mapped_column(String(40))                     # chronorace
    source_key: Mapped[str] = mapped_column(String(80))                 # 20260821_mtb
    name: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    venue_id: Mapped[int | None] = mapped_column(ForeignKey("venues.id"))
    series_round: Mapped[int | None] = mapped_column(Integer)           # DHI #7
    status: Mapped[str] = mapped_column(String(20), default="completed", server_default="completed")  # scheduled | completed | cancelled

    season: Mapped[Season] = relationship()
    venue: Mapped[Venue | None] = relationship()


class Race(Base):
    """One category's race at an event. `format` holds the weekend format,
    e.g. {"kind": "q1q2", "q1_to_final": 20, "q2_to_final": 10}."""
    __tablename__ = "races"
    __table_args__ = (UniqueConstraint("event_id", "category_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    format: Mapped[dict | None] = mapped_column(JSONB)

    event: Mapped[Event] = relationship()
    category: Mapped[Category] = relationship()
    rounds: Mapped[list["Round"]] = relationship(back_populates="race", cascade="all, delete-orphan",
                                                 passive_deletes=True)


class Round(Base):
    __tablename__ = "rounds"
    __table_args__ = (UniqueConstraint("race_id", "kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))                       # practice | qual | qual1 | qual2 | semi | final
    ordinal: Mapped[int] = mapped_column(Integer)                       # running order within the race
    name: Mapped[str | None] = mapped_column(String(80))                # heading as published

    race: Mapped[Race] = relationship(back_populates="rounds")


class Athlete(Base):
    __tablename__ = "athletes"
    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    nation: Mapped[str | None] = mapped_column(String(3))
    birth_year: Mapped[int | None] = mapped_column(Integer)
    gender: Mapped[str | None] = mapped_column(String(1))


class AthleteIdentifier(Base):
    """How sources refer to an athlete: ("name", "o callaghan oisin"),
    ("uci", "10007307417"), ... One athlete can have many."""
    __tablename__ = "athlete_identifiers"
    scheme: Mapped[str] = mapped_column(String(20), primary_key=True)
    value: Mapped[str] = mapped_column(String(200), primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id", ondelete="CASCADE"), index=True)


class Result(Base):
    __tablename__ = "results"
    __table_args__ = (UniqueConstraint("round_id", "athlete_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id", ondelete="CASCADE"))
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"), index=True)
    position: Mapped[int | None] = mapped_column(Integer)               # official rank; null if not classified
    status: Mapped[str] = mapped_column(String(10))                     # OK | DNF | DNS | DSQ
    time_ms: Mapped[int | None] = mapped_column(BigInteger)
    bib: Mapped[str | None] = mapped_column(String(20))
    team: Mapped[str | None] = mapped_column(String(200))
    nation: Mapped[str | None] = mapped_column(String(3))
    extra: Mapped[dict | None] = mapped_column(JSONB)


class Split(Base):
    __tablename__ = "splits"
    result_id: Mapped[int] = mapped_column(ForeignKey("results.id", ondelete="CASCADE"), primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)         # 1..n
    cum_time_ms: Mapped[int | None] = mapped_column(BigInteger)
    rank: Mapped[int | None] = mapped_column(Integer)


class SourceFile(Base):
    """Every ingested file, so re-ingesting unchanged files is a no-op."""
    __tablename__ = "source_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(Text, unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    parser: Mapped[str] = mapped_column(String(40))
    race_id: Mapped[int | None] = mapped_column(ForeignKey("races.id", ondelete="SET NULL"))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PointsScheme(Base):
    """Championship points by rank, per competition, era and round kind."""
    __tablename__ = "points_schemes"
    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"))
    season_from: Mapped[int] = mapped_column(Integer)
    season_to: Mapped[int | None] = mapped_column(Integer)              # null = still current
    round_kind: Mapped[str] = mapped_column(String(20))                 # final | qual1 | semi ...
    points: Mapped[list[int]] = mapped_column(ARRAY(Integer))           # points[0] = 1st place
    is_official: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    note: Mapped[str | None] = mapped_column(Text)


class ModelRun(Base):
    """One run of a model: its settings, what it was fit on, and summary metrics."""
    __tablename__ = "model_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"))
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    model: Mapped[str] = mapped_column(String(60))                      # season_sim
    kind: Mapped[str] = mapped_column(String(20))                       # forecast | backtest
    data_through: Mapped[date | None] = mapped_column(Date)             # last event date in training data
    code_version: Mapped[str | None] = mapped_column(String(64))        # git commit
    params: Mapped[dict | None] = mapped_column(JSONB)
    metrics: Mapped[dict | None] = mapped_column(JSONB)


class RacePrediction(Base):
    """Per-athlete prediction for one race. race_id is null for races that
    don't exist in the database yet (e.g. an unraced round with unknown venue);
    `target` then names it (e.g. "next_round")."""
    __tablename__ = "race_predictions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model_run_id: Mapped[int] = mapped_column(ForeignKey("model_runs.id", ondelete="CASCADE"), index=True)
    race_id: Mapped[int | None] = mapped_column(ForeignKey("races.id", ondelete="CASCADE"))
    target: Mapped[str] = mapped_column(String(80))
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"))
    win_prob: Mapped[float | None] = mapped_column(Float)
    podium_prob: Mapped[float | None] = mapped_column(Float)
    top10_prob: Mapped[float | None] = mapped_column(Float)
    make_final_prob: Mapped[float | None] = mapped_column(Float)
    exp_points: Mapped[float | None] = mapped_column(Float)
    extra: Mapped[dict | None] = mapped_column(JSONB)


class StandingsPrediction(Base):
    __tablename__ = "standings_predictions"
    model_run_id: Mapped[int] = mapped_column(ForeignKey("model_runs.id", ondelete="CASCADE"), primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"), primary_key=True)
    current_points: Mapped[float | None] = mapped_column(Float)
    exp_points: Mapped[float | None] = mapped_column(Float)
    points_p10: Mapped[float | None] = mapped_column(Float)
    points_p90: Mapped[float | None] = mapped_column(Float)
    champion_prob: Mapped[float | None] = mapped_column(Float)
    top3_prob: Mapped[float | None] = mapped_column(Float)
    top10_prob: Mapped[float | None] = mapped_column(Float)
    exp_rank: Mapped[float | None] = mapped_column(Float)


class MarketLink(Base):
    """A prediction-market outcome token linked to one of our model's probabilities.

    prediction: race_win | race_podium | race_top10 | race_make_final   (per race; race_id
                null = the next unraced round, "remaining_round")
                champion | standings_top3                               (season standings)
    invert:     the token pays out when the prediction does NOT happen (e.g. the "No" side),
                so the model's fair price is 1 - p.
    """
    __tablename__ = "market_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    exchange: Mapped[str] = mapped_column(String(20), default="polymarket", server_default="polymarket")
    market_slug: Mapped[str | None] = mapped_column(String(300))
    question: Mapped[str] = mapped_column(Text)
    condition_id: Mapped[str | None] = mapped_column(String(80))
    token_id: Mapped[str] = mapped_column(String(100), index=True)
    outcome: Mapped[str] = mapped_column(String(200))                   # "Yes", "No", or a named outcome
    neg_risk: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    tick_size: Mapped[float | None] = mapped_column(Float)
    min_size: Mapped[float | None] = mapped_column(Float)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"))
    race_id: Mapped[int | None] = mapped_column(ForeignKey("races.id", ondelete="SET NULL"))
    prediction: Mapped[str] = mapped_column(String(30))
    invert: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    note: Mapped[str | None] = mapped_column(Text)


class Order(Base):
    """Every order the app builds: dry runs, submissions (with the exchange's
    response) and cancellations. Nothing is ever deleted."""
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    exchange: Mapped[str] = mapped_column(String(20), default="polymarket", server_default="polymarket")
    market_link_id: Mapped[int | None] = mapped_column(ForeignKey("market_links.id", ondelete="SET NULL"))
    token_id: Mapped[str] = mapped_column(String(100))
    side: Mapped[str] = mapped_column(String(4))                        # BUY | SELL
    price: Mapped[float] = mapped_column(Float)
    size: Mapped[float] = mapped_column(Float)                          # shares
    order_type: Mapped[str] = mapped_column(String(8), default="GTC", server_default="GTC")
    post_only: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    status: Mapped[str] = mapped_column(String(20))                     # dry_run | submitted | rejected | error | cancelled
    exchange_order_id: Mapped[str | None] = mapped_column(String(100))
    model_prob: Mapped[float | None] = mapped_column(Float)
    best_bid: Mapped[float | None] = mapped_column(Float)
    best_ask: Mapped[float | None] = mapped_column(Float)
    model_run_id: Mapped[int | None] = mapped_column(ForeignKey("model_runs.id", ondelete="SET NULL"))
    response: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class HouseMarket(Base):
    """A YES/NO market we quote ourselves (private bets), priced from the model.

    kind: race_win | race_podium | race_make_final   (race_id + athlete_id; settle from results)
          rank_up | rank_down                          (championship rank after the race vs before;
                                                        settle manually from official standings)
    Prices are what a counterparty pays per $1 payout:
        yes_price = fair + spread/2,  no_price = (1 - fair) + spread/2   (a side is not offered
        if its price would exceed max_price).
    """
    __tablename__ = "house_markets"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    race_id: Mapped[int] = mapped_column(ForeignKey("races.id"))
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"))
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(Text)
    model_run_id: Mapped[int | None] = mapped_column(ForeignKey("model_runs.id", ondelete="SET NULL"))
    fair_prob: Mapped[float] = mapped_column(Float)                     # model probability (or admin override)
    fair_source: Mapped[str] = mapped_column(String(20), default="model", server_default="model")
    spread: Mapped[float] = mapped_column(Float)                        # e.g. 0.06 = 6 points total
    yes_price: Mapped[float | None] = mapped_column(Float)
    no_price: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")  # open | closed | settled | void
    outcome: Mapped[bool | None] = mapped_column()                      # True = YES happened
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settle_note: Mapped[str | None] = mapped_column(Text)
    context: Mapped[dict | None] = mapped_column(JSONB)                 # e.g. current_rank for rank markets
    __table_args__ = (UniqueConstraint("race_id", "athlete_id", "kind"),)


class HouseBet(Base):
    """A bet a counterparty took against our quote. Money is handled outside the app."""
    __tablename__ = "house_bets"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    market_id: Mapped[int] = mapped_column(ForeignKey("house_markets.id"), index=True)
    counterparty: Mapped[str] = mapped_column(String(120))
    side: Mapped[str] = mapped_column(String(3))                        # side the counterparty bought: YES | NO
    price: Mapped[float] = mapped_column(Float)                         # price paid per $1 payout
    stake: Mapped[float] = mapped_column(Float)                         # amount the counterparty puts up
    payout: Mapped[float] = mapped_column(Float)                        # stake / price, paid to them if they win
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")  # open | won | lost | void
    note: Mapped[str | None] = mapped_column(Text)
