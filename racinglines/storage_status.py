"""
Where the data lives and how big it is: the VM's disk, data folders and databases, and the data bucket's prefixes
(owner, 2026-10-14: "our status includes all bucket data stats as well as what is on VM").

    vm        disk total / used / free (the filesystem holding data/), and per data root (this checkout's data/ and
              the other app checkout's on the VM) each top-level folder's size, file count and newest file; the
              database dumps in backups/db counted on their own
    db        every database this role may connect to, with pg_database_size
    buckets   per bucket (RACINGLINES_STATUS_BUCKETS, comma-separated; default the primary data bucket) each top-level
              prefix and the folders under it (vendor/probalytics, backups/prod, ...): size, objects, newest object,
              from `gcloud storage ls --long --recursive` (the VM's service account can list the bucket)

Listing a 20+ GB bucket and walking the archive is slow, so nothing here runs on a page load: `refresh()` writes a
JSON snapshot (data/status/storage.json) that the admin Database page (/admin/db; owner, 2026-10-14), `racinglines db storage` and the MCP tool
`storage_status` read, with `health()` (disk room, the bucket reachable, the VM's newest dumps and data folders also in the bucket).
The page starts a background refresh when the snapshot is older than STALE_SECONDS.

Sizes and counts only, never file contents: the bucket holds licensed vendor data (Probalytics, ToS section 5), so this
is admin-only everywhere it is shown.
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from racinglines import paths

DEFAULT_BUCKETS = ("racinglines-data-384052502248",)
APP_CHECKOUTS = ("/opt/racinglines", "/opt/racinglines-staging")      # prod and staging on the VM (docs/vm-deploy.md)
STALE_SECONDS = 6 * 3600
GCLOUD_TIMEOUT = 1800

_LOCK = threading.Lock()
_RUNNING = False


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") if ts else None


def snapshot_path():
    return Path(paths.DATA) / "status" / "storage.json"


def buckets():
    raw = os.environ.get("RACINGLINES_STATUS_BUCKETS", "")
    return [b.strip().removeprefix("gs://").strip("/") for b in raw.split(",") if b.strip()] or list(DEFAULT_BUCKETS)


def data_roots():
    """This checkout's data/ first, then the other app checkout's on the VM when it is there."""
    roots = [Path(paths.DATA)]
    extra = os.environ.get("RACINGLINES_STATUS_DATA_ROOTS")
    cands = [Path(p) for p in extra.split(":") if p] if extra is not None else [Path(c) / "data" for c in APP_CHECKOUTS]
    for p in cands:
        if p.is_dir() and all(p.resolve() != r.resolve() for r in roots):
            roots.append(p)
    return roots


def _walk(path):
    """(bytes, files, newest mtime) under path, without following links; unreadable entries are skipped."""
    size = files = 0
    newest = 0.0
    stack = [path]
    while stack:
        try:
            it = os.scandir(stack.pop())
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        st = e.stat(follow_symlinks=False)
                        size, files, newest = size + st.st_size, files + 1, max(newest, st.st_mtime)
                except OSError:
                    continue
    return size, files, newest


def _root_stats(root):
    folders, loose = [], [0, 0, 0.0]
    for e in sorted(os.scandir(root), key=lambda e: e.name):
        if e.is_dir(follow_symlinks=False):
            b, n, t = _walk(e.path)
            folders.append(dict(name=e.name, bytes=b, files=n, newest=_iso(t)))
        elif e.is_file(follow_symlinks=False):
            st = e.stat(follow_symlinks=False)
            loose = [loose[0] + st.st_size, loose[1] + 1, max(loose[2], st.st_mtime)]
    if loose[1]:
        folders.append(dict(name="(files at the top)", bytes=loose[0], files=loose[1], newest=_iso(loose[2])))
    dumps = sorted((root / "backups" / "db").glob("*.sql.gz")) if (root / "backups" / "db").is_dir() else []
    dumps.sort(key=lambda p: p.stat().st_mtime)
    backups = dict(dumps=len(dumps), bytes=sum(p.stat().st_size for p in dumps),
                   newest=dumps[-1].name if dumps else None, newest_at=_iso(dumps[-1].stat().st_mtime) if dumps else None)
    return dict(path=str(root), bytes=sum(f["bytes"] for f in folders), folders=folders, backups=backups)


def vm_stats():
    du = shutil.disk_usage(paths.DATA if Path(paths.DATA).exists() else "/")
    return dict(disk=dict(total=du.total, used=du.used, free=du.free),
                roots=[_root_stats(r) for r in data_roots()])


def db_stats(conn):
    from sqlalchemy import text
    rows = conn.execute(text("""SELECT datname, pg_database_size(datname) AS bytes FROM pg_database
                                WHERE NOT datistemplate AND has_database_privilege(datname, 'CONNECT')
                                ORDER BY datname""")).all()
    return [dict(name=r[0], bytes=int(r[1])) for r in rows]


_LS_LINE = re.compile(r"^\s*(\d+)\s+(\d{4}-\d\d-\d\dT\S+)\s+(gs://\S+)\s*$")


def parse_ls(text, bucket):
    """`gcloud storage ls --long --recursive gs://BUCKET` -> per top-level prefix and the folders under it:
    [dict(prefix, bytes, objects, newest, children=[...])]. Objects at the bucket's top count under "(top)"."""
    tops = {}
    head = f"gs://{bucket}/"
    for line in text.splitlines():
        m = _LS_LINE.match(line)
        if not m or not m.group(3).startswith(head):
            continue
        size, at, name = int(m.group(1)), m.group(2), m.group(3)[len(head):]
        parts = name.split("/")
        keys = [parts[0] + "/" if len(parts) > 1 else "(top)"]
        if len(parts) > 2:
            keys.append(parts[0] + "/" + parts[1] + "/")
        for depth, k in enumerate(keys):
            node = tops.setdefault(keys[0], dict(prefix=keys[0], bytes=0, objects=0, newest=None, children={}))
            if depth:
                node = node["children"].setdefault(k, dict(prefix=k, bytes=0, objects=0, newest=None))
            node["bytes"] += size
            node["objects"] += 1
            node["newest"] = max(node["newest"] or at, at)
    out = []
    for t in sorted(tops.values(), key=lambda t: t["prefix"]):
        t["children"] = sorted(t["children"].values(), key=lambda c: c["prefix"])
        out.append(t)
    return out


