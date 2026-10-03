"""Draft a form email of one F1 weekend's top paper picks on Kalshi and Polymarket.

    .venv/bin/python scripts/weekend_picks.py                       # next scheduled F1 event, top 3
    .venv/bin/python scripts/weekend_picks.py --event-id 89 --top 5
    .venv/bin/python scripts/weekend_picks.py --venues kalshi --min-volume 500
    .venv/bin/python scripts/weekend_picks.py --image ~/Downloads/markets.png --email you@example.com
    .venv/bin/python scripts/weekend_picks.py --compose --email you@example.com   # write it with Claude Code instead

Images are local files: the saved .html shows them from disk, and the sent mail carries them as inline (cid:) parts,
which Proton Mail Bridge keeps inline because each has Content-Disposition: inline and a Content-ID.

--compose opens a Claude Code chat (the `claude` CLI) with the racinglines MCP tools: the hosted server when
RACINGLINES_MCP_TOKEN is set, else a local `racinglines mcp` on $DATABASE_URL. Claude asks what the email should say,
pulls the numbers, asks for screenshots (local image paths are embedded when the mail is sent) and writes
subject.txt, email.html and email.txt under <out-dir>/compose-<time>/; exit the chat and the script sends it.

Reads the same market matrix as the MCP `list_markets` tool and ranks every outcome by expected profit per $1
contract: buying YES costs the ask (EV = fair - ask - fee), buying NO costs 1 - bid (EV = bid - fair - fee). Writes
two files under reports/picks/ (gitignored): <event>.html, an email with inline styles and no external CSS, so a
copy from the browser pastes into Gmail or Outlook with the table intact, and <event>.txt, the same picks as plain
lines with no table, for a plain-text mail. Read-only: it places nothing and writes nothing to the database.

The fair values are the live forecast's, which has not seen the weekend's practice or qualifying: the email says so.
"""

import argparse
import getpass
import html
import json
import os
import re
import shutil
import smtplib
import subprocess
import sys
import warnings
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

from sqlalchemy import text

from racinglines.db.config import get_engine
from racinglines.mcp import tools as T
from racinglines.markets import venues as V

warnings.filterwarnings("ignore")

KINDS = "race_win,race_podium,race_top10,race_constructor_top"
LABEL = {"race_win": "to win", "race_podium": "to finish on the podium", "race_top10": "to finish in the top 10",
         "race_constructor_top": "to be the top constructor"}
KALSHI_FEE = 0.07  # estimated taker fee per contract: rate * p * (1 - p)
LINK = {"kalshi": "https://www.coinbase.com/predictions/event/{slug}", "polymarket": "https://polymarket.com/event/{slug}"}


def _fee(venue, price):
    return KALSHI_FEE * price * (1 - price) if venue == "kalshi" else 0.0


def _next_event(conn):
    r = conn.execute(text("""SELECT e.id FROM events e JOIN seasons s ON s.id = e.season_id
        JOIN competitions c ON c.id = s.competition_id
        WHERE c.code = 'f1_wdc' AND e.status = 'scheduled' ORDER BY e.start_date LIMIT 1""")).first()
    if not r:
        raise SystemExit("no scheduled F1 event; pass --event-id")
    return r[0]


def candidates(rows, venues, min_volume, max_spread):
    """Every (outcome, venue, side) with a model fair value and a tradable quote, with its EV per contract."""
    out = []
    for r in rows:
        if r.get("fair") is None:
            continue
        for v in venues:
            bid, ask, vol = r.get(f"{v}_bid"), r.get(f"{v}_ask"), r.get(f"{v}_volume") or 0
            if r.get(f"{v}_closed") or vol < min_volume or ask is None or bid is None or ask - bid > max_spread:
                continue
            for side, price, win in (("YES", ask, r["fair"]), ("NO", 1 - bid, 1 - r["fair"])):
                ev = win - price - _fee(v, price)
                if ev > 0:
                    out.append(dict(subject=r["subject"], kind=r["kind"], venue=v, side=side, token=r[f"{v}_token"],
                                    model=win, price=price, ev=ev, roi=ev / price, volume=vol))
    return sorted(out, key=lambda c: -c["ev"])


