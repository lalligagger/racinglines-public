"""Draft a form email of one F1 weekend's top paper picks on Kalshi and Polymarket.

    .venv/bin/python scripts/weekend_picks.py                       # next scheduled F1 event, top 3
    .venv/bin/python scripts/weekend_picks.py --event-id 89 --top 5
    .venv/bin/python scripts/weekend_picks.py --venues kalshi --min-volume 500

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
import re
import smtplib
import warnings
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


def render_html(info, pricing, picks, rest, venues, username=None):
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
    return f"""<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222222;max-width:720px">
<p>{greeting}</p>
<p>Here are this weekend's top paper picks for the <b>{html.escape(info['title'])}</b> ({_when(info)}), ranked by the
model's expected profit per $1 contract on {" and ".join(v.title() for v in venues)}.</p>
<table style="border-collapse:collapse;border:1px solid #cccccc"><tr>{head}</tr>{body}</table>
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


def send_email(recipient, subject, html_body, text_body, smtp_server="127.0.0.1", smtp_port=1025, smtp_user=None, dry_run=False):
    """Send email via SMTP (e.g., Proton Mail Bridge). Prompts for password securely."""
    if dry_run:
        print(f"[DRY RUN] Would send to {recipient}")
        return True

    if not smtp_user:
        smtp_user = input("SMTP username (Proton email): ")
    password = getpass.getpass("SMTP password: ")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"F1 Paper Picks <{smtp_user}>"
    msg["To"] = recipient

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

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


def send_to_users(conn, min_volume, max_spread, max_picks, smtp_server, smtp_port, smtp_user, dry_run=False):
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
            html_body = render_html(m, m.get("pricing") or {}, picks, rest, exchanges_list)
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
    ap.add_argument("--smtp-server", default="127.0.0.1", help="SMTP server (default: localhost for Proton Bridge)")
    ap.add_argument("--smtp-port", type=int, default=1025, help="SMTP port (default: 1025 for Proton Bridge)")
    ap.add_argument("--smtp-user", help="SMTP username (if not set, prompted at runtime)")
    a = ap.parse_args()

    # Multi-user mode
    if a.send_all or a.user_id:
        with get_engine().connect() as conn:
            if a.send_all:
                send_to_users(conn, a.min_volume, a.max_spread, a.top,
                            smtp_server=a.smtp_server, smtp_port=a.smtp_port,
                            smtp_user=a.smtp_user, dry_run=a.dry_run)
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

                html_body = render_html(m, m.get("pricing") or {}, picks, rest, exchanges_list)
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
    html_body = render_html(m, m.get("pricing") or {}, picks, rest, venues, username=a.username)
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
