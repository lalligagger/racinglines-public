"""
Flat commands with the sport as an option: `racinglines <command> [--sport SPORT] [options]`, e.g.
`racinglines forecast --sport f1 --save`. The sport comes from --sport, else $RACINGLINES_SPORT, else the one sport that
offers the command; the command runs exactly what the sport's own parser (racinglines/cli/<sport>.py) runs for it, and
which sports offer which command is read from those parsers at run time, so nothing is listed twice. The sport-first
form (`racinglines f1 forecast`) still works: the VM's timers, scripts and the Lab's jobs use it.
"""

import argparse
import importlib
import os
import re
import sys

# the CLI module of each sport (sports/<code>.toml codes, plus the short names the commands have always used)
SPORTS = {"f1": "f1", "mtb_dh": "mtb_dh", "nascar": "nascar", "motogp": "motogp", "road_cycling": "cycling",
          "cycling": "cycling"}
MODULES = ("f1", "mtb_dh", "nascar", "motogp", "cycling")

# the help's sections, in order; a sport command is listed under its section (a name a group already uses is renamed:
# the downhill live follower is `follow`, since `live` is the live-event group)
SECTIONS = {
    "Data": ("fetch", "download", "parse", "ingest", "link", "record", "inrace-backfill", "events", "startlist",
             "probe", "points"),
    "Pricing": ("forecast", "backtest", "walk-forward", "compare", "matrix", "diagnostic", "combo", "props",
                "sprint-check", "season", "price", "reliability"),
    "Trading": ("replay", "sweep", "season-replay", "season-strategy", "season-checkpoints", "scorecard", "signals",
                "demo-history", "reconcile", "profiles", "search", "search-report", "search-import", "search-analyze",
                "follow"),
    "Polymarket (F1, older commands; see `markets`)": ("pm-sync", "pm-links-export", "pm-links-import", "pm-history",
                                                       "pm-trades", "pm-record", "pm-archive"),
}
RENAMED = {"follow": "live"}                   # flat name -> the sport parser's command
COMMANDS = tuple(c for cmds in SECTIONS.values() for c in cmds)

# one line for a command several sports offer (`racinglines <command> --sport S -h` says what it does there)
SHARED = {
    "fetch": "Download the sport's source data (results, sessions or feeds) to data/raw/.",
    "ingest": "Load the downloaded data into the database.",
    "forecast": "Price the upcoming races with the sport's model.",
    "backtest": "Price past races as of before each one and score them against the results.",
    "compare": "A challenger model against the baseline, race by race.",
    "replay": "Replay a strategy against an exchange's recorded prices.",
    "sweep": "The season sweep: the taker modes and maker variants through each race's weekend.",
    "season-replay": "Champion markets replayed through the season.",
    "signals": "Live paper signals of users' strategy profiles (recommendations only).",
    "demo-history": "Backfill the demo accounts' track record from backtest replays.",
    "search": "Search model or strategy settings.",
}


class _Parser(Exception):
    pass


def parser_of(module):
    """The argparse parser a sport's CLI module builds, without running anything: its main() is stopped at the parse."""
    mod = importlib.import_module(f"racinglines.cli.{module}")
    grab = lambda self, *a, **k: (_ for _ in ()).throw(_Parser(self))      # noqa: E731
    saved = argparse.ArgumentParser.parse_args, argparse.ArgumentParser.parse_known_args
    argparse.ArgumentParser.parse_args = argparse.ArgumentParser.parse_known_args = grab
    try:
        mod.main(["-h"])
    except _Parser as p:
        return p.args[0]
    finally:
        argparse.ArgumentParser.parse_args, argparse.ArgumentParser.parse_known_args = saved
    raise RuntimeError(f"racinglines.cli.{module} has no argparse parser")


def _subcommands(parser):
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            helps = {c.dest: c.help or "" for c in a._choices_actions}
            return {name: helps.get(name, "") for name in a.choices}
    return {}


