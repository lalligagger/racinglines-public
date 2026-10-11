//! The maker replay (racinglines/markets/strategies/maker_replay.py `replay`, fill rules "touch" and "through")
//! and its scoring (`_score_fills`, `summary`, `by_stage`, `skip_reasons`) in Rust, compiled to WebAssembly so the
//! browser can re-run an event's replay as the user moves the knobs, with no work on the server.
//!
//! The Python replay is the reference: tests/test_wasm_replay.py runs both on the same tapes and checks every quote
//! and fill is equal, and the summaries agree to rounding. Rules live in one place each: change the Python first,
//! port the change here, and the parity test says whether the two still agree.
//!
//! Browser interface (no wasm-bindgen; JSON in and out through linear memory, see racinglines/web/static/replay.js):
//!   alloc(len) -> ptr, dealloc(ptr, len)
//!   load(ptr, len) -> 0 | 1          the event (markets with tapes, stages), kept until the next load
//!   run(ptr, len) -> ptr             params JSON in; result JSON out, its length at result_len()

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Deserialize, Clone)]
pub struct Stage { pub run_id: i64, pub start: i64, pub end: i64, #[serde(default = "yes")] pub session_end: bool }
fn yes() -> bool { true }

/// A market's outcome as Python's Market.outcome: a payout (true = 1, false = 0, or a float), "void" (refund at
/// cost) or "fair" / null (undecided).
#[derive(Deserialize, Clone, Copy, PartialEq)]
#[serde(untagged)]
pub enum Outcome { Payout(f64), Bool(bool), Tag(Tag) }
#[derive(Deserialize, Clone, Copy, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum Tag { Void, Fair }

#[derive(Deserialize, Clone)]
pub struct Market {
    pub kind: String,
    #[serde(default)] pub subject: String,
    pub fairs: HashMap<String, Option<f64>>,
    #[serde(default)] pub outcome: Option<Outcome>,
    pub mid_ts: Vec<i64>, pub mid_px: Vec<f64>,
    pub tr_ts: Vec<i64>, pub tr_px: Vec<f64>, pub tr_sz: Vec<f64>, pub tr_buy: Vec<bool>,
}

#[derive(Deserialize, Clone)]
pub struct Event { pub stages: Vec<Stage>, #[serde(default)] pub qual_start: Option<i64>, pub markets: Vec<Market> }

/// maker_replay.Params (fill "touch" or "through"; the defaults are Python's).
#[derive(Deserialize, Clone)]
#[serde(default)]
pub struct Params {
    pub half_spread: f64, pub tick: f64, pub size: f64, pub max_pos: f64, pub max_capital: f64, pub skew: f64,
    pub step_min: f64, pub pull_min: f64, pub min_volume_24h: f64, pub price_band: (f64, f64),
    pub max_disagree: Option<f64>, pub fill: String, pub flatten_before_qual: bool, pub taker_cost: f64,
    pub info_skew: f64, pub info_tau_h: f64, pub half_spread_by_kind: HashMap<String, f64>, pub maker_fee: f64,
}
impl Default for Params {
    fn default() -> Self {
        Params { half_spread: 0.02, tick: 0.01, size: 50.0, max_pos: 250.0, max_capital: 1000.0, skew: 1.0, step_min: 5.0,
                 pull_min: 15.0, min_volume_24h: 100.0, price_band: (0.03, 0.97), max_disagree: Some(0.15),
                 fill: "through".into(), flatten_before_qual: false, taker_cost: 0.01, info_skew: 0.0, info_tau_h: 2.0,
                 half_spread_by_kind: HashMap::new(), maker_fee: 0.0 }
    }
}

/// Why a market was not quoted at a step (quote()'s reasons; None = quoted).
pub const REASONS: [&str; 7] = ["quoted", "no fair", "no market price", "outside price band", "thin", "disagree", "limit"];

pub struct Quote { pub t: i64, pub market: usize, pub run_id: i64, pub bid: Option<f64>, pub ask: Option<f64>, pub why: u8 }
pub struct Fill { pub t: i64, pub market: usize, pub run_id: i64, pub buy: bool, pub price: f64, pub qty: f64, pub fair: Option<f64> }
pub struct Replay { pub quotes: Vec<Quote>, pub fills: Vec<Fill>, pub cash: Vec<f64>, pub inv: Vec<f64> }

/// Python's round(x, nd) (half to even on the scaled value).
fn pyround(x: f64, nd: i32) -> f64 {
    let s = 10f64.powi(nd);
    let y = x * s;
    let r = if (y - y.trunc()).abs() == 0.5 { 2.0 * (y / 2.0).round() } else { y.round() };
    r / s
}
fn bisect_right(v: &[i64], x: i64) -> usize { v.partition_point(|&a| a <= x) }
fn worst_case(cash: f64, inv: f64) -> f64 { f64::min(cash, cash + inv) }

/// _used: the event's worst-case loss, summed over markets in order.
fn used(cash: &[f64], inv: &[f64]) -> f64 {
    let mut s = 0.0;
    for i in 0..cash.len() { s += f64::min(0.0, worst_case(cash[i], inv[i])); }
    -s
}
fn used_with(cash: &[f64], inv: &[f64], c: usize, nc: f64, ni: f64) -> f64 {
    let mut s = 0.0;
    for i in 0..cash.len() {
        let (x, y) = if i == c { (nc, ni) } else { (cash[i], inv[i]) };
        s += f64::min(0.0, worst_case(x, y));
    }
    -s
}

/// _cap: the largest fill <= q that keeps the event's worst-case loss within max_capital.
fn cap(q: f64, sgn: f64, price: f64, cash: &[f64], inv: &[f64], c: usize, p: &Params) -> f64 {
    let after = |x: f64| used_with(cash, inv, c, cash[c] - sgn * x * price, inv[c] + sgn * x);
    if q <= 0.0 || after(q) <= p.max_capital + 1e-9 || after(q) <= used(cash, inv) { return f64::max(q, 0.0); }
    let (mut lo, mut hi) = (0.0, q);
    for _ in 0..30 {
        let m = (lo + hi) / 2.0;
        if after(m) <= p.max_capital { lo = m } else { hi = m }
    }
    lo
}

fn venue_fee(rate: f64, price: f64, q: f64) -> f64 { pyround(rate * q * price * (1.0 - price) * 100.0, 6).ceil() / 100.0 }

/// quote(): (bid, ask, reason code).
fn quote(fair: Option<f64>, mid: Option<f64>, vol: impl Fn() -> f64, inv: f64, p: &Params, hs: f64, skew: f64, used: f64) -> (Option<f64>, Option<f64>, u8) {
    let fair = match fair { Some(f) if !f.is_nan() => f, _ => return (None, None, 1) };
    let mid = match mid { Some(m) => m, None => return (None, None, 2) };
    if !(p.price_band.0 <= mid && mid <= p.price_band.1) { return (None, None, 3); }
    if vol() < p.min_volume_24h { return (None, None, 4); }
    if let Some(d) = p.max_disagree { if (fair - mid).abs() > d { return (None, None, 5); } }
    let shift = -skew * hs * inv / p.max_pos;
    let mut bid = pyround((fair - hs + shift) / p.tick, 6).floor() * p.tick;
    let mut ask = pyround((fair + hs + shift) / p.tick, 6).ceil() * p.tick;
    bid = f64::min(bid, pyround(mid / p.tick, 6).ceil() * p.tick - p.tick);       // post-only: never cross
    ask = f64::max(ask, pyround(mid / p.tick, 6).floor() * p.tick + p.tick);
    let mut b = if bid < p.tick { None } else { Some(pyround(bid, 4)) };
    let mut a = if ask > 1.0 - p.tick { None } else { Some(pyround(ask, 4)) };
    let at_cap = used >= p.max_capital;
    if b.is_some() && (inv >= p.max_pos || (at_cap && inv >= 0.0)) { b = None; }
    if a.is_some() && (inv <= -p.max_pos || (at_cap && inv <= 0.0)) { a = None; }
    (b, a, if b.is_some() || a.is_some() { 0 } else { 6 })
}

/// numpy's pairwise sum (np.add.reduce on a contiguous float64 array), so a sum Python takes with .sum() is
/// bit-identical here.
fn np_sum(v: &[f64]) -> f64 {
    let n = v.len();
    if n < 8 {
        let mut s = -0.0;
        for x in v { s += x; }
        s
    } else if n <= 128 {
        let mut r = [v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]];
        let mut i = 8;
        while i < n - n % 8 {
            for j in 0..8 { r[j] += v[i + j]; }
            i += 8;
        }
        let mut s = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        while i < n { s += v[i]; i += 1; }
        s
    } else {
        let n2 = (n / 2) - (n / 2) % 8;
        np_sum(&v[..n2]) + np_sum(&v[n2..])
    }
}

/// _Tape.volume: the 24 h traded notional as a prefix-sum difference, or the exact sum when that is within rounding
/// of the threshold, so the thin-market test decides exactly as Python's.
fn volume(m: &Market, cum: &[f64], t: i64, threshold: f64) -> f64 {
    let j = bisect_right(&m.tr_ts, t);
    let k = bisect_right(&m.tr_ts, t - 24 * 3_600_000_000_000);
    let v = cum[j] - cum[k];
    if (v - threshold).abs() <= 1e-6 * f64::max(1.0, threshold.abs()) {
        let prod: Vec<f64> = (k..j).map(|i| m.tr_px[i] * m.tr_sz[i]).collect();
        return np_sum(&prod);
    }
    v
}

fn mid_at(m: &Market, t: i64) -> Option<f64> {
    let i = bisect_right(&m.mid_ts, t);
    if i > 0 { Some(m.mid_px[i - 1]) } else { None }
}

/// Prefix sums of trade notional per market (the 24 h volume is a difference of two).
pub fn notional_prefix(ev: &Event) -> Vec<Vec<f64>> {
    ev.markets.iter().map(|m| {
        let mut c = Vec::with_capacity(m.tr_ts.len() + 1);
        let mut s = 0.0;
        c.push(0.0);
        for k in 0..m.tr_ts.len() { s += m.tr_px[k] * m.tr_sz[k]; c.push(s); }
        c
    }).collect()
}

/// maker_replay.replay for fill "touch" / "through".
pub fn replay(ev: &Event, cum: &[Vec<f64>], p: &Params) -> Result<Replay, String> {
    let touch = match p.fill.as_str() { "touch" => true, "through" => false, f => return Err(format!("fill {f:?}: touch or through")) };
    let step = (p.step_min * 60e9) as i64;
    let pull = (p.pull_min * 60e9) as i64;
    let n = ev.markets.len();
    let (mut cash, mut inv) = (vec![0.0; n], vec![0.0; n]);
    let (mut quotes, mut fills) = (Vec::new(), Vec::new());
    let hs_of: Vec<f64> = ev.markets.iter().map(|m| *p.half_spread_by_kind.get(&m.kind).unwrap_or(&p.half_spread)).collect();
    for st in &ev.stages {
        let key = st.run_id.to_string();
        let fairs: Vec<Option<f64>> = ev.markets.iter().map(|m| m.fairs.get(&key).copied().flatten()).collect();
        let (mut t, end) = (st.start, st.end - if st.session_end { pull } else { 0 });
        while t < end {
            let t_next = i64::min(t + step, end);
            let u = used(&cash, &inv);
            let mut skew = p.skew;
            if p.info_skew != 0.0 && st.session_end {
                skew = p.skew * (1.0 + p.info_skew * (-((st.end - t) as f64) / (p.info_tau_h * 3600e9)).exp());
            }
            for (c, m) in ev.markets.iter().enumerate() {
                let a = bisect_right(&m.tr_ts, t);
                let vol = || volume(m, &cum[c], t, p.min_volume_24h);
                let (bid, ask, why) = quote(fairs[c], mid_at(m, t), vol, inv[c], p, hs_of[c], skew, u);
                quotes.push(Quote { t, market: c, run_id: st.run_id, bid, ask, why });
                if bid.is_none() && ask.is_none() { continue; }
                let b = bisect_right(&m.tr_ts, t_next);
                let (mut left_bid, mut left_ask) = (p.size, p.size);
                for k in a..b {
                    let (px, sz, buy) = (m.tr_px[k], m.tr_sz[k], m.tr_buy[k]);
                    if !buy {
                        if let Some(bd) = bid {
                            if left_bid > 0.0 && (if touch { px <= bd } else { px < bd }) {
                                let q = cap(f64::min(f64::min(sz, left_bid), p.max_pos - inv[c]), 1.0, bd, &cash, &inv, c, p);
                                if q > 0.0 {
                                    left_bid -= q; inv[c] += q; cash[c] -= q * bd;
                                    if p.maker_fee != 0.0 { cash[c] -= venue_fee(p.maker_fee, bd, q); }
                                    fills.push(Fill { t: m.tr_ts[k], market: c, run_id: st.run_id, buy: true, price: bd, qty: q, fair: fairs[c] });
                                }
                            }
                        }
                    } else if let Some(ak) = ask {
                        if left_ask > 0.0 && (if touch { px >= ak } else { px > ak }) {
                            let q = cap(f64::min(f64::min(sz, left_ask), p.max_pos + inv[c]), -1.0, ak, &cash, &inv, c, p);
                            if q > 0.0 {
                                left_ask -= q; inv[c] -= q; cash[c] += q * ak;
                                if p.maker_fee != 0.0 { cash[c] -= venue_fee(p.maker_fee, ak, q); }
                                fills.push(Fill { t: m.tr_ts[k], market: c, run_id: st.run_id, buy: false, price: ak, qty: q, fair: fairs[c] });
                            }
                        }
                    }
                }
            }
            t = t_next;
        }
        if p.flatten_before_qual && Some(st.end) == ev.qual_start {
            for (c, m) in ev.markets.iter().enumerate() {        // take the market to go flat before qualifying
                let q = inv[c];
                let mid = match mid_at(m, end) { Some(x) if q.abs() >= 1e-9 => x, _ => continue };
                let px = if q < 0.0 { f64::min(mid + p.taker_cost, 1.0) } else { f64::max(mid - p.taker_cost, 0.0) };
                cash[c] += q * px;
                inv[c] = 0.0;
                fills.push(Fill { t: end, market: c, run_id: st.run_id, buy: q < 0.0, price: px, qty: q.abs(), fair: fairs[c] });
            }
        }
    }
    Ok(Replay { quotes, fills, cash, inv })
}

/// One fill scored as _score_fills does (NaN where Python has NaN).
pub struct Scored { pub spread_pnl: f64, pub markout_5m: f64, pub markout_60m: f64, pub model_edge: f64, pub pnl: f64 }

pub fn score(ev: &Event, f: &Fill) -> Scored {
    let m = &ev.markets[f.market];
    let sgn = if f.buy { 1.0 } else { -1.0 };
    let at = |t: i64| mid_at(m, t).unwrap_or(f64::NAN);
    let (mid, m5, m60) = (at(f.t), at(f.t + 300_000_000_000), at(f.t + 3_600_000_000_000));
    let out = match m.outcome {
        None | Some(Outcome::Tag(Tag::Fair)) => f64::NAN,
        Some(Outcome::Tag(Tag::Void)) => f.price,
        Some(Outcome::Bool(b)) => if b { 1.0 } else { 0.0 },
        Some(Outcome::Payout(y)) => y,
    };
    Scored { spread_pnl: sgn * (mid - f.price) * f.qty, markout_5m: sgn * (m5 - mid) * f.qty,
             markout_60m: sgn * (m60 - mid) * f.qty, model_edge: sgn * (f.fair.unwrap_or(f64::NAN) - f.price) * f.qty,
             pnl: sgn * (out - f.price) * f.qty }
}

/// settlement_rules.settle_position(inv, 0, cash, outcome); None while undecided.
fn position_pnl(m: &Market, cash: f64, inv: f64) -> Option<f64> {
    match m.outcome {
        None | Some(Outcome::Tag(Tag::Fair)) => None,
        Some(Outcome::Tag(Tag::Void)) => Some(0.0),
        Some(Outcome::Bool(b)) => Some(cash + inv * if b { 1.0 } else { 0.0 }),
        Some(Outcome::Payout(y)) => Some(cash + inv * y),
    }
}

fn nansum(it: impl Iterator<Item = f64>) -> f64 { it.filter(|x| !x.is_nan()).sum() }

#[derive(Serialize)]
pub struct KindRow { pub kind: String, pub markets: usize, pub quoted_share: f64, pub fills: usize, pub shares: f64,
                     pub notional: f64, pub spread_pnl: f64, pub markout_60m: f64, pub model_edge: f64, pub pnl: f64,
                     pub worst_case: f64 }
#[derive(Serialize)]
pub struct StageRow { pub run_id: i64, pub start: i64, pub end: i64, pub fills: usize, pub notional: f64,
                      pub spread_pnl: f64, pub markout_60m: f64, pub model_edge: f64, pub pnl: f64 }
#[derive(Serialize)]
pub struct Summary { pub summary: Vec<KindRow>, pub stages: Vec<StageRow>, pub skips: Vec<(String, usize)>,
                     pub fills: usize, pub quotes: usize }

/// maker_replay.summary (per kind, sorted, then "total"), by_stage and skip_reasons.
pub fn summarize(ev: &Event, r: &Replay) -> Summary {
    let scored: Vec<Scored> = r.fills.iter().map(|f| score(ev, f)).collect();
    let mut kinds: Vec<&str> = ev.markets.iter().map(|m| m.kind.as_str()).collect();
    kinds.sort();
    kinds.dedup();
    let mut rows = Vec::new();
    for k in kinds.iter().map(|k| Some(*k)).chain(std::iter::once(None)) {
        let in_k = |c: usize| k.map_or(true, |k| ev.markets[c].kind == k);
        let fi: Vec<usize> = (0..r.fills.len()).filter(|&i| in_k(r.fills[i].market)).collect();
        let qs: Vec<&Quote> = r.quotes.iter().filter(|q| in_k(q.market)).collect();
        let ms: Vec<usize> = (0..ev.markets.len()).filter(|&c| in_k(c)).collect();
        rows.push(KindRow {
            kind: k.unwrap_or("total").to_string(),
            markets: ms.len(),
            quoted_share: if qs.is_empty() { 0.0 } else { qs.iter().filter(|q| q.why == 0).count() as f64 / qs.len() as f64 },
            fills: fi.len(),
            shares: fi.iter().map(|&i| r.fills[i].qty).sum(),
            notional: fi.iter().map(|&i| r.fills[i].qty * r.fills[i].price).sum(),
            spread_pnl: nansum(fi.iter().map(|&i| scored[i].spread_pnl)),
            markout_60m: nansum(fi.iter().map(|&i| scored[i].markout_60m)),
            model_edge: nansum(fi.iter().map(|&i| scored[i].model_edge)),
            pnl: ms.iter().map(|&c| position_pnl(&ev.markets[c], r.cash[c], r.inv[c]).unwrap_or(0.0)).sum(),
            worst_case: ms.iter().map(|&c| worst_case(r.cash[c], r.inv[c])).sum(),
        });
    }
    let stages = ev.stages.iter().map(|st| {
        let fi: Vec<usize> = (0..r.fills.len()).filter(|&i| r.fills[i].run_id == st.run_id).collect();
        StageRow { run_id: st.run_id, start: st.start, end: st.end, fills: fi.len(),
                   notional: fi.iter().map(|&i| r.fills[i].qty * r.fills[i].price).sum(),
                   spread_pnl: nansum(fi.iter().map(|&i| scored[i].spread_pnl)),
                   markout_60m: nansum(fi.iter().map(|&i| scored[i].markout_60m)),
                   model_edge: nansum(fi.iter().map(|&i| scored[i].model_edge)),
                   pnl: nansum(fi.iter().map(|&i| scored[i].pnl)) }
    }).collect();
    let mut counts = [0usize; 7];
    for q in &r.quotes { counts[q.why as usize] += 1; }
    let mut skips: Vec<(String, usize)> = (0..7).filter(|&i| counts[i] > 0).map(|i| (REASONS[i].to_string(), counts[i])).collect();
    skips.sort_by(|a, b| b.1.cmp(&a.1));
    Summary { summary: rows, stages, skips, fills: r.fills.len(), quotes: r.quotes.len() }
}

/// Replay and summarize one parameter set (the browser's call).
pub fn run_json(ev: &Event, cum: &[Vec<f64>], params: &str) -> String {
    let out = serde_json::from_str::<Params>(params).map_err(|e| e.to_string())
        .and_then(|p| replay(ev, cum, &p)).map(|r| summarize(ev, &r));
    match out {
        Ok(s) => serde_json::to_string(&s).unwrap_or_else(|e| format!("{{\"error\":{:?}}}", e.to_string())),
        Err(e) => format!("{{\"error\":{:?}}}", e),
    }
}

#[cfg(target_arch = "wasm32")]
mod browser {
    use super::*;
    use std::cell::RefCell;

