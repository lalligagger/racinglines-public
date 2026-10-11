"""
The Mario Kart tour: the pipeline end to end on a synthetic season, behind each real command's `--demo` flag (CLI tree
option A, owner 2026-10-11: no root `demo` group). No database, network or account; everything is made up
(racinglines/demo/kart.toml, engine racinglines/demo/kart.py). Play money, nothing is traded.

    racinglines model backtest --demo      1. five seasons of history, the pace model fitted and swept walk-forward
    racinglines model forecast --demo      2. the next race at Rainbow Road: 400,000 simulated races
    racinglines live run --demo            3. the race live: Wario's book re-quotes every sector, 100 Toads trade, the report
    racinglines book price --demo          4. sportsbook lines against the model and the exchanges (docs/sportsbook/slips.md)

A command wires its flag with add_arguments(parser, step) and run(step, args) (or main(step, argv)). Options:
    --seed N        the whole tour's seed (default 7): the same seed gives the same history, race and fills
    --track KEY     forecast and race: rainbow-road (default), bowsers-castle, mario-circuit, moo-moo-meadows
    --out DIR       where the steps keep their files (default data/demo/kart): model.json, forecast.json and the race's
                    run folder (runs/live/kart-<track>-<seed>/, with report/report.md, .html and with --pdf .pdf)
    --sims N        backtest: Monte Carlo runs per race priced (2,500); forecast: total runs (400,000)
    --delay S       race: seconds between updates on screen (0.6; 0 for no pause)
    --pdf           race: also render the report as a PDF (weasyprint or a headless Chrome)
"""

import argparse
import json
import time
from contextlib import contextmanager
from pathlib import Path

from racinglines import paths

STEPS = ("backtest", "forecast", "race")


COMMANDS = {"backtest": "racinglines model backtest --demo", "forecast": "racinglines model forecast --demo",
            "race": "racinglines live run --demo", "book": "racinglines book price --demo"}


def add_arguments(p, step):
    """The tour's options for one step on a command's parser (the command adds --demo itself)."""
    p.add_argument("--seed", type=int, default=7, help="demo: the tour's seed")
    p.add_argument("--out", default=None, help="demo: the tour's folder (default data/demo/kart)")
    if step != "backtest":
        p.add_argument("--track", default="rainbow-road", help="demo: the track")
    if step == "backtest":
        p.add_argument("--seasons", type=int, default=5, help="demo: seasons of history")
        p.add_argument("--sims", type=int, default=2500, help="demo: Monte Carlo runs per race priced")
    if step == "forecast":
        p.add_argument("--sims", type=int, default=400_000, help="demo: Monte Carlo runs")
    if step == "race":
        p.add_argument("--delay", type=float, default=0.6, help="demo: seconds between updates on screen")
        p.add_argument("--pdf", action="store_true", help="demo: also render the report as a PDF")
    return p


def _rich():
    try:
        import rich  # noqa: F401
    except ImportError as e:
        raise SystemExit(f"the Mario Kart tour (--demo) needs the rich package (pip install -r requirements.txt): {e}")
    from rich.console import Console
    return Console(highlight=False)


def _out(args):
    return Path(args.out) if args.out else paths.DATA / "demo" / "kart"


def _step(con, n, title, sub=""):
    from rich.panel import Panel
    con.print(Panel(f"[bold]🏁 Step {n} of 4 · {title}[/]" + (f"\n[dim]{sub}[/]" if sub else ""), border_style="red",
                    expand=False))


@contextmanager
def _progress(con, emoji):
    """A Rich progress bar; yields progress(done, total, what)."""
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn, TimeRemainingColumn
    with Progress(TextColumn(emoji), BarColumn(bar_width=36, complete_style="red", finished_style="green"),
                  MofNCompleteColumn(), TimeElapsedColumn(), TextColumn("·"), TimeRemainingColumn(),
                  TextColumn("[dim]{task.description}"), console=con, transient=False) as bar:
        task = bar.add_task("", total=None)

        def update(done, total, what=""):
            bar.update(task, completed=done, total=total, description=what)
        yield update


