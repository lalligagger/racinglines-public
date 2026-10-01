"""Browser click-through of the demo, as a new visitor sees it (read-only; GET pages only).

    python scripts/deploy/browser_smoke.py https://racinglines.bet [--out reports/browser-smoke]

For each one-click demo tier (pro, basic): open /login, click "Try as pro" / "Try as basic", then visit every
same-site link on the landing page and one level below it (at most --max pages per tier). It records each page's
HTTP status, JavaScript errors and broken same-site links, saves a screenshot of each page reached from the
landing page (683x900 CSS px at 1.5x = 1024 px wide, the report rule), and prints one line per problem. Exit 1 if
any page answers 400 or more or throws a JavaScript error.

Needs Playwright (not in requirements.txt): pip install playwright && python -m playwright install chromium
"""

import argparse
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

SKIP = ("/logout", "/static/", "/admin")          # sign-out ends the run; admin is not a demo page
TIERS = (("pro", "Try as pro"), ("basic", "Try as basic"))


def same_site_links(page, base):
    host = urlparse(base).netloc
    hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
    out = []
    for h in hrefs:
        if not h or h.startswith(("#", "mailto:", "javascript:")):
            continue
        u = urljoin(page.url, h)
        p = urlparse(u)
        if p.netloc == host and not p.path.startswith(SKIP):
            out.append(u.split("#")[0])
    return out


def run_tier(browser, base, tier, button, out, limit):
    ctx = browser.new_context(viewport={"width": 683, "height": 900}, device_scale_factor=1.5)
    ctx.add_init_script("try { sessionStorage.setItem('racinglines-notice-ok', '1') } catch (e) {}")  # no popup
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    problems, seen = [], {}
    page.goto(urljoin(base, "/login"))
    page.get_by_role("button", name=button).click()
    page.wait_for_load_state("networkidle")
    landing = page.url
    print(f"{tier}: signed in, landed on {urlparse(landing).path}", flush=True)
    first = list(dict.fromkeys(same_site_links(page, base)))
    queue = [(u, landing, True) for u in first]
    started = time.time()
    while queue and len(seen) < limit:
        url, src, shoot = queue.pop(0)
        if url in seen:
            continue
        before = len(errors)
        try:
            resp = page.goto(url, wait_until="networkidle", timeout=45000)
            code = resp.status if resp else 0
        except Exception as e:                    # a timeout or a dropped connection is a problem, not a crash
            code = 0
            errors.append(f"load failed: {e}")
        seen[url] = code
        path = urlparse(url).path + (f"?{urlparse(url).query}" if urlparse(url).query else "")
        if code >= 400 or code == 0:
            problems.append(f"{tier}: {code} {path} (linked from {urlparse(src).path})")
        for e in errors[before:]:
            problems.append(f"{tier}: JS error on {path}: {e[:200]}")
        if shoot and code and code < 400:
            name = (urlparse(url).path.strip("/").replace("/", "_") or "home")[:80]
            page.screenshot(path=str(out / f"{tier}-{name}.png"), full_page=False)
        if shoot and code and code < 400:                     # one level below the landing page's links
            queue += [(u, url, False) for u in same_site_links(page, base) if u not in seen]
        if len(seen) % 10 == 0:
            print(f"progress browser_smoke {tier}: {len(seen)} pages, {int(time.time() - started)} s", flush=True)
    ctx.close()
    print(f"{tier}: {len(seen)} pages visited, {len(problems)} problems", flush=True)
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("url", help="e.g. https://racinglines.bet or http://127.0.0.1:8000")
    ap.add_argument("--out", default="reports/browser-smoke", help="screenshot folder (default %(default)s)")
    ap.add_argument("--max", type=int, default=60, help="pages per tier (default %(default)s)")
    ap.add_argument("--chromium", default="", help="a Chromium executable, if Playwright's own isn't installed")
    a = ap.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("needs Playwright: pip install playwright && python -m playwright install chromium")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    problems = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=a.chromium or None)
        for tier, button in TIERS:
            problems += run_tier(browser, a.url.rstrip("/") + "/", tier, button, out, a.max)
        browser.close()
    for line in problems:
        print("PROBLEM " + line)
    print(f"browser smoke: {'FAILED' if problems else 'passed'} ({len(problems)} problems; screenshots in {out})")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