def _links(conn, picks):
    toks = [p["token"] for p in picks if p["token"]]
    got = {}
    if toks:
        for t, slug in conn.execute(text("SELECT token_id, event_slug FROM market_links WHERE token_id = ANY(:t)"), {"t": toks}):
            got[t] = slug
    for p in picks:
        slug = got.get(p["token"])
        p["url"] = LINK[p["venue"]].format(slug=slug) if slug else None


def _bet(p):
    return f"{p['subject']} {LABEL.get(p['kind'], p['kind'])}"


def _when(info):
    return str(info.get("start_date") or "")[:10]


def render_html(info, pricing, picks, rest, venues, username=None, images=()):
    greeting = f"Hi {username}," if username else "Hi,"
    td = 'style="padding:6px 10px;border:1px solid #cccccc;text-align:{a};font-size:14px"'
    head = "".join(f'<th {td.format(a="left")[:-1]};background:#f0f0f0">{h}</th>' for h in
                   ("#", "Bet", "Side", "Venue", "Model: side wins", "Price", "EV / $1", "Volume", "Link"))
    body = ""
    for i, p in enumerate(picks, 1):
        link = f'<a href="{html.escape(p["url"])}">open</a>' if p["url"] else "n/a"
        cells = [i, html.escape(_bet(p)), f"<b>{p['side']}</b>", p["venue"].title(), f"{p['model']:.0%}",
                 f"{p['price'] * 100:.0f}¢", f"+{p['ev'] * 100:.1f}¢ ({p['roi']:+.0%})", f"${p['volume']:,.0f}", link]
        body += "<tr>" + "".join(f'<td {td.format(a="left")}>{c}</td>' for c in cells) + "</tr>"
    more = "".join(f"<li>{html.escape(_bet(p))}: {p['side']} on {p['venue'].title()}, +{p['ev'] * 100:.1f}¢</li>" for p in rest)
    shots = "".join(f'<p><img src="{html.escape(str(i))}" style="max-width:100%;height:auto"></p>' for i in images)
    return f"""<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222222;max-width:720px">
<p>{greeting}</p>
<p>Here are this weekend's top paper picks for the <b>{html.escape(info['title'])}</b> ({_when(info)}), ranked by the
model's expected profit per $1 contract on {" and ".join(v.title() for v in venues)}.</p>
<table style="border-collapse:collapse;border:1px solid #cccccc"><tr>{head}</tr>{body}</table>
{shots}
{"<p><b>Next in line:</b></p><ul>" + more + "</ul>" if rest else ""}
<p><b>Read these with care.</b> Prices are from {html.escape(str(pricing.get('source', 'the live forecast')))}, which
has not seen this weekend's practice or qualifying, so the biggest gaps are where the model is most likely wrong.
EV is the model's fair value against the quote you would trade at (ask for YES, 1 minus bid for NO), less an
estimated Kalshi fee of {KALSHI_FEE:.0%} x p x (1 - p). Picks on the same driver or team are correlated. Paper
trading only: nothing here has been placed.</p>
<p>Check the YES/NO label and the live price on the venue before you size anything.</p>
</div>"""


def render_text(info, pricing, picks, rest, venues, username=None):
    greeting = f"Hi {username}," if username else "Hi,"
    lines = [greeting, "", f"Top paper picks for the {info['title']} ({_when(info)}), ranked by the model's expected "
             f"profit per $1 contract on {' and '.join(v.title() for v in venues)}.", ""]
    for i, p in enumerate(picks, 1):
        lines += [f"{i}. {_bet(p)}: buy {p['side']} on {p['venue'].title()}",
                  f"   model gives this side {p['model']:.0%} vs price {p['price'] * 100:.0f}c, EV +{p['ev'] * 100:.1f}c per $1 ({p['roi']:+.0%}), "
                  f"volume ${p['volume']:,.0f}", f"   {p['url'] or 'no link on file'}", ""]
    if rest:
        lines += ["Next in line:"] + [f"- {_bet(p)}: {p['side']} on {p['venue'].title()}, +{p['ev'] * 100:.1f}c" for p in rest] + [""]
    lines += [f"Read with care: prices are from {pricing.get('source', 'the live forecast')}, which has not seen this "
              "weekend's practice or qualifying, so the biggest gaps are where the model is most likely wrong. EV is "
              "fair value against the quote you would trade at, less an estimated Kalshi fee. Picks on the same "
              "driver or team are correlated. Paper trading only: nothing here has been placed.", "",
              "Check the YES/NO label and the live price on the venue before you size anything."]
    return "\n".join(lines)