def _gcloud_ls(bucket):
    exe = shutil.which("gcloud")
    if not exe:
        raise RuntimeError("gcloud is not installed here")
    r = subprocess.run([exe, "storage", "ls", "--long", "--recursive", f"gs://{bucket}"], capture_output=True,
                       text=True, timeout=GCLOUD_TIMEOUT)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1][:300] if (r.stderr or r.stdout).strip()
                           else f"gcloud exited {r.returncode}")
    return r.stdout


def bucket_stats(bucket, ls=None):
    try:
        prefixes = parse_ls((ls or _gcloud_ls)(bucket), bucket)
    except Exception as ex:  # noqa: BLE001  (no gcloud, no access, a timeout: shown on the page, never raised)
        return dict(bucket=bucket, error=f"{type(ex).__name__}: {ex}")
    return dict(bucket=bucket, bytes=sum(p["bytes"] for p in prefixes), objects=sum(p["objects"] for p in prefixes),
                prefixes=prefixes)


def build(conn=None, ls=None):
    """The whole snapshot (nothing written). conn: a database connection for the sizes, or None to skip them."""
    t0 = time.monotonic()
    snap = dict(taken_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), vm=vm_stats())
    try:
        snap["databases"] = db_stats(conn) if conn is not None else []
    except Exception as ex:  # noqa: BLE001
        snap["databases"], snap["databases_error"] = [], f"{type(ex).__name__}: {str(ex).splitlines()[0][:300]}"
    snap["buckets"] = [bucket_stats(b, ls) for b in buckets()]
    snap["seconds"] = round(time.monotonic() - t0, 1)
    return snap


def refresh(conn=None, ls=None):
    """Build the snapshot and write it (atomically) to data/status/storage.json; returns it."""
    snap = build(conn, ls)
    p = snapshot_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snap, indent=1))
    tmp.replace(p)
    return snap


def read():
    """The last snapshot, or None before the first refresh."""
    try:
        return json.loads(snapshot_path().read_text())
    except (OSError, ValueError):
        return None


def age_seconds(snap):
    if not snap or not snap.get("taken_at"):
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(snap["taken_at"])).total_seconds()


def refreshing():
    return _RUNNING


def refresh_in_background(force=False):
    """Start one refresh in a thread (its own database connection) when the snapshot is missing or stale, or when
    forced; at most one at a time. Returns whether one started."""
    global _RUNNING
    with _LOCK:
        age = age_seconds(read())
        if _RUNNING or not (force or age is None or age >= STALE_SECONDS):
            return False
        _RUNNING = True

    def run():
        global _RUNNING
        try:
            from racinglines.db.config import get_engine
            with get_engine().connect() as c:            # the app's shared (cached) engine: never disposed here
                refresh(c)
        except Exception:  # noqa: BLE001  (the page keeps showing the last snapshot)
            pass
        finally:
            with _LOCK:
                _RUNNING = False

    threading.Thread(target=run, name="storage-status", daemon=True).start()
    return True


def human(n):
    """Bytes as a short size: 4.6 GB, 120 MB (decimal units, like the plan doc and `df -H`)."""
    if n is None:
        return ""
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if abs(n) < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000


