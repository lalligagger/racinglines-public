"""
The MCP server: `build()` registers the tools of racinglines/mcp/tools.py and the docs as resources on an
MCPServer (the `mcp` package, 2.x); `serve()` runs it over stdio (the default: a chat client launches
`racinglines mcp` as a subprocess) or streamable HTTP (`--http`, for the VM behind a tunnel), where every request
must carry an account's bearer token (racinglines/mcp/auth.py: `racinglines mcp token <account>`).

Every read tool runs in its own READ ONLY transaction. The job tools (run_job, cancel_job) write what the Lab's
Run form writes: a `jobs` row; the job's subprocess saves a model run (forecasts as scenarios, never promoted).
"""

import contextvars
import json
import os
import sys
from pathlib import Path

from sqlalchemy import text

from racinglines.mcp import tools as T

NAME = "racinglines"
DOCS = Path(__file__).resolve().parents[2] / "docs"
SPORTS = Path(__file__).resolve().parents[2] / "sports"
DEFAULT_PORT = 8100

INSTRUCTIONS = """racinglines: fair prices and market making for race sports (Formula 1 on Polymarket and Kalshi, UCI downhill),
priced strictly as of any moment and tested on real market tapes. This server reads the app's database and archive
and runs its simulations.

How to use it:
- overview() first: sports, seasons, the live forecast, what runs and markets exist.
- Data: list_events / get_event, search_athletes / get_athlete, list_markets (our fair value vs every venue per
  outcome), get_market_history (exchange prices, trades, books; resampled), list_model_runs / get_model_run /
  get_predictions, get_forecast, edge_finder (sweep results per strategy), list_diagnostics / get_diagnostic,
  track_record / list_positions / list_signals (paper trading), list_live_events, data_changes.
- Anything else: sql(query) — read-only SELECT, paged. describe_schema() lists the tables.
- Scenarios: list_job_types() then run_job(job_type, params) queues a Lab job (backtest, forecast scenario, event
  diagnostic, Edge Finder sweep, season strategy, downhill scenario/backtest); get_job(job_id) follows it and gives the
  model run it saved. replay_maker(run_id, knobs...) re-quotes a past event against the real tape in seconds.
- Every list is paged: default 50 rows, at most 500, and a byte cap; `total`, `truncated` and `next_offset` say
  what is left. Ask for what you need (columns, limit, offset) rather than everything.
- Probabilities are fractions (0.31 = 31%); money is USD; times are UTC. Fair values are the model's; the exchange
  columns are the venue's quotes at the time shown.
- Resources racinglines://docs/<page> hold the documentation (model.md, market-making.md, f1-forecast.md, ...).
"""


_URL = None
CALLER = contextvars.ContextVar("racinglines_mcp_caller", default=None)     # dict(id, username, role) in --http mode


def _engine():
    from racinglines.db.config import get_engine
    return get_engine(_URL)


def _json(obj):
    """One line of JSON: the text a chat client reads (an indented dump would double the bytes for nothing)."""
    return json.dumps(obj, default=str)


def _read(fn, **kw):
    """Call a tools.py function inside a READ ONLY transaction; anticipated errors become tool errors the client sees."""
    from mcp.server.mcpserver.exceptions import ToolError
    try:
        with _engine().begin() as c:
            c.execute(text("SET TRANSACTION READ ONLY"))
            return _json(fn(c, **kw))
    except (ValueError, KeyError, TypeError) as ex:
        raise ToolError(str(ex)) from ex
    except Exception as ex:  # noqa: BLE001  (a database error: its first line is safe and useful)
        raise ToolError(f"{type(ex).__name__}: {str(ex).splitlines()[0][:400]}") from ex


def _plain(fn, **kw):
    from mcp.server.mcpserver.exceptions import ToolError
    try:
        return _json(fn(**kw))
    except (ValueError, KeyError, TypeError) as ex:
        raise ToolError(str(ex)) from ex


def _write(fn, **kw):
    """The job tools: they write a jobs row (what the Lab's Run form does), nothing else."""
    from mcp.server.mcpserver.exceptions import ToolError
    try:
        return _json(fn(_engine(), **kw))
    except (ValueError, KeyError, TypeError) as ex:
        raise ToolError(str(ex)) from ex