def _inline_images(html_body):
    """Swap every <img src> that names a local file for a cid: reference, so the mail carries the image itself."""
    images = []

    def swap(m):
        path = Path(html.unescape(m.group(2)).removeprefix("file://")).expanduser()
        if not path.is_file():
            return m.group(0)
        cid = f"img{len(images)}@racinglines"
        images.append((cid, path))
        return f"{m.group(1)}cid:{cid}{m.group(3)}"

    return re.sub(r'(<img\b[^>]*?\bsrc=["\'])([^"\']+)(["\'])', swap, html_body, flags=re.I), images


def send_email(recipient, subject, html_body, text_body, smtp_server="127.0.0.1", smtp_port=1025, smtp_user=None, dry_run=False):
    """Send email via SMTP (e.g., Proton Mail Bridge). Prompts for password securely."""
    if dry_run:
        print(f"[DRY RUN] Would send to {recipient}")
        return True

    if not smtp_user:
        smtp_user = input("SMTP username (Proton email): ")
    password = getpass.getpass("SMTP password: ")

    html_body, images = _inline_images(html_body)
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text_body, "plain"))
    alt.attach(MIMEText(html_body, "html"))
    msg = alt
    if images:
        msg = MIMEMultipart("related")
        msg.attach(alt)
        for cid, path in images:
            img = MIMEImage(path.read_bytes())
            img.add_header("Content-ID", f"<{cid}>")
            img.add_header("Content-Disposition", "inline", filename=path.name)
            msg.attach(img)
    msg["Subject"] = subject
    msg["From"] = f"Racinglines <{smtp_user}>"
    msg["To"] = recipient

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
            server.ehlo()
            if server.has_extn("starttls"):
                server.starttls()  # Bridge's certificate is self-signed; the stdlib default context doesn't verify it
                server.ehlo()
            server.login(smtp_user, password)
            server.sendmail(smtp_user, recipient, msg.as_string())
        print(f"Sent to {recipient}")
        return True
    except Exception as e:
        print(f"Failed to send to {recipient}: {e}", file=__import__("sys").stderr)
        return False


COMPOSE_BRIEF = """You are helping the racinglines owner write this weekend's picks email, in place of the fixed template of
scripts/weekend_picks.py. The racinglines MCP tools are connected: use them (overview, list_events, list_markets,
get_forecast, get_market_history, track_record, ...) for every number you put in the email, and never invent one.

Work with the owner step by step:
1. Ask who the email is for and what it should cover (picks, market moves, commentary, a product update), how many
   picks, which venues (Kalshi, Polymarket) and which angles or drivers to feature.
2. Pull the data and propose the content. Rank picks the way the template does: buying YES costs the ask,
   EV = fair - ask - fee; buying NO costs 1 - bid, EV = bid - fair - fee; Kalshi's fee is about 0.07 x p x (1 - p).
   Skip books wider than 15c and markets with under $100 volume unless the owner says otherwise.
3. Ask whether a screenshot would help (a chart, the Markets page). The owner saves it and gives you its absolute
   path; reference it as <img src="/absolute/path.png" style="max-width:100%">. The script embeds local images
   when it sends the mail.
4. Keep the template's caveats unless told otherwise: fair values have not seen this weekend's practice or
   qualifying, picks on one driver or team are correlated, paper trading only, check the YES/NO label and the live
   price before sizing anything.
5. When the owner approves the draft, write exactly three files into the folder
   {out}
   namely subject.txt (one line), email.html (inline styles only, no external CSS, max-width 720px, so it pastes into Gmail
   or Outlook), and email.txt (the same email as plain text). Then tell the owner to exit (/exit or Ctrl-D) and the
   script takes over.
{seed}"""