    thread_local! {
        static EVENT: RefCell<Option<(Event, Vec<Vec<f64>>)>> = RefCell::new(None);
        static OUT: RefCell<Vec<u8>> = RefCell::new(Vec::new());
    }

    #[no_mangle]
    pub extern "C" fn alloc(len: usize) -> *mut u8 {
        let mut v = Vec::<u8>::with_capacity(len);
        let p = v.as_mut_ptr();
        std::mem::forget(v);
        p
    }

    #[no_mangle]
    pub unsafe extern "C" fn dealloc(ptr: *mut u8, len: usize) { drop(Vec::from_raw_parts(ptr, 0, len)); }

    unsafe fn text(ptr: *const u8, len: usize) -> String {
        String::from_utf8_lossy(std::slice::from_raw_parts(ptr, len)).into_owned()
    }

    /// The event's JSON: 0 when loaded, 1 when it doesn't parse.
    #[no_mangle]
    pub unsafe extern "C" fn load(ptr: *const u8, len: usize) -> u32 {
        match serde_json::from_str::<Event>(&text(ptr, len)) {
            Ok(ev) => { let cum = notional_prefix(&ev); EVENT.with(|e| *e.borrow_mut() = Some((ev, cum))); 0 }
            Err(_) => 1,
        }
    }

    /// Params JSON in; the summary JSON's pointer out (its length: result_len()).
    #[no_mangle]
    pub unsafe extern "C" fn run(ptr: *const u8, len: usize) -> *const u8 {
        let params = text(ptr, len);
        let s = EVENT.with(|e| match &*e.borrow() {
            Some((ev, cum)) => run_json(ev, cum, &params),
            None => "{\"error\":\"no event loaded\"}".to_string(),
        });
        OUT.with(|o| { *o.borrow_mut() = s.into_bytes(); o.borrow().as_ptr() })
    }

    #[no_mangle]
    pub extern "C" fn result_len() -> usize { OUT.with(|o| o.borrow().len()) }
}
