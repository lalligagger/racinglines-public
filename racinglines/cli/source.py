"""
Where a command's data comes from: the one resolver every command goes through (racinglines/cli/__init__.py calls
apply() before anything else is imported, so the settings below reach every module).

    --demo [PACK]   a demo store: a separate database (racinglines_demo_<pack>, on the same server as the configured
                    one) and data folder (data/demo/<pack>) filled from a data pack by the real pipeline
                    (racinglines/demo/store.py), built on first use. PACK defaults to kart; a pack is a folder with a
                    pack.toml (racinglines/demo/packs/, or RACINGLINES_DEMO_PACKS). It only switches the data source:
                    the commands themselves run unchanged. Sets DATABASE_URL, RACINGLINES_DATA and
                    RACINGLINES_OFFLINE=1 (FastF1's servers are never called; the store's files are the record).

    RACINGLINES_DEMO_DATABASE_URL   the demo database (default: the configured URL, named racinglines_demo_<pack>)
    RACINGLINES_DEMO_DATA           the demo data folder (default data/demo/<pack>, gitignored)
"""

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _config():
    from racinglines.cli import config as C
    try:
        return C.load()
    except ValueError:
        return {}


def base_url():
    """The configured database: DATABASE_URL, else the CLI defaults file's `db`, else docker-compose's."""
    from racinglines.db.config import DEFAULT_URL
    return os.environ.get("DATABASE_URL") or _config().get("db") or DEFAULT_URL


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def demo_url(pack):
    from sqlalchemy.engine import make_url
    if os.environ.get("RACINGLINES_DEMO_DATABASE_URL"):
        return os.environ["RACINGLINES_DEMO_DATABASE_URL"]
    return make_url(base_url()).set(database=f"racinglines_demo_{_slug(pack.name)}").render_as_string(hide_password=False)


def demo_data(pack):
    return Path(os.environ.get("RACINGLINES_DEMO_DATA") or ROOT / "data" / "demo" / _slug(pack.name))


def demo_active():
    """The active demo pack's name, or None."""
    return os.environ.get("RACINGLINES_DEMO") or None


def pack(ref=None):
    """The demo pack `ref` (default: the active one, else kart). SystemExit naming the known packs if it isn't one."""
    from racinglines.demo import store
    p = store.find(ref or demo_active())
    if p is None:
        raise SystemExit(f"--demo: no pack {ref!r} (known: {', '.join(store.packs())}; RACINGLINES_DEMO_PACKS adds folders)")
    return p


def use_demo(ref=None, build=True, console=None):
    """Point this process at a demo pack's store (building it first when it is missing or outdated). Returns its URL."""
    pk = pack(ref)
    if demo_active() == pk.name:
        url, data = os.environ["DATABASE_URL"], Path(os.environ["RACINGLINES_DATA"])
    else:
        url, data = demo_url(pk), demo_data(pk)
        os.environ.update(DATABASE_URL=url, RACINGLINES_DATA=str(data), RACINGLINES_OFFLINE="1", RACINGLINES_DEMO=pk.name)
        paths = sys.modules.get("racinglines.paths")
        if paths is not None and Path(paths.DATA) != data:      # imported before: only the database follows
            print(f"demo: data folder stays {paths.DATA} in this process (the database is the demo's)", file=sys.stderr)
    if build:
        ensure(pk, url, data, console)
    return url


def ensure(pk, url, data, console=None):
    from racinglines.demo import store
    try:
        why = store.status(pk, url, data)
    except Exception as ex:                                   # noqa: BLE001  no server: say how to start one
        raise SystemExit(f"demo: no Postgres server for {_safe(url)} ({type(ex).__name__}). Start one with "
                         f"`docker compose up -d` (port 5433, docs/quickstart.md), or set DATABASE_URL to your own "
                         f"server: the demo database is created next to it.") from None
    if why == "ready":
        return
    err = _console(console)
    say = (lambda m: err.print(m)) if err else (lambda m: print(m, file=sys.stderr, flush=True))
    say(f"demo: building the {pk.name} pack's store ({why}): database {store._db_name(url)}, folder {data}. "
        f"Synthetic data, made once (a few minutes).")
    store.build(pk, url, data, console=err)
    say(f"demo: the {pk.name} store is ready ({pk.sport} data; `racinglines db stats --demo {pk.name}`)")


def _console(console):
    if console is not None:
        return console
    try:
        from rich.console import Console
    except ImportError:
        return None
    return Console(stderr=True, highlight=False)


def _safe(url):
    from sqlalchemy.engine import make_url
    return make_url(url).render_as_string(hide_password=True)


def take_demo(argv):
    """(argv without `--demo [PACK]`, the pack ref or None, whether --demo was given). PACK is the next word when it
    names a pack (`--demo=PACK` too)."""
    from racinglines.demo import store
    out, ref, given, i = [], None, False, 0
    while i < len(argv):
        a = argv[i]
        if a == "--demo" or a.startswith("--demo="):
            given = True
            if "=" in a:
                ref = a.split("=", 1)[1]
            elif i + 1 < len(argv) and not argv[i + 1].startswith("-") and store.find(argv[i + 1]) is not None:
                ref = argv[i + 1]
                i += 1
        else:
            out.append(a)
        i += 1
    return out, ref, given


def apply(argv):
    """The argv a command should parse, after the data source is set: `--demo [PACK]` is taken out (the commands don't
    know it) and the pack's store selected."""
    rest, ref, given = take_demo(argv)
    if not given:
        return argv
    use_demo(ref, build=not {"-h", "--help"} & set(rest))
    return rest