def _template_seed(venues, min_volume, max_spread, top):
    """The template's own top picks, as a starting point for the chat; empty when this machine has no database."""
    try:
        with get_engine().connect() as conn:
            event_id = _next_event(conn)
            race_id = conn.execute(text("SELECT id FROM races WHERE event_id = :e ORDER BY id LIMIT 1"), {"e": event_id}).scalar()
            info, pricing, df = V.event_matrix(conn, race_id)
            want = [k.strip() for k in KINDS.split(",")]
            rows = T._matrix_rows(df[df["kind"].isin(want)]) if len(df) else []
            cands = candidates(rows, venues, min_volume, max_spread)[:top + 3]
            _links(conn, cands)
    except Exception as e:  # noqa: BLE001  (no reachable database here: the chat pulls everything over MCP)
        print(f"no local picks to seed the chat ({type(e).__name__}); Claude will pull them over MCP", file=sys.stderr)
        return ""
    lines = [f"\nThe template's picks for the {info['title']} ({_when(info)}), from {(pricing or {}).get('source', 'the live forecast')}:"]
    lines += [f"- {_bet(p)}: {p['side']} on {p['venue'].title()}, model {p['model']:.0%} vs {p['price'] * 100:.0f}c, "
              f"EV +{p['ev'] * 100:.1f}c, volume ${p['volume']:,.0f}, {p['url'] or 'no link'}" for p in cands]
    return "\n".join(lines)


def _mcp_config(mcp_url):
    """The racinglines MCP server for this session: the hosted one when RACINGLINES_MCP_TOKEN is set, else a local
    `racinglines mcp` over stdio (reads $DATABASE_URL, so run it where the database is)."""
    token = os.environ.get("RACINGLINES_MCP_TOKEN")
    if token:
        server = {"type": "http", "url": mcp_url, "headers": {"Authorization": f"Bearer {token}"}}
    else:
        server = {"command": str(Path(sys.executable).with_name("racinglines")), "args": ["mcp"]}
    return json.dumps({"mcpServers": {"racinglines": server}})


def compose_email_interactive(out_dir, venues, min_volume, max_spread, top, mcp_url):
    """Open a Claude Code chat with the racinglines MCP tools to write the email; returns (subject, html, text), or
    None when the chat ended without writing the three files."""
    claude = shutil.which("claude")
    if not claude:
        raise SystemExit("--compose needs the Claude Code CLI (`claude`) on PATH")
    out = Path(out_dir) / f"compose-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    brief = COMPOSE_BRIEF.format(out=out.resolve(), seed=_template_seed(venues, min_volume, max_spread, top))
    subprocess.run([claude, "Help me write this weekend's picks email.", "--mcp-config", _mcp_config(mcp_url),
                    "--append-system-prompt", brief])
    files = [out / n for n in ("subject.txt", "email.html", "email.txt")]
    if not all(f.exists() for f in files):
        print(f"the chat ended without writing {', '.join(f.name for f in files if not f.exists())} in {out}", file=sys.stderr)
        return None
    print(f"wrote {out}")
    return tuple(f.read_text().strip() if f.name == "subject.txt" else f.read_text() for f in files)