def caller_id():
    c = CALLER.get()
    return c["id"] if c else None


def build(jobs_worker=False, engine_url=None):
    """The server with every tool and resource registered. `jobs_worker`: run the Lab's job worker in this process
    (queued jobs run here when no web app is running). `engine_url`: a database other than $DATABASE_URL."""
    global _URL
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ResourceError

    _URL = engine_url
    srv = MCPServer(NAME, instructions=INSTRUCTIONS, log_level="WARNING")

    # --- orientation --------------------------------------------------------------------------------
    @srv.tool()
    def overview() -> str:
        """What the database holds: sports, seasons, the live forecast per competition, model runs by kind, market
        links per exchange, venues, users and the next races. Call this first."""
        return _read(T.overview)

    @srv.tool()
    def describe_schema(table: str | None = None) -> str:
        """The database tables with one-line meanings, or one table's columns and types (for the sql tool)."""
        return _read(T.describe_schema, table=table)

    # --- data ---------------------------------------------------------------------------------------
    @srv.tool()
    def list_events(sport: str | None = None, competition: str | None = None, season: int | None = None,
                    status: str | None = None, limit: int = 50, offset: int = 0) -> str:
        """Events (race weekends / rounds), newest first. sport: f1 or mtb_dh; competition: f1_wdc or uci_dhi_wc;
        status: completed or scheduled. Each row has its id (for get_event) and source_key (e.g. 2026-15)."""
        return _read(T.list_events, sport=sport, competition=competition, season=season, status=status, limit=limit, offset=offset)

    @srv.tool()
    def get_event(event_id: int | None = None, source_key: str | None = None, include: str = "results") -> str:
        """One event by id or source_key ('2026-15', '20260821_mtb'): its races and, per `include` (comma-separated:
        results, predictions, markets), the final classification, every stored prediction, the venues matrix."""
        return _read(T.get_event, event_id=event_id, source_key=source_key, include=include)

    @srv.tool()
    def search_athletes(q: str | None = None, limit: int = 50) -> str:
        """Drivers and riders by (part of) name, with result counts, last race and wins."""
        return _read(T.search_athletes, q=q, limit=limit)

    @srv.tool()
    def get_athlete(athlete_id: int, include: str = "results") -> str:
        """One athlete with identifiers and, per `include` (results, predictions), their results and prediction history."""
        return _read(T.get_athlete, athlete_id=athlete_id, include=include)

    @srv.tool()
    def list_markets(race_id: int | None = None, event_id: int | None = None, competition: str | None = None,
                     sport: str | None = None, kinds: str | None = None, limit: int = 50, offset: int = 0) -> str:
        """The market matrix: one row per outcome (kind x subject) with our fair value, each venue's quote (Polymarket,
        Kalshi when enabled, the private book), the gap and, for a past race, the result and the exchange price at the
        time we priced. Give race_id or event_id for a race weekend, or competition/sport for the season-long markets.
        kinds: comma-separated (race_win, race_podium, race_top10, race_h2h, race_constructor_top, race_pole, champion, ...)."""
        return _read(T.list_markets, race_id=race_id, event_id=event_id, competition=competition, sport=sport, kinds=kinds,
                     limit=limit, offset=offset)

    @srv.tool()
    def get_market_history(tokens: str | None = None, race_id: int | None = None, kind: str | None = None,
                           athlete_id: int | None = None, subject: str | None = None, exchange: str | None = None,
                           series: str = "prices", start: str | None = None, end: str | None = None,
                           resample: str | None = "1h", limit: int = 200, offset: int = 0) -> str:
        """Exchange time series from the archive and the database. series: prices (last price per bucket), trades (count,
        volume, VWAP per bucket; resample=None lists trades) or books (best bid/ask). Pick markets by tokens (comma-separated
        token ids from list_markets) or by race_id + kind / athlete_id / subject (a name) / exchange (polymarket, kalshi).
        start/end are UTC ISO timestamps; a race defaults to the week before its start. resample is a pandas offset
        ('15min', '1h', '1D'); at most 200 points per token whatever you ask."""
        return _read(T.get_market_history, tokens=tokens, race_id=race_id, kind=kind, athlete_id=athlete_id, subject=subject,
                     exchange=exchange, series=series, start=start, end=end, resample=resample, limit=limit, offset=offset)

    @srv.tool()
    def list_model_runs(kind: str | None = None, competition: str | None = None, sport: str | None = None,
                        season: int | None = None, limit: int = 50, offset: int = 0) -> str:
        """Stored model runs, newest first. kind: forecast (live prices), scenario, diagnostic (as-of a cutoff), backtest,
        sweep (a season traded on the exchange), season_strategy, season_checkpoints, walk_forward, candidate."""
        return _read(T.list_model_runs, kind=kind, competition=competition, sport=sport, season=season, limit=limit, offset=offset)

    @srv.tool()
    def get_model_run(run_id: int, path: str | None = None) -> str:
        """One run: params, metrics and its prediction targets. Large metrics come back as a key map with sizes; path
        (e.g. 'metrics.weekends', 'metrics.weekends.3', 'params.settings') returns that part, paged when it is a list."""
        return _read(T.get_model_run, run_id=run_id, path=path)

    @srv.tool()
    def get_predictions(run_id: int, target: str | None = None, top: int = 20, standings: bool = False) -> str:
        """A run's per-athlete probabilities (win, podium, top 10, make the Final, expected points) for one target (a race;
        omit to list the targets), or with standings=true its projected championship standings."""
        return _read(T.get_predictions, run_id=run_id, target=target, top=top, standings=standings)

    @srv.tool()
    def get_forecast(competition: str | None = None, sport: str | None = None, category: str | None = None, top: int = 10) -> str:
        """The live forecast (the run the web app shows as our fair prices): the next races' top probabilities and the
        championship standings, per competition and category."""
        return _read(T.get_forecast, competition=competition, sport=sport, category=category, top=top)

    # --- strategy research ---------------------------------------------------------------------------
    @srv.tool()
    def edge_finder(year: int = 2026, strategy: str | None = None, limit: int = 50, offset: int = 0) -> str:
        """The Lab's Edge Finder from saved sweeps: every configuration (a full set of sweep settings) with a full-season
        sweep of `year`, and each strategy's full-season recap (P&L, volume, weekends up, drawdown, consistency, fills and
        markout for makers). Nothing is simulated. strategy: update, hold, last, early, maker, maker_flat, ... (omit for all)."""
        return _read(T.edge_finder, year=year, strategy=strategy, limit=limit, offset=offset)

    @srv.tool()
    def list_candidates(limit: int = 50, offset: int = 0) -> str:
        """Named configuration x strategy candidates saved in the Lab (searches add theirs; the strategy profiles A and C)."""
        return _read(T.list_candidates, limit=limit, offset=offset)

    @srv.tool()
    def list_diagnostics(limit: int = 50, offset: int = 0) -> str:
        """Events with as-of diagnostic runs (our prices at a cutoff before the race): the run ids and cutoffs per event.
        get_diagnostic(run_id) reads one; replay_maker(run_id, ...) re-quotes it."""
        return _read(T.list_diagnostics, limit=limit, offset=offset)

    @srv.tool()
    def get_diagnostic(run_id: int, top: int = 25) -> str:
        """One diagnostic run: our prices vs Polymarket at the cutoff (and 24 h before), the edge per market, the paper
        strategy's P&L, Brier and log loss per kind for model and market, and the result."""
        return _read(T.get_diagnostic, run_id=run_id, top=top)

    @srv.tool()
    def replay_maker(run_id: int, fill: str = "through", half_spread: float = 0.02, size: float = 50, max_pos: float = 250,
                     max_capital: float = 1000, skew: float = 1.0, max_disagree: float = 0.15, min_volume_24h: float = 100,
                     pull_min: float = 15, exchange: str = "polymarket", with_sweep: bool = False, top: int = 20) -> str:
        """Scenario: replay a maker quoting an exchange (polymarket, or kalshi with its maker fee) through an event's
        diagnostic runs (repricing at each cutoff) against the real trade tape, with the event diagnostic's knobs: fill rule
        (through, touch, queue), half-spread ($), shares per quote, max inventory per market, max worst-case loss ($),
        inventory skew, max |fair - market| to quote, min 24 h volume ($), pull time before the race (min). Synchronous
        (seconds); nothing is stored. with_sweep adds the half-spread x fill-rule sensitivity table."""
        return _read(T.replay_maker, run_id=run_id, fill=fill, half_spread=half_spread, size=size, max_pos=max_pos,
                     max_capital=max_capital, skew=skew, max_disagree=max_disagree, min_volume_24h=min_volume_24h,
                     pull_min=pull_min, exchange=exchange, with_sweep=with_sweep, top=top)

    # --- paper trading, live events, change log ------------------------------------------------------
    @srv.tool()
    def track_record(user: str, venue: str = "polymarket") -> str:
        """A user's paper-trading record, one row per weekend: strategy, trades taken or fills, positions, P&L (settled or
        marked), backtest replay or live. venue: polymarket, kalshi (the maker's replay on Kalshi's tape), private, or all
        (one row per weekend and venue, with a venue column and totals per venue). Users: see overview()."""
        return _read(T.track_record, user=user, venue=venue, viewer=CALLER.get())

    @srv.tool()
    def list_positions(user: str, venue: str | None = None, event_key: str | None = None, open_only: bool = False,
                       limit: int = 50, offset: int = 0) -> str:
        """A user's paper positions (YES/NO shares, cash, mark, outcome, P&L) with totals per venue."""
        return _read(T.list_positions, user=user, venue=venue, event_key=event_key, open_only=open_only, limit=limit,
                     offset=offset, viewer=CALLER.get())

    @srv.tool()
    def list_signals(user: str | None = None, event_key: str | None = None, status: str | None = None,
                     action: str | None = None, limit: int = 50, offset: int = 0) -> str:
        """Paper signals (what a strategy profile would do: buy/sell recommendations, quote/pull, paper fills), newest first.
        status: new, alerted, expired, filled_paper; action: buy, sell, quote, pull, fill."""
        return _read(T.list_signals, user=user, event_key=event_key, status=status, action=action, limit=limit,
                     offset=offset, viewer=CALLER.get())

    @srv.tool()
    def list_live_events(limit: int = 50, offset: int = 0) -> str:
        """Live private-book events: the settled ones (maker P&L vs the crowd and the demo taker, fills, volume) and the run
        folders on this machine, with whether one is live now."""
        return _read(T.list_live_events, limit=limit, offset=offset)

    @srv.tool()
    def data_changes(sport: str | None = None, limit: int = 50, offset: int = 0) -> str:
        """The data change log: ingests that changed the race history, athlete merges and notes, newest first."""
        return _read(T.data_changes, sport=sport, limit=limit, offset=offset)

    # --- sql ----------------------------------------------------------------------------------------
    @srv.tool()
    def sql(query: str, limit: int = 50, offset: int = 0) -> str:
        """Run one read-only SQL query (SELECT / WITH ... SELECT / EXPLAIN) against the database, in a READ ONLY transaction
        with a 10 s timeout. The result is paged (limit at most 500; an outer LIMIT/OFFSET is applied for you). The users and
        orders tables are not readable. describe_schema() lists the tables and columns."""
        return _read(T.sql, query=query, limit=limit, offset=offset)

    # --- jobs ---------------------------------------------------------------------------------------
    @srv.tool()
    def list_job_types() -> str:
        """The simulations run_job can queue (the Lab's job catalog) with their knobs, ranges and defaults, and every sweep
        setting (model, timing, taker, maker, markets) an Edge Finder sweep accepts."""
        return _plain(T.list_job_types)

    @srv.tool()
    def run_job(job_type: str, params: dict | None = None) -> str:
        """Scenario: queue a simulation as a Lab job: f1_backtest, f1_scenario (a forward forecast saved as a scenario, never
        the live prices), f1_diagnostic (event '2026-15', cutoff '2026-09-25T13:30'), f1_sweep (year + settings: any sweep
        setting), f1_season_strategy, dh_scenario, dh_backtest. params: the job type's knobs (list_job_types). Returns the
        job id; get_job follows it and names the model run it saved (result_run_id)."""
        return _write(T.run_job, job_type=job_type, params=params, user_id=caller_id())

    @srv.tool()
    def get_job(job_id: int, log_lines: int = 20) -> str:
        """A job's status (queued, running, done, failed), progress, the last log lines and result_run_id."""
        return _read(T.get_job, job_id=job_id, log_lines=log_lines)

    @srv.tool()
    def list_jobs(status: str | None = None, limit: int = 50, offset: int = 0) -> str:
        """Jobs, newest first (the Lab's and this server's)."""
        return _read(T.list_jobs, status=status, limit=limit, offset=offset)

    @srv.tool()
    def cancel_job(job_id: int) -> str:
        """Cancel a job that has not started yet."""
        return _write(T.cancel_job, job_id=job_id)

    # --- resources: the docs and the sport schemas ---------------------------------------------------
    @srv.resource("racinglines://docs", name="docs-index", description="The documentation pages available as racinglines://docs/<page>")
    def docs_index() -> str:
        pages = sorted(p.name for p in DOCS.glob("*.md"))
        return "\n".join(pages)

    @srv.resource("racinglines://docs/{page}", name="doc", description="One documentation page (Markdown), e.g. model.md",
                  mime_type="text/markdown")
    def doc(page: str) -> str:
        p = DOCS / page
        if not page.endswith(".md") or "/" in page or not p.exists():
            raise ResourceError(f"no docs page {page!r}; read racinglines://docs for the list")
        return p.read_text()

    @srv.resource("racinglines://sports/{code}", name="sport", description="A sport's schema (sports/<code>.toml): f1, mtb_dh, or a tape-only sport (nascar, motogp, indycar)",
                  mime_type="application/toml")
    def sport(code: str) -> str:
        p = SPORTS / f"{code}.toml"
        if "/" in code or not p.exists():
            raise ResourceError(f"no sport {code!r}")
        return p.read_text()

    if jobs_worker:
        from racinglines.web import jobs as J
        J.start_worker(reset_running=False)
    return srv