def _pct(x):
    return f"{100 * x:.1f}%"


def _model(out):
    f = out / "model.json"
    if not f.exists():
        raise SystemExit(f"no model at {f}: run `{COMMANDS['backtest']}` first (step 1)")
    return json.loads(f.read_text())


# ---------------------------------------------------------------------------
# 1. backtest
# ---------------------------------------------------------------------------

def cmd_backtest(args, con):
    from rich.table import Table

    from racinglines.demo import kart as K
    cfg = K.load()
    out = _out(args)
    out.mkdir(parents=True, exist_ok=True)
    tracks = ", ".join(t["name"] for t in cfg["tracks"].values())
    _step(con, 1, "Backtest", f"{args.seasons} seasons x {len(cfg['tracks'])} tracks ({tracks}), "
                              f"{len(cfg['drivers'])} drivers; the pace model swept walk-forward")
    con.print("🍄 Building the history...")
    races = K.history(cfg, args.seed, args.seasons)
    con.print(f"   {len(races)} races, {sum(r['events'] for r in races):,} items thrown")
    t0 = time.time()
    with _progress(con, "🏎️ ") as bar:
        bt = K.backtest(cfg, races, sims=args.sims, progress=bar, seed=args.seed)
    best = bt["leaderboard"][0]
    pace = K.fit(races, best["half_life"], best["shrink"])
    true = K.true_pace(cfg, args.seed, args.seasons)[-1]
    model = dict(seed=args.seed, seasons=args.seasons, n_races=len(races), half_life=best["half_life"],
                 shrink=best["shrink"], pace=pace.tolist(), true_pace=true.tolist(), backtest=bt)
    (out / "model.json").write_text(json.dumps(model, indent=1))
    (out / "history.json").write_text(json.dumps(races))

    b = bt["baseline"]
    t = Table(title=f"Walk-forward: {bt['races']} races priced before the start, {bt['sims']:,} simulations each",
              title_justify="left")
    for c in ("half-life", "shrink", "win Brier", "win log loss", "podium Brier", "podium log loss"):
        t.add_column(c, justify="right")
    for i, r in enumerate(bt["leaderboard"]):
        style = "bold green" if i == 0 else None
        t.add_row(K._hl(r["half_life"]), f"{r['shrink']:g}", f"{r['win_brier']:.4f}", f"{r['win_logloss']:.4f}",
                  f"{r['podium_brier']:.4f}", f"{r['podium_logloss']:.4f}", style=style)
    t.add_row("baseline", "everyone equal", f"{b['win_brier']:.4f}", f"{b['win_logloss']:.4f}",
              f"{b['podium_brier']:.4f}", f"{b['podium_logloss']:.4f}", style="dim")
    con.print(t)
    gain = 1 - (best["win_logloss"] + best["podium_logloss"]) / (b["win_logloss"] + b["podium_logloss"])
    con.print(f"Chosen: half-life [bold]{K._hl(best['half_life'])}[/] races, shrink [bold]{best['shrink']:g}[/]: "
              f"log loss {gain:.1%} better than everyone-equal (lower is better).")

    p = Table(title="Fitted pace vs the hidden truth", caption="seconds per sector faster than the field",
              title_justify="left", caption_justify="left")
    for c, j in (("driver", "left"), ("fitted", "right"), ("true", "right"), ("error", "right")):
        p.add_column(c, justify=j)
    tc = true - true.mean()
    for i in sorted(range(len(pace)), key=lambda i: -pace[i]):
        p.add_row(cfg["drivers"][i]["name"], f"{pace[i]:+.3f}", f"{tc[i]:+.3f}", f"{pace[i] - tc[i]:+.3f}")
    con.print(p)
    con.print(f"[green]✓[/] {time.time() - t0:.1f} s · model saved to {out / 'model.json'}")
    con.print(f"Next: [bold]{COMMANDS['forecast']}[/]")
    return 0


# ---------------------------------------------------------------------------
# 2. forecast
# ---------------------------------------------------------------------------

