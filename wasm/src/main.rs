// Command-line runner for the replay library (src/lib.rs), for benchmarks and the parity test, natively or as
// wasm32-wasip1 under Node (run_wasi.mjs). Reads {"event": Event, "calls": [Params, ...]} as written by
// scripts/bench/replay_dump.py or tests/test_wasm_replay.py, runs every call `reps` times, prints the time per pass
// and writes per call its quotes [t, market, run_id, bid, ask, reason], fills [t, market, run_id, buy, price, qty]
// and summary, for an exact comparison with the Python replay.
//   cargo run --release -- <input.json> <output.json> [reps]
//   cargo build --release --target wasm32-wasip1 && node run_wasi.mjs <dir> <input.json> <output.json> [reps]
use racinglines_replay::{notional_prefix, replay, summarize, Event, Params};
use serde::Deserialize;
use std::time::Instant;

#[derive(Deserialize)]
struct Input { event: Event, calls: Vec<Params> }

fn main() {
    let a: Vec<String> = std::env::args().collect();
    if a.len() < 3 { eprintln!("usage: replay <input.json> <output.json> [reps]"); std::process::exit(2); }
    let inp: Input = serde_json::from_str(&std::fs::read_to_string(&a[1]).expect("read input")).expect("parse input");
    let reps: usize = a.get(3).map(|s| s.parse().expect("reps")).unwrap_or(1).max(1);
    let cum = notional_prefix(&inp.event);
    let t0 = Instant::now();
    let mut outs = Vec::new();
    for r in 0..reps {
        for p in &inp.calls {
            let res = replay(&inp.event, &cum, p).unwrap_or_else(|e| panic!("{e}"));
            let s = summarize(&inp.event, &res);
            if r == 0 { outs.push((res, s)); }
        }
    }
    let dt = t0.elapsed().as_secs_f64() / reps as f64;
    let nq: usize = outs.iter().map(|o| o.0.quotes.len()).sum();
    let nf: usize = outs.iter().map(|o| o.0.fills.len()).sum();
    println!("replay: {} calls, {} quote decisions, {} fills, {:.4} s per pass with summaries (mean of {})",
             inp.calls.len(), nq, nf, dt, reps);
    let js: Vec<serde_json::Value> = outs.iter().map(|(r, s)| serde_json::json!({
        "quotes": r.quotes.iter().map(|q| serde_json::json!([q.t, q.market, q.run_id, q.bid, q.ask, q.why])).collect::<Vec<_>>(),
        "fills": r.fills.iter().map(|f| serde_json::json!([f.t, f.market, f.run_id, f.buy, f.price, f.qty])).collect::<Vec<_>>(),
        "summary": s,
    })).collect();
    std::fs::write(&a[2], serde_json::to_string(&js).unwrap()).expect("write output");
}
