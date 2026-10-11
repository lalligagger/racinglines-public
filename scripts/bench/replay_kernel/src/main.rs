// Benchmark only, not used by the app: racinglines/markets/strategies/maker_replay.py `replay` (fill rules "touch" and
// "through"; no "queue") as a Rust kernel, to time the same replays natively and as WebAssembly. Reads the inputs
// written by scripts/bench/replay_dump.py, runs every call `reps` times, prints the time per pass and writes every
// quote and fill so replay_dump.py --check can compare them with the Python replay exactly.
//   cargo run --release -- <input.json> <output.json> [reps]
//   cargo build --release --target wasm32-wasip1 && node run_wasi.mjs <dir> <input.json> <output.json> [reps]
use serde::Deserialize;
use std::collections::HashMap;
use std::time::Instant;

#[derive(Deserialize)]
struct Stage { run_id: i64, start: i64, end: i64, session_end: bool }
#[derive(Deserialize)]
struct Mkt { kind: String, fairs: HashMap<String, Option<f64>>, mid_ts: Vec<i64>, mid_px: Vec<f64>,
             tr_ts: Vec<i64>, tr_px: Vec<f64>, tr_sz: Vec<f64>, tr_buy: Vec<bool> }
#[derive(Deserialize)]
struct Event { stages: Vec<Stage>, qual_start: Option<i64>, markets: Vec<Mkt> }
#[derive(Deserialize, Clone)]
struct P { half_spread: f64, tick: f64, size: f64, max_pos: f64, max_capital: f64, skew: f64, step_min: f64,
           pull_min: f64, min_volume_24h: f64, band_lo: f64, band_hi: f64, max_disagree: Option<f64>, touch: bool,
           flatten_before_qual: bool, taker_cost: f64, info_skew: f64, info_tau_h: f64,
           by_kind: HashMap<String, f64>, maker_fee: f64 }
#[derive(Deserialize)]
struct Call { event: usize, p: P }
#[derive(Deserialize)]
struct Input { events: Vec<Event>, calls: Vec<Call> }

// Python's round(x, nd) for the values seen here (half-even on the scaled value).
fn pyround(x: f64, nd: i32) -> f64 { let s = 10f64.powi(nd); let y = x * s; let r = y.round();
    let r = if (y - y.trunc()).abs() == 0.5 { 2.0 * (y / 2.0).round() } else { r }; r / s }
fn bisect_right(v: &[i64], x: i64) -> usize { v.partition_point(|&a| a <= x) }

// Python: -sum(min(0.0, min(cash, cash + inv)) for each market), summed in market order
fn used(cash: &[f64], inv: &[f64]) -> f64 { let mut s = 0.0; for i in 0..cash.len() { s += f64::min(0.0, f64::min(cash[i], cash[i] + inv[i])); } -s }
fn used_mod(cash: &[f64], inv: &[f64], c: usize, nc: f64, ni: f64) -> f64 { let mut s = 0.0;
    for i in 0..cash.len() { let (x, y) = if i == c { (nc, ni) } else { (cash[i], inv[i]) }; s += f64::min(0.0, f64::min(x, x + y)); } -s }
fn cap(q: f64, sgn: f64, price: f64, cash: &[f64], inv: &[f64], c: usize, p: &P) -> f64 {
    let base = used(cash, inv);
    let ua = |x: f64| used_mod(cash, inv, c, cash[c] - sgn * x * price, inv[c] + sgn * x);
    if q <= 0.0 || ua(q) <= p.max_capital + 1e-9 || ua(q) <= base { return f64::max(q, 0.0); }
    let (mut lo, mut hi) = (0.0, q);
    for _ in 0..30 { let m = (lo + hi) / 2.0; if ua(m) <= p.max_capital { lo = m } else { hi = m } }
    lo
}
fn fee(rate: f64, price: f64, q: f64) -> f64 { (pyround(rate * q * price * (1.0 - price) * 100.0, 6)).ceil() / 100.0 }

// reason codes: 0 quoted, 1 no fair, 2 no market price, 3 band, 4 thin, 5 disagree, 6 limit
fn quote(fair: Option<f64>, mid: Option<f64>, vol: f64, inv: f64, p: &P, hs: f64, skew: f64, used: f64) -> (Option<f64>, Option<f64>, u8) {
    let fair = match fair { Some(f) if !f.is_nan() => f, _ => return (None, None, 1) };
    let mid = match mid { Some(m) => m, None => return (None, None, 2) };
    if !(p.band_lo <= mid && mid <= p.band_hi) { return (None, None, 3); }
    if vol < p.min_volume_24h { return (None, None, 4); }
    if let Some(d) = p.max_disagree { if (fair - mid).abs() > d { return (None, None, 5); } }
    let shift = -skew * hs * inv / p.max_pos;
    let mut bid = pyround((fair - hs + shift) / p.tick, 6).floor() * p.tick;
    let mut ask = pyround((fair + hs + shift) / p.tick, 6).ceil() * p.tick;
    bid = f64::min(bid, pyround(mid / p.tick, 6).ceil() * p.tick - p.tick);
    ask = f64::max(ask, pyround(mid / p.tick, 6).floor() * p.tick + p.tick);
    let mut b = if bid < p.tick { None } else { Some(pyround(bid, 4)) };
    let mut a = if ask > 1.0 - p.tick { None } else { Some(pyround(ask, 4)) };
    let at_cap = used >= p.max_capital;
    if b.is_some() && (inv >= p.max_pos || (at_cap && inv >= 0.0)) { b = None; }
    if a.is_some() && (inv <= -p.max_pos || (at_cap && inv <= 0.0)) { a = None; }
    (b, a, if b.is_some() || a.is_some() { 0 } else { 6 })
}