def send_to_users(conn, min_volume, max_spread, max_picks, smtp_server, smtp_port, smtp_user, dry_run=False, images=()):
    """Send F1 weekend picks to all users with registered emails, respecting their exchange preferences."""
    import sys
    from racinglines.db.models import UserEmailPrefs

    # Fetch next F1 event
    event_id = _next_event(conn)
    race_id = conn.execute(text("SELECT id FROM races WHERE event_id = :e ORDER BY id LIMIT 1"), {"e": event_id}).scalar()
    info, pricing, df = V.event_matrix(conn, race_id)
    m = dict(title=info["title"], start_date=info["start_date"], pricing=pricing or {})
    want = [k.strip() for k in KINDS.split(",")]
    rows = T._matrix_rows(df[df["kind"].isin(want)]) if len(df) else []

    if not rows:
        print("No rows from event matrix", file=sys.stderr)
        return

    # Fetch all users with registered emails
    users = conn.execute(text("""
        SELECT id, email, exchanges FROM user_email_prefs
        WHERE email IS NOT NULL
        ORDER BY id
    """)).fetchall()

    if not users:
        print("No users with registered emails")
        return

    subject_template = f"F1 paper picks: {m['title']} ({_when(m)})"
    sent_count = 0
    failed_count = 0

    for user_id, email, exchanges in users:
        try:
            # exchanges is a list like ['polymarket', 'kalshi']
            exchanges_list = list(exchanges) if exchanges else ["polymarket"]

            # Generate picks for this user's exchanges
            cands = candidates(rows, exchanges_list, min_volume, max_spread)
            if not cands:
                print(f"[user {user_id}] No picks for exchanges {exchanges_list}", file=sys.stderr)
                continue

            picks, rest = cands[:max_picks], cands[max_picks:max_picks + 3]
            _links(conn, picks + rest)

            # Render email
            html_body = render_html(m, m.get("pricing") or {}, picks, rest, exchanges_list, images=images)
            text_body = render_text(m, m.get("pricing") or {}, picks, rest, exchanges_list)

            # Send email
            success = send_email(email, subject_template, html_body, text_body,
                               smtp_server=smtp_server, smtp_port=smtp_port,
                               smtp_user=smtp_user, dry_run=dry_run)

            if success:
                sent_count += 1
                print(f"[user {user_id}] Sent F1 picks ({len(picks)} picks) to {email}", file=sys.stderr)
            else:
                failed_count += 1
        except Exception as e:
            failed_count += 1
            print(f"[user {user_id}] Error: {e}", file=sys.stderr)

    print(f"\n=== Summary ===", file=sys.stderr)
    print(f"Sent: {sent_count}, Failed: {failed_count}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])

    # Multi-user mode
    ap.add_argument("--send-all", action="store_true", help="send F1 picks to all users with registered emails")
    ap.add_argument("--user-id", type=int, help="send to specific user ID (from user_email_prefs)")
    ap.add_argument("--dry-run", action="store_true", help="print what would be sent (no SMTP)")

    # Compose mode: a Claude Code chat writes the email instead of the template
    ap.add_argument("--compose", action="store_true",
                    help="write the email in a Claude Code chat with the racinglines MCP tools; with --email or --send-all, send it")
    ap.add_argument("--mcp-url", default="https://mcp.racinglines.bet/mcp",
                    help="hosted MCP server for --compose, used when RACINGLINES_MCP_TOKEN is set")

    # Single-user mode (backward compatible)
    ap.add_argument("--event-id", type=int, help="default: the next scheduled F1 event")
    ap.add_argument("--venues", default="kalshi,polymarket")
    ap.add_argument("--kinds", default=KINDS)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--min-volume", type=float, default=100, help="skip markets with less volume than this (USD)")
    ap.add_argument("--max-spread", type=float, default=0.15, help="skip books wider than this (drops 1c/99c placeholders)")
    ap.add_argument("--out-dir", default="reports/picks")
    ap.add_argument("--email", help="recipient email address; if set, sends the picks via SMTP")
    ap.add_argument("--username", help="personalize greeting with username")
    ap.add_argument("--image", action="append", default=[], metavar="PATH",
                    help="a screenshot or chart to show under the picks table (repeatable); embedded in the mail when sent")
    ap.add_argument("--smtp-server", default="127.0.0.1", help="SMTP server (default: localhost for Proton Bridge)")
    ap.add_argument("--smtp-port", type=int, default=1025, help="SMTP port (default: 1025 for Proton Bridge)")
    ap.add_argument("--smtp-user", help="SMTP username (if not set, prompted at runtime)")
    a = ap.parse_args()
    a.image = [Path(i).expanduser().resolve() for i in a.image]
    if missing := [str(i) for i in a.image if not i.is_file()]:
        raise SystemExit(f"--image: no such file: {', '.join(missing)}")

    if a.compose:
        venues = [v.strip() for v in a.venues.split(",") if v.strip()]
        composed = compose_email_interactive(a.out_dir, venues, a.min_volume, a.max_spread, a.top, a.mcp_url)
        if not composed:
            return
        subject, html_body, text_body = composed
        print(f"Subject: {subject}")
        recipients = [a.email] if a.email else []
        if a.send_all:
            with get_engine().connect() as conn:
                recipients += [r[0] for r in conn.execute(text("SELECT email FROM user_email_prefs WHERE email IS NOT NULL ORDER BY id"))]
        for r in recipients:
            send_email(r, subject, html_body, text_body, smtp_server=a.smtp_server, smtp_port=a.smtp_port,
                       smtp_user=a.smtp_user, dry_run=a.dry_run)
        return

    # Multi-user mode
    if a.send_all or a.user_id:
        with get_engine().connect() as conn:
            if a.send_all:
                send_to_users(conn, a.min_volume, a.max_spread, a.top,
                            smtp_server=a.smtp_server, smtp_port=a.smtp_port,
                            smtp_user=a.smtp_user, dry_run=a.dry_run, images=a.image)
            elif a.user_id:
                # Single user from DB
                user_row = conn.execute(text(
                    "SELECT email, exchanges FROM user_email_prefs WHERE id = :uid"
                ), {"uid": a.user_id}).first()
                if not user_row:
                    raise SystemExit(f"User {a.user_id} not found")
                email, exchanges = user_row
                if not email:
                    raise SystemExit(f"User {a.user_id} has no email registered")

                exchanges_list = list(exchanges) if exchanges else ["polymarket"]

                # Get F1 event
                event_id = a.event_id or _next_event(conn)
                race_id = conn.execute(text("SELECT id FROM races WHERE event_id = :e ORDER BY id LIMIT 1"), {"e": event_id}).scalar()
                info, pricing, df = V.event_matrix(conn, race_id)
                m = dict(title=info["title"], start_date=info["start_date"], pricing=pricing or {})
                want = [k.strip() for k in a.kinds.split(",")]
                rows = T._matrix_rows(df[df["kind"].isin(want)]) if len(df) else []
                cands = candidates(rows, exchanges_list, a.min_volume, a.max_spread)
                picks, rest = cands[:a.top], cands[a.top:a.top + 3]
                _links(conn, picks + rest)

                if not picks:
                    raise SystemExit("no pick clears the filters; try a lower --min-volume or a wider --max-spread")

                html_body = render_html(m, m.get("pricing") or {}, picks, rest, exchanges_list, images=a.image)
                text_body = render_text(m, m.get("pricing") or {}, picks, rest, exchanges_list)
                subject = f"F1 paper picks: {m['title']} ({_when(m)})"
                print(f"Subject: {subject}")

                send_email(email, subject, html_body, text_body,
                          smtp_server=a.smtp_server, smtp_port=a.smtp_port,
                          smtp_user=a.smtp_user, dry_run=a.dry_run)
        return

    # Single-user mode (backward compatible with original script)
    venues = [v.strip() for v in a.venues.split(",") if v.strip()]
    with get_engine().connect() as conn:
        event_id = a.event_id or _next_event(conn)
        race_id = conn.execute(text("SELECT id FROM races WHERE event_id = :e ORDER BY id LIMIT 1"), {"e": event_id}).scalar()
        info, pricing, df = V.event_matrix(conn, race_id)  # not list_markets: its byte cap drops rows
        m = dict(title=info["title"], start_date=info["start_date"], pricing=pricing or {})
        want = [k.strip() for k in a.kinds.split(",")]
        rows = T._matrix_rows(df[df["kind"].isin(want)]) if len(df) else []
        cands = candidates(rows, venues, a.min_volume, a.max_spread)
        picks, rest = cands[:a.top], cands[a.top:a.top + 3]
        _links(conn, picks + rest)
    if not picks:
        raise SystemExit("no pick clears the filters; try a lower --min-volume or a wider --max-spread")
    stem = re.sub(r"[^a-z0-9]+", "-", f"{_when(m)}-{m['title']}".lower()).strip("-")
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    html_body = render_html(m, m.get("pricing") or {}, picks, rest, venues, username=a.username, images=a.image)
    text_body = render_text(m, m.get("pricing") or {}, picks, rest, venues, username=a.username)
    (out / f"{stem}.html").write_text(html_body)
    (out / f"{stem}.txt").write_text(text_body)
    subject = f"F1 paper picks: {m['title']} ({_when(m)})"
    print(f"Subject: {subject}")
    print(f"wrote {out / (stem + '.html')} and {out / (stem + '.txt')}")

    if a.email:
        send_email(a.email, subject, html_body, text_body,
                   smtp_server=a.smtp_server, smtp_port=a.smtp_port,
                   smtp_user=a.smtp_user, dry_run=a.dry_run)


if __name__ == "__main__":
    main()