def cmd_forecast(args, con):
    from rich.table import Table

    from racinglines.demo import kart as K
    cfg = K.load()
    if args.track not in cfg["tracks"]:
        raise SystemExit(f"unknown track {args.track!r} (known: {', '.join(cfg['tracks'])})")
    out = _out(args)
    model = _model(out)
    track = cfg["tracks"][args.track]
    _step(con, 2, f"Forecast · {track['name']}", f"{args.sims:,} simulated races on the fitted pace, items included")
    t0 = time.time()
    with _progress(con, "🍄") as bar:
        fc = K.forecast(cfg, model, args.track, n=args.sims, progress=bar, seed=args.seed)
    (out / "forecast.json").write_text(json.dumps(dict(track=args.track, sims=args.sims, **fc), indent=1))
    t = Table(title=f"{track['name']}: before the start", title_justify="left")
    for c, j in (("driver", "left"), ("win", "right"), ("fair odds", "right"), ("podium", "right"),
                 ("top 5", "right")):
        t.add_column(c, justify=j)
    nm = K.names(cfg)
    for i in sorted(range(len(nm)), key=lambda i: -fc["race_win"][i]):
        t.add_row(nm[i], _pct(fc["race_win"][i]), K.odds(fc["race_win"][i]), _pct(fc["race_podium"][i]),
                  _pct(fc["race_top5"][i]))
    con.print(t)
    se = max((p * (1 - p) / args.sims) ** 0.5 for p in fc["race_win"])
    con.print(f"[dim]Monte Carlo error at most ±{1.96 * se:.2%} (95%) on any win probability.[/]")
    con.print(f"[green]✓[/] {time.time() - t0:.1f} s · saved to {out / 'forecast.json'}")
    con.print(f"Next: [bold]{COMMANDS['race']}[/]")
    return 0


# ---------------------------------------------------------------------------
# 3. race
# ---------------------------------------------------------------------------

def _ba(x):
    """'0.31 / 0.37', a dash for a side not quoted."""
    if x["bid"] is None and x["ask"] is None:
        return "–"
    return " / ".join("–" if v is None else f"{v:.2f}" for v in (x["bid"], x["ask"]))


def _race_view(snap, cfg, race):
    from rich.console import Group
    from rich.panel import Panel
    from rich.progress_bar import ProgressBar
    from rich.table import Table
    from rich.text import Text

    from racinglines.demo import kart as K
    u = snap["update"]
    q = {x["key"]: x for x in snap["quotes"]}
    inv = {k: v["inv"] for k, v in race.book["markets"].items()}
    head = Table.grid(padding=(0, 1))
    head.add_row(Text(f"🏎️  {race.track['name']} · {u['label']}", style="bold"),
                 ProgressBar(total=u["of"], completed=u["k"], width=30, complete_style="red", finished_style="green"),
                 Text(f"{u['k']}/{u['of']} sectors", style="dim"))
    t = Table(expand=False)
    for c, j in (("", "right"), ("driver", "left"), ("gap", "right"), ("win", "right"), ("bid / ask", "center"),
                 ("podium", "right"), ("bid / ask", "center"), ("Wario's win pos.", "right")):
        t.add_column(c, justify=j)
    for s in snap["standings"]:
        w, p = q[f"race_win:{s['name']}"], q[f"race_podium:{s['name']}"]
        pos = inv.get(f"race_win:{s['name']}", 0.0)
        t.add_row(str(s["pos"]), s["name"], "leader" if s["pos"] == 1 else f"+{s['gap']:.2f}s", _pct(w["fair"]), _ba(w),
                  _pct(p["fair"]), _ba(p), Text(f"{pos:+,.0f}", style="red" if pos < 0 else "green" if pos > 0 else "dim"))
    ev = Text("\n".join(snap["events"]) if snap["events"] else ("Let's-a go! 🏁" if u["k"] == 0 else " "))
    mp, cr = snap["maker_pnl"], snap["crowd"]
    foot = Text.assemble(("Wario's book ", "bold"), (K.money(mp["total"]), "green" if mp["total"] >= 0 else "red"),
                         (" marked to fair · ", "dim"), (f"{cfg['crowd']['name']}: ", "bold"),
                         f"{cr['fills']:,} fills (+{snap['fills']}), ${cr['volume']:,.0f} traded, "
                         f"{cr['active']} of {cr['takers']} betting")
    return Panel(Group(head, ev, t, foot), title=f"🍄 {cfg['bookie']['name']}'s book", border_style="red", expand=False)