struct Out { quotes: Vec<(i64, usize, i64, Option<f64>, Option<f64>, u8)>, fills: Vec<(i64, usize, i64, bool, f64, f64)> }

fn replay(ev: &Event, cum: &[Vec<f64>], p: &P) -> Out {
    let step = (p.step_min * 60e9) as i64; let pull = (p.pull_min * 60e9) as i64; let day = (24.0 * 3600e9) as i64;
    let n = ev.markets.len(); let mut cash = vec![0.0; n]; let mut inv = vec![0.0; n];
    let mut o = Out { quotes: Vec::new(), fills: Vec::new() };
    let hs_of: Vec<f64> = ev.markets.iter().map(|m| *p.by_kind.get(&m.kind).unwrap_or(&p.half_spread)).collect();
    for st in &ev.stages {
        let key = st.run_id.to_string();
        let fairs: Vec<Option<f64>> = ev.markets.iter().map(|m| m.fairs.get(&key).copied().flatten()).collect();
        let (mut t, end) = (st.start, st.end - if st.session_end { pull } else { 0 });
        while t < end {
            let t_next = i64::min(t + step, end);
            let u = used(&cash, &inv);
            let mut skew = p.skew;
            if p.info_skew != 0.0 && st.session_end { skew = p.skew * (1.0 + p.info_skew * (-((st.end - t) as f64) / (p.info_tau_h * 3600e9)).exp()); }
            for (c, m) in ev.markets.iter().enumerate() {
                let i = bisect_right(&m.mid_ts, t); let mid = if i > 0 { Some(m.mid_px[i - 1]) } else { None };
                let a = bisect_right(&m.tr_ts, t); let vol = cum[c][a] - cum[c][bisect_right(&m.tr_ts, t - day)];
                let (bid, ask, why) = quote(fairs[c], mid, vol, inv[c], p, hs_of[c], skew, u);
                o.quotes.push((t, c, st.run_id, bid, ask, why));
                if bid.is_none() && ask.is_none() { continue; }
                let b = bisect_right(&m.tr_ts, t_next);
                let (mut lb, mut la) = (p.size, p.size);
                for k in a..b {
                    let (px, sz, buy) = (m.tr_px[k], m.tr_sz[k], m.tr_buy[k]);
                    if let (false, Some(bd)) = (buy, bid) { if lb > 0.0 && (if p.touch { px <= bd } else { px < bd }) {
                        let q = cap(f64::min(f64::min(sz, lb), p.max_pos - inv[c]), 1.0, bd, &cash, &inv, c, p);
                        if q > 0.0 { lb -= q; inv[c] += q; cash[c] -= q * bd; if p.maker_fee != 0.0 { cash[c] -= fee(p.maker_fee, bd, q); }
                            o.fills.push((m.tr_ts[k], c, st.run_id, true, bd, q)); }
                        continue; } }
                    if let (true, Some(ak)) = (buy, ask) { if la > 0.0 && (if p.touch { px >= ak } else { px > ak }) {
                        let q = cap(f64::min(f64::min(sz, la), p.max_pos + inv[c]), -1.0, ak, &cash, &inv, c, p);
                        if q > 0.0 { la -= q; inv[c] -= q; cash[c] += q * ak; if p.maker_fee != 0.0 { cash[c] -= fee(p.maker_fee, ak, q); }
                            o.fills.push((m.tr_ts[k], c, st.run_id, false, ak, q)); } } }
                }
            }
            t = t_next;
        }
        if p.flatten_before_qual && Some(st.end) == ev.qual_start {
            for (c, m) in ev.markets.iter().enumerate() {
                let i = bisect_right(&m.mid_ts, end); let q = inv[c];
                if q.abs() < 1e-9 || i == 0 { continue; }
                let mid = m.mid_px[i - 1];
                let px = if q < 0.0 { f64::min(mid + p.taker_cost, 1.0) } else { f64::max(mid - p.taker_cost, 0.0) };
                cash[c] += q * px; inv[c] = 0.0; o.fills.push((end, c, st.run_id, q < 0.0, px, q.abs()));
            }
        }
    }
    o
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let inp: Input = serde_json::from_str(&std::fs::read_to_string(&a[1]).unwrap()).unwrap();
    let reps: usize = a.get(3).map(|s| s.parse().unwrap()).unwrap_or(5);
    let cums: Vec<Vec<Vec<f64>>> = inp.events.iter().map(|e| e.markets.iter().map(|m| {
        let mut c = vec![0.0]; let mut s = 0.0; for k in 0..m.tr_ts.len() { s += m.tr_px[k] * m.tr_sz[k]; c.push(s); } c }).collect()).collect();
    let mut outs = Vec::new();
    let t0 = Instant::now();
    for r in 0..reps { for call in &inp.calls { let o = replay(&inp.events[call.event], &cums[call.event], &call.p); if r == 0 { outs.push(o); } } }
    let dt = t0.elapsed().as_secs_f64() / reps as f64;
    let nq: usize = outs.iter().map(|o| o.quotes.len()).sum(); let nf: usize = outs.iter().map(|o| o.fills.len()).sum();
    println!("kernel: {} calls, {} quote decisions, {} fills, {:.4} s per pass (mean of {})", inp.calls.len(), nq, nf, dt, reps);
    let js: Vec<serde_json::Value> = outs.iter().map(|o| serde_json::json!({"quotes": o.quotes, "fills": o.fills})).collect();
    std::fs::write(&a[2], serde_json::to_string(&js).unwrap()).unwrap();
}