def bearer_app(app, engine=None):
    """Streamable HTTP behind per-account bearer tokens: every request must carry `Authorization: Bearer rl_...`
    matching an account (auth.lookup); the account is the caller for the request (CALLER)."""
    from starlette.responses import JSONResponse

    from racinglines.mcp import auth

    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            got = headers.get("authorization", "")
            user = auth.lookup(engine or _engine(), got[7:].strip()) if got.startswith("Bearer ") else None
            if user is None:
                await JSONResponse({"error": "unauthorized: a bearer token issued with `racinglines mcp token <account>`"},
                                   status_code=401, headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
                return
            token = CALLER.set(user)
            try:
                await app(scope, receive, send)
            finally:
                CALLER.reset(token)
            return
        await app(scope, receive, send)
    return guarded


def http_app(srv, engine=None):
    """The streamable-HTTP ASGI app behind the bearer check, for any Host header. The SDK's default for a
    loopback bind answers 421 to every Host but localhost (its DNS-rebinding guard: a browser page tricked into
    calling 127.0.0.1 would carry no bearer token and is refused 401 here before the MCP app sees it), which
    would also refuse the tunnel's public hostname (mcp.racinglines.bet)."""
    from mcp.server.transport_security import TransportSecuritySettings
    app = srv.streamable_http_app(stateless_http=True, json_response=True,
                                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    return bearer_app(app, engine=engine)


def serve(http=False, host="127.0.0.1", port=DEFAULT_PORT, jobs_worker=True):
    """Run the server: stdio (default), or streamable HTTP on host:port/mcp, each request with an account's token."""
    from racinglines.mcp import auth
    srv = build(jobs_worker=jobs_worker)
    if not http:
        srv.run("stdio")
        return
    who = auth.holders(_engine())
    if not who:
        print("racinglines mcp --http: no account has a token yet; issue one with `racinglines mcp token <account>`.",
              file=sys.stderr)
        sys.exit(2)
    print("accounts with MCP access: " + ", ".join(f"{u} ({r})" for u, r, _ in who), file=sys.stderr)
    if host not in ("127.0.0.1", "localhost"):
        print(f"WARNING: listening on {host}; keep it behind a tunnel or a private network.", file=sys.stderr)
    import uvicorn
    uvicorn.run(http_app(srv), host=host, port=int(port), log_level="warning")
