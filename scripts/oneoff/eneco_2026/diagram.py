"""Data and model diagram for the Eneco Tour report: existing pieces grey, new ones (2026-10-13) blue, missing red."""
import sys
out = sys.argv[1]
W, H = 1215, 680
cols = {0: 20, 1: 275, 2: 530, 3: 760, 4: 985}
heads = ["DATA", "MODEL INPUTS", "MODELS", "SIMULATION", "MARKETS &amp; PICKS"]
C = {"old": ("#eef0f3", "#8a93a0"), "new": ("#e3eefc", "#2f6fd1"), "miss": ("#fdecec", "#c94141")}
N = {}
nodes = [
 ("itt", 0, 70, "old", ["PCS ITT results", "itt_results_pcs.csv", "2020 to 20 Sep 2026"]),
 ("road", 0, 160, "old", ["PCS one-day road results", "road_results_pcs.csv", "to 6 Oct 2026"]),
 ("stg", 0, 250, "new", ["PCS stage results + GC", "after every stage (fetch_stages)", "stage_results_pcs.csv"]),
 ("route", 0, 350, "new", ["Eneco route, 6 stages", "wielerflits / touretappe", "-> event file [[stages]]"]),
 ("sl", 0, 440, "new", ["Eneco start list (PCS)", "race/eneco-tour/2026, 88", "riders (+ stand-ins to 140)"]),
 ("boards", 0, 530, "new", ["Book boards (owner", "screenshots, transcribed):", "prologue + GC win & h2h"]),
 ("ittin", 1, 70, "old", ["Rider TT ability (log time)", "incidents, climbing term"]),
 ("short", 1, 150, "new", ["Short-TT noise 2.0", "(TT <= 15 km, backtested)"]),
 ("roadin", 1, 230, "old", ["Rider road ability", "(pseudo-time from places)"]),
 ("curves", 1, 310, "new", ["Road-stage gap curves", "by class: flat / rolling /", "hilly / mountain"]),
 ("rules", 1, 410, "new", ["[model.gc]: bonus 10-6-4,", "abandon 1%, field 140,", "TT speed 50 km/h"]),
 ("ittm", 2, 100, "old", ["ITT book model", "cycling.py fit/simulate"]),
 ("roadm", 2, 250, "old", ["Road book model", "cycling.py fit/simulate"]),
 ("gcsim", 3, 210, "new", ["GC simulator", "cycling_gc.py: sum of", "stage gaps - bonuses", "one sim, all markets"]),
 ("pro", 4, 70, "old", ["Prologue winner", "+ h2h probabilities"]),
 ("gc", 4, 170, "new", ["GC winner + overall", "matchup probabilities"]),
 ("kelly", 4, 290, "new", ["Joint quarter Kelly", "$1,000, no cap, EV >= 5%", "correlated across markets"]),
 ("slip", 4, 410, "new", ["Recommended slip", "(paper, settle later)"]),
 ("bt", 3, 420, "new", ["Walk-forward backtests:", "short TTs, past", "stage-race GCs"]),
]
bw, lh = 215, 15
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
       'font-family="Inter, DejaVu Sans, sans-serif">',
       '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
       '<path d="M0,0 L10,5 L0,10 z" fill="#555"/></marker></defs>', f'<rect width="{W}" height="{H}" fill="#fff"/>']
for i, h in enumerate(heads):
    svg.append(f'<text x="{cols[i]}" y="40" font-size="13" font-weight="700" fill="#333">{h}</text>')
for key, c, y, kind, lines in nodes:
    x = cols[c]; h = 16 + lh * len(lines)
    fill, stroke = C[kind]
    dash = ' stroke-dasharray="5,3"' if kind == "miss" else ""
    svg.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{h}" rx="7" fill="{fill}" stroke="{stroke}" stroke-width="1.6"{dash}/>')
    for i, t in enumerate(lines):
        svg.append(f'<text x="{x + 10}" y="{y + 20 + lh * i}" font-size="12" fill="#222"'
                   f'{" font-weight=\"600\"" if i == 0 else ""}>{t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")}</text>')
    N[key] = (x, y, h)
edges = [("itt", "ittin"), ("road", "roadin"), ("stg", "roadin"), ("stg", "ittin"), ("stg", "curves"), ("route", "rules"),
         ("route", "gcsim"), ("sl", "gcsim"), ("ittin", "ittm"), ("short", "ittm"), ("roadin", "roadm"), ("curves", "gcsim"),
         ("rules", "gcsim"), ("ittm", "gcsim"), ("roadm", "gcsim"), ("gcsim", "pro"), ("gcsim", "gc"), ("boards", "kelly"),
         ("pro", "kelly"), ("gc", "kelly"), ("kelly", "slip"), ("stg", "bt"), ("itt", "bt"), ("bt", "short"), ("gcsim", "bt")]
for a, b in edges:
    xa, ya, ha = N[a]; xb, yb, hb = N[b]
    if xb > xa:
        x1, y1, x2, y2 = xa + bw, ya + ha / 2, xb - 2, yb + hb / 2
    elif xb < xa:
        x1, y1, x2, y2 = xa, ya + ha / 2, xb + bw + 2, yb + hb / 2
    else:
        x1, y1, x2, y2 = xa + bw / 2, ya + ha, xb + bw / 2, yb - 2
    mx = (x1 + x2) / 2
    svg.append(f'<path d="M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}" fill="none" stroke="#777" stroke-width="1.1" marker-end="url(#a)"/>')
ly = 630
for i, (k, lab) in enumerate([("old", "existing (before today)"), ("new", "new today (2026-10-13)")]):
    fill, stroke = C[k]
    svg.append(f'<rect x="{20 + i * 250}" y="{ly}" width="26" height="16" rx="4" fill="{fill}" stroke="{stroke}"/>'
               f'<text x="{54 + i * 250}" y="{ly + 13}" font-size="12" fill="#333">{lab}</text>')
svg.append('</svg>')
open(out, "w").write("\n".join(svg))