def lines(snap):
    """The snapshot as plain text lines (the CLI's output; the page and MCP use the dict)."""
    if not snap:
        return ["no storage snapshot yet: run `racinglines db storage --refresh`"]
    d = snap["vm"]["disk"]
    out = [f"snapshot {snap['taken_at']} (took {snap.get('seconds')} s)", ""]
    out += [f"[{h['state']:>4}] {h['check']}: {h['text']}" for h in health(snap)] + ["",
           f"VM disk: {human(d['free'])} free of {human(d['total'])} ({human(d['used'])} used)"]
    for r in snap["vm"]["roots"]:
        out.append(f"  {r['path']}  {human(r['bytes'])}")
        for f in sorted(r["folders"], key=lambda f: -f["bytes"]):
            out.append(f"    {f['name'] + '/':<24} {human(f['bytes']):>9} {f['files']:>9,} files  newest {f['newest'] or '-'}")
        b = r["backups"]
        out.append(f"    backups/db dumps: {b['dumps']} ({human(b['bytes'])}), newest {b['newest'] or '-'}")
    out += ["", "Databases:"] + [f"  {x['name']:<28} {human(x['bytes']):>9}" for x in snap.get("databases", [])]
    if snap.get("databases_error"):
        out.append(f"  (not read: {snap['databases_error']})")
    for b in snap.get("buckets", []):
        out.append("")
        if b.get("error"):
            out.append(f"gs://{b['bucket']}: not listed ({b['error']})")
            continue
        out.append(f"gs://{b['bucket']}  {human(b['bytes'])}, {b['objects']:,} objects")
        for p in b["prefixes"]:
            out.append(f"  {p['prefix']:<30} {human(p['bytes']):>9} {p['objects']:>9,} objects  newest {p['newest']}")
            for c in p["children"]:
                out.append(f"    {c['prefix']:<28} {human(c['bytes']):>9} {c['objects']:>9,} objects  newest {c['newest']}")
    return out


LOW_DISK_BYTES = 5_000_000_000
LOW_DISK_SHARE = 0.10


def _bucket_backups(snap, root_path):
    """The bucket folder a data root's backups are copied to: backups/staging/ for the staging checkout, else
    backups/prod/ (the copy in docs/vm-deploy.md), and its node in the first listed bucket that has it."""
    want = "backups/staging/" if "racinglines-staging" in root_path else "backups/prod/"
    for b in snap.get("buckets", []):
        for p in b.get("prefixes", []):
            for c in p.get("children", []):
                if c["prefix"] == want:
                    return b["bucket"], c
    return None, None


def health(snap):
    """VM and bucket health and the link between them, from a snapshot: [dict(check, state ok|warn|bad, text)].
    Disk room, the bucket listed from here, and each data root's newest database dump also being in the bucket."""
    if not snap:
        return []
    out = []
    d = snap["vm"]["disk"]
    low = d["free"] < LOW_DISK_BYTES or (d["total"] and d["free"] / d["total"] < LOW_DISK_SHARE)
    out.append(dict(check="VM disk", state="warn" if low else "ok",
                    text=f"{human(d['free'])} free of {human(d['total'])}" + (" (low)" if low else "")))
    for b in snap.get("buckets", []):
        out.append(dict(check=f"VM → gs://{b['bucket']}", state="bad" if b.get("error") else "ok",
                        text=f"not listed: {b['error']}" if b.get("error") else
                        f"listed from the VM: {human(b['bytes'])}, {b['objects']:,} objects"))
    tops = {p["prefix"].rstrip("/"): (b["bucket"], p) for b in reversed(snap.get("buckets", [])) for p in b.get("prefixes", [])}
    for r in snap["vm"]["roots"]:
        if "racinglines-staging" in r["path"]:
            continue                                   # the bucket's data folders are prod's copies (bucket.sh FOLDERS)
        for f in r["folders"]:
            if f["name"] not in tops or f["name"] == "backups" or not f["newest"]:
                continue
            bucket, node = tops[f["name"]]
            behind = (node["newest"] or "")[:19] < f["newest"][:19]
            out.append(dict(check=f"{f['name']}/ copy", state="warn" if behind else "ok",
                            text=f"newest on the VM {f['newest']}, in gs://{bucket}/{node['prefix']} {node['newest']}"
                                 + (": the bucket is behind" if behind else "")))
    for r in snap["vm"]["roots"]:
        dumps = r["backups"]
        if not dumps["dumps"]:
            continue
        bucket, node = _bucket_backups(snap, r["path"])
        where = f"gs://{bucket}/{node['prefix']}" if node else "the bucket"
        if node is None:
            out.append(dict(check=f"Backups {r['path']}", state="warn",
                            text=f"newest dump {dumps['newest']} ({dumps['newest_at']}); no backup folder in the bucket"))
            continue
        behind = (node["newest"] or "")[:19] < (dumps["newest_at"] or "")[:19]
        out.append(dict(check=f"Backups {r['path']}", state="warn" if behind else "ok",
                        text=f"newest dump {dumps['newest_at']}, newest in {where} {node['newest']}"
                             + (": the bucket is behind" if behind else "")))
    return out
