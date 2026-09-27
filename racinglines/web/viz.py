"""Server-rendered SVG charts (no JavaScript): exchange price lines with our fair values."""

import numpy as np
import pandas as pd

COLORS = ["#2563eb", "#16a34a", "#dc2626", "#9333ea", "#d97706", "#0891b2"]


def price_chart(series, labels, fairs=None, markers=(), w=900, h=220, pad=34):
    """series: {key: [(ts, price), ...]}; labels/fairs: {key: ...}; markers: [(ts, label)].
    Returns a dict for the `chart` template macro, or None if there's nothing to draw."""
    series = {k: v for k, v in series.items() if len(v) >= 2}
    if not series:
        return None
    t0 = min(v[0][0] for v in series.values())
    t1 = max(v[-1][0] for v in series.values())
    span = max((t1 - t0).total_seconds(), 1)
    top = max(max(p for _, p in v) for v in series.values())
    top = max(top, max((f for f in (fairs or {}).values() if f is not None), default=0))
    ymax = min(1.0, max(0.1, round(top * 1.15 + 0.05, 1)))
    plot_h = h - 16

    def x(t):
        return pad + (w - pad - 4) * (t - t0).total_seconds() / span

    def y(p):
        return 4 + (plot_h - 8) * (1 - min(p, ymax) / ymax)

    lines = []
    for i, (k, pts) in enumerate(series.items()):
        f = (fairs or {}).get(k)
        lines.append(dict(label=labels.get(k, k), color=COLORS[i % len(COLORS)],
                          points=" ".join(f"{x(t):.1f},{y(p):.1f}" for t, p in pts),
                          fair_y=round(y(f), 1) if f is not None else None))
    yticks = [dict(y=round(y(v), 1), label=f"{v * 100:.0f}%") for v in [ymax * i / 4 for i in range(5)]]
    days = pd.date_range(pd.Timestamp(t0).ceil("D"), t1, freq="D")
    step = max(1, len(days) // 6)
    xticks = [dict(x=round(x(d), 1), label=d.strftime("%b %d")) for d in days[::step]]
    if len(xticks) < 2:
        hrs = pd.date_range(pd.Timestamp(t0).ceil("6h"), t1, freq="6h")
        xticks = [dict(x=round(x(d), 1), label=d.strftime("%d %H:%M")) for d in hrs]
    mk = [dict(x=round(x(t), 1), label=lab, anchor="end" if x(t) > w - 80 else "start") for t, lab in markers if t0 <= t <= t1]
    return dict(w=w, h=h, pad=pad, lines=lines, yticks=yticks, xticks=xticks, markers=mk)


def line_chart(series, labels=None, w=900, h=200, pad=48, money=True, include_zero=True, markers=()):
    """series: {key: [(ts, value), ...]} -> dict for the `chart` macro, with a $ axis and a zero line.
    include_zero=False fits the axis to the data (e.g. a bankroll); markers: [(ts, label)] dashed verticals."""
    series = {k: v for k, v in series.items() if len(v) >= 2}
    if not series:
        return None
    t0 = min(v[0][0] for v in series.values())
    t1 = max(v[-1][0] for v in series.values())
    span = max((t1 - t0).total_seconds(), 1)
    lo = min(min(y for _, y in v) for v in series.values())
    hi = max(max(y for _, y in v) for v in series.values())
    if include_zero:
        lo, hi = min(0.0, lo), max(0.0, hi)
    rng = (hi - lo) or 1.0
    lo, hi = lo - 0.08 * rng, hi + 0.08 * rng
    plot_h = h - 16

    def x(t):
        return pad + (w - pad - 4) * (t - t0).total_seconds() / span

    def y(v):
        return 4 + (plot_h - 8) * (1 - (v - lo) / (hi - lo))

    lines = [dict(label=(labels or {}).get(k, k), color=COLORS[i % len(COLORS)], fair_y=None,
                  points=" ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in pts)) for i, (k, pts) in enumerate(series.items())]
    ticks = np.linspace(lo, hi, 5)
    yticks = [dict(y=round(y(v), 1), label=(f"${v:,.0f}" if money else f"{v:.2f}")) for v in ticks]
    months = pd.date_range(pd.Timestamp(t0).ceil("D"), t1, freq="MS")
    if len(months) < 2:
        months = pd.date_range(pd.Timestamp(t0).ceil("D"), t1, freq="7D")
    xticks = [dict(x=round(x(d), 1), label=d.strftime("%b %d")) for d in months]
    mk = [dict(x=round(x(t), 1), label=lab, anchor="end" if x(t) > w * 0.8 else "start")
          for t, lab in markers if t0 <= t <= t1]
    return dict(w=w, h=h, pad=pad, lines=lines, yticks=yticks, xticks=xticks, markers=mk,
                zero_y=round(y(0.0), 1) if lo <= 0 <= hi else None)