def _doc_lines(module):
    """{command: description} from the module docstring's command list (continued on deeper-indented lines)."""
    doc = importlib.import_module(f"racinglines.cli.{module}").__doc__ or ""
    out, cur = {}, None
    for line in doc.splitlines():
        m = re.match(r"^ {4}([a-z][a-z-]*) {2,}(\S.*)$", line)
        if m:
            cur = m.group(1)
            out[cur] = m.group(2)
        elif cur and re.match(r"^ {6,}\S", line):
            out[cur] += " " + line.strip()
        else:
            cur = None
    return out


def _first_sentence(text):
    text = " ".join(text.split())
    m = re.search(r"[.;:] (?=[A-Z(])", text)
    return text if m is None else text[:m.start() + 1]


def commands(module):
    """{sport command: one-line help} of a sport's CLI module (the parser's help, else the docstring's line)."""
    doc = _doc_lines(module)
    return {c: _first_sentence(h or doc.get(c, "")) for c, h in _subcommands(parser_of(module)).items()}


def offered(flat):
    """The sport modules that offer a flat command, in MODULES order."""
    name = RENAMED.get(flat, flat)
    return [m for m in MODULES if name in commands(m)]


def _hoist(parser, rest):
    """Move the sport parser's own options (f1's --db, --variant, --half-life), which argparse wants before the command,
    to the front, so they can be written anywhere."""
    own = {s: a for a in parser._actions if not isinstance(a, argparse._SubParsersAction)
           for s in a.option_strings if s not in ("-h", "--help")}
    front, back, i = [], [], 0
    while i < len(rest):
        tok = rest[i]
        a = own.get(tok.split("=", 1)[0])
        if a is None:
            back.append(tok)
            i += 1
            continue
        if "=" in tok or a.nargs == 0:
            n = 0
        elif a.nargs in ("+", "*"):
            n = 0
            while i + 1 + n < len(rest) and not rest[i + 1 + n].startswith("-"):
                n += 1
        else:
            n = a.nargs if isinstance(a.nargs, int) else 1
        front += rest[i:i + 1 + n]
        i += 1 + n
    return front, back


def _take_sport(argv):
    """(--sport value or None, argv without it)."""
    out, sport, i = [], None, 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--sport" and i + 1 < len(argv):
            sport, i = argv[i + 1], i + 2
        elif tok.startswith("--sport="):
            sport, i = tok.split("=", 1)[1], i + 1
        else:
            out.append(tok)
            i += 1
    return sport, out


def help_text():
    rows = {}
    for m in MODULES:
        for c, h in commands(m).items():
            flat = next((f for f, s in RENAMED.items() if s == c), c)
            r = rows.setdefault(flat, [[], h])
            r[0].append(m)
    lines = []
    for section, cmds in SECTIONS.items():
        lines.append(f"  {section}")
        for c in cmds:
            if c in rows:
                sports, h = rows[c]
                h = SHARED.get(c, h) if len(sports) > 1 else h
                h = h if len(h) <= 76 else h[:75].rstrip(" ,;:(") + "…"
                lines.append(f"    {c:<19} {' '.join(sports):<26} {h}")
        lines.append("")
    return "\n".join(lines)


def main(flat, argv):
    sport, rest = _take_sport(argv)
    sports = offered(flat)
    if sport is None:
        env = os.environ.get("RACINGLINES_SPORT")
        if env and SPORTS.get(env) in sports:
            sport = env
        elif len(sports) == 1:
            sport = sports[0]
        else:
            if rest and rest[0] in ("-h", "--help"):
                print(f"racinglines {flat} --sport {{{','.join(sports)}}} [options]\n\n{SHARED.get(flat, '')}\n"
                      f"`racinglines {flat} --sport SPORT -h` for that sport's options.")
                return 0
            print(f"racinglines {flat}: say which sport with --sport ({', '.join(sports)}) or $RACINGLINES_SPORT",
                  file=sys.stderr)
            return 2
    module = SPORTS.get(sport)
    if module not in sports:
        print(f"racinglines {flat}: not offered for {sport}; it is for {', '.join(sports)}", file=sys.stderr)
        return 2
    print(f"racinglines {flat}: sport {sport}", file=sys.stderr)
    front, back = _hoist(parser_of(module), rest)
    return importlib.import_module(f"racinglines.cli.{module}").main(front + [RENAMED.get(flat, flat)] + back)