def cmd_race(args, con):
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table

    from racinglines.demo import kart as K
    from racinglines.pipelines import live_report as R
    cfg = K.load()
    if args.track not in cfg["tracks"]:
        raise SystemExit(f"unknown track {args.track!r} (known: {', '.join(cfg['tracks'])})")
    out = _out(args)
    model = _model(out)
    old, paths.DATA = paths.DATA, out                     # the run folder: <out>/runs/live/kart-<track>-<seed>/
    try:
        race = K.Race(cfg, model, args.track, args.seed)
        _step(con, 3, f"Race · {race.track['name']}", f"{cfg['laps']} laps x {cfg['sectors']} sectors, "
                                                       f"{race.sims:,} simulations of the rest of the race per update")
        con.print(f"[bold]{cfg['bookie']['name']}[/] opens the book on {race.track['name']}: win and podium for "
                  f"{len(race.names)} drivers, {cfg['crowd']['takers']} {cfg['crowd']['name']} with ${cfg['crowd']['budget'][0]:.0f}"
                  f"-{cfg['crowd']['budget'][1]:.0f} each. Every sector the model re-prices the rest of the race and "
                  "Wario re-quotes.")
        snap = race.step()
        with Live(_race_view(snap, cfg, race), console=con, refresh_per_second=8) as live:
            while True:
                if args.delay:
                    time.sleep(args.delay)
                nxt = race.step()
                if nxt is None:
                    break
                snap = nxt
                live.update(_race_view(snap, cfg, race))
        con.print()
        files = R.write(dict(run=race.run), pdf=args.pdf)
    finally:
        paths.DATA = old

    order = [s["name"] for s in snap["standings"]]
    mp, cr = snap["maker_pnl"], snap["crowd"]
    res = cr.get("results") or {}
    t = Table.grid(padding=(0, 2))
    t.add_row("🥇🥈🥉", "  ".join(order[:3]))
    t.add_row("Wario's book", f"[{'green' if mp['total'] >= 0 else 'red'}]{K.money(mp['total'])}[/] settled, "
                              f"on ${cr['volume']:,.0f} traded in {cr['fills']:,} fills")
    if res:
        t.add_row(f"The {cfg['crowd']['name']}", f"{res['up']} up, {res['down']} down; median {K.money(res['median'])}, "
                                                f"best {K.money(res['best'])}, worst {K.money(res['worst'])}")
    t.add_row("", f"[dim]The {cfg['crowd']['name']} bet at random, with no view of their own: Wario's edge is the "
                  "spread, kept centred on the model's fair.[/]")
    con.print(Panel(t, title=f"🏁 Finish · {race.track['name']}", border_style="green", expand=False))
    con.print(f"Report: {files['md']}" + (f"\n        {files['pdf']}" if files.get("pdf") else
                                          f"\n        {files['html']}" + ("" if not args.pdf else
                                                                           " [dim](no PDF: needs weasyprint or Chrome)[/]")))
    con.print(f"Next: [bold]{COMMANDS['book']}[/] (step 4: sportsbook lines against the model and the exchanges)")
    return 0


def run(step, args):
    """Run one step ("backtest", "forecast", "race") with parsed args (add_arguments' options)."""
    return {"backtest": cmd_backtest, "forecast": cmd_forecast, "race": cmd_race}[step](args, _rich())


def main(step, argv=None):
    """Parse argv with the step's options and run it (tests, and a command that hands its argv over)."""
    p = add_arguments(argparse.ArgumentParser(prog=COMMANDS[step]), step)
    return run(step, p.parse_args(argv))
