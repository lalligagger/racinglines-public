//! Prices every line of a book against the fair file, following `racinglines/books/slips.py` `price_book`:
//! model and market side by side (no blend), legs on one race multiplied and flagged as correlated, legs on
//! different races multiplied as independent. Then sizes stakes with fractional Kelly under a per-book cap.

use crate::book::{BookFile, FairFile, Leg, Market, Price};
use crate::odds;
use serde::Serialize;
use std::collections::BTreeMap;

pub const CORRELATED: &str = "correlated: EV approximate";

#[derive(Debug, Clone, Copy)]
pub enum Basis {
    Model,
    Market,
}

#[derive(Debug, Clone)]
pub struct Sizing {
    pub bankroll: f64,
    pub kelly: f64,
    pub max_stake: f64,
    pub basis: Basis,
}

#[derive(Debug, Serialize)]
pub struct LegOut {
    pub leg: String,
    pub sport: Option<String>,
    pub event: String,
    pub kind: String,
    pub side: String,
    pub subject: String,
    pub decimal_odds: Option<f64>,
    pub book_prob: Option<f64>,
    pub model_prob: Option<f64>,
    pub market_prob: Option<f64>,
    pub ev_model: Option<f64>,
    pub ev_market: Option<f64>,
    pub note: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct LineOut {
    pub line: usize,
    pub id: String,
    pub title: String,
    pub selection: String,
    pub kind: String,
    pub status: String,
    pub reason: Option<String>,
    pub decimal_odds: Option<f64>,
    pub book_prob: Option<f64>,
    pub model_prob: Option<f64>,
    pub market_prob: Option<f64>,
    pub edge_model: Option<f64>,
    pub edge_market: Option<f64>,
    pub ev_model: Option<f64>,
    pub ev_market: Option<f64>,
    pub kelly_full: Option<f64>,
    pub stake: Option<f64>,
    pub flags: Vec<String>,
    pub legs: Vec<LegOut>,
}

#[derive(Debug, Serialize)]
pub struct Overround {
    pub title: String,
    pub event: String,
    pub n_lines: usize,
    pub sum_book_prob: f64,
}

#[derive(Debug, Serialize)]
pub struct Report {
    pub venue: String,
    pub event: String,
    pub sport: Option<String>,
    pub captured_utc: Option<String>,
    pub odds: String,
    pub currency: Option<String>,
    pub fair_source: Option<String>,
    pub fair_as_of_utc: Option<String>,
    pub sizing: SizingOut,
    pub lines: Vec<LineOut>,
    pub overround: Vec<Overround>,
    pub unmapped: Vec<String>,
    pub total_stake: f64,
    pub blend: &'static str,
}

#[derive(Debug, Serialize)]
pub struct SizingOut {
    pub basis: &'static str,
    pub bankroll: f64,
    pub kelly: f64,
    pub max_stake: f64,
    pub scaled_to_cap: bool,
}

fn complement(side: &str) -> bool {
    matches!(side, "no" | "under")
}

fn r6(x: f64) -> f64 {
    (x * 1e6).round() / 1e6
}

fn subject(leg: &Leg) -> String {
    let mut s = match (&leg.driver, &leg.opponent, &leg.team) {
        (Some(d), Some(o), _) => format!("{d} v {o}"),
        (Some(d), None, _) => d.clone(),
        (None, _, Some(t)) => t.clone(),
        _ => String::new(),
    };
    if let Some(l) = leg.line {
        s = if s.is_empty() { format!("{l}") } else { format!("{s} {l}") };
    }
    s
}

/// The fair (model, market) of the leg's yes side, by exact keys; an h2h listed the other way round is the complement.
fn lookup(
    prices: &[Price],
    sport: &Option<String>,
    event: &str,
    leg: &Leg,
    book_sport: &Option<String>,
    book_event: &str,
) -> Option<(Option<f64>, Option<f64>, bool)> {
    for p in prices {
        let p_sport = p.sport.clone().or_else(|| book_sport.clone());
        let p_event = p.event.as_deref().unwrap_or(book_event);
        if p.kind != leg.kind || p_sport != *sport || p_event != event || p.team != leg.team || p.line != leg.line {
            continue;
        }
        if p.driver == leg.driver && p.opponent == leg.opponent {
            return Some((p.model, p.market, false));
        }
        if leg.opponent.is_some() && p.driver == leg.opponent && p.opponent == leg.driver {
            return Some((p.model.map(|x| 1.0 - x), p.market.map(|x| 1.0 - x), true));
        }
    }
    None
}

fn product(xs: &[Option<f64>]) -> Option<f64> {
    xs.iter().try_fold(1.0, |acc, x| x.map(|v| acc * v))
}

pub fn price(book: &BookFile, fair: &FairFile, sizing: &Sizing) -> Report {
    let h = &book.book;
    let mut lines = Vec::new();
    let mut unmapped = Vec::new();
    for (i, line) in book.lines.iter().enumerate() {
        let n = i + 1;
        let id = line.id.clone().unwrap_or_else(|| n.to_string());
        let mut out = LineOut {
            line: n,
            id: id.clone(),
            title: line.title.clone(),
            selection: line.selection.clone(),
            kind: String::new(),
            status: "priced".into(),
            reason: None,
            decimal_odds: None,
            book_prob: None,
            model_prob: None,
            market_prob: None,
            edge_model: None,
            edge_market: None,
            ev_model: None,
            ev_market: None,
            kelly_full: None,
            stake: None,
            flags: vec![],
            legs: vec![],
        };
        let m = match &line.market {
            Market::Table(m) => m,
            Market::Unmapped(s) => {
                out.status = "unmapped".into();
                out.reason = Some(format!("market = {s:?}"));
                unmapped.push(id);
                lines.push(out);
                continue;
            }
        };
        out.kind = m.kind.clone();
        let legs: Vec<&Leg> = if m.kind == "combo" { m.legs.iter().collect() } else { vec![m] };
        if legs.is_empty() {
            out.status = "unmapped".into();
            out.reason = Some("a combo with no legs".into());
            unmapped.push(id);
            lines.push(out);
            continue;
        }

        // Per leg: its own odds (a parlay leg), and the fair for its side.
        let mut groups: BTreeMap<(Option<String>, String), Vec<usize>> = BTreeMap::new();
        let mut bad = None;
        for (j, leg) in legs.iter().enumerate() {
            let sport = leg.sport.clone().or_else(|| h.sport.clone());
            let event = leg.event.clone().unwrap_or_else(|| h.event.clone());
            let side = leg.side.clone().unwrap_or_else(|| "yes".into());
            let dec = match leg.odds.as_ref().map(|q| odds::decimal(q, &h.odds)).transpose() {
                Ok(d) => d,
                Err(e) => {
                    bad = Some(format!("leg {}: {e}", j + 1));
                    None
                }
            };
            let hit = lookup(&fair.prices, &sport, &event, leg, &h.sport, &h.event);
            let flip = |p: Option<f64>| p.map(|x| if complement(&side) { 1.0 - x } else { x });
            let (model, market, note) = match hit {
                Some((mo, mk, rev)) => (flip(mo), flip(mk), rev.then(|| "h2h listed the other way round".to_string())),
                None => (None, None, Some("no fair price for this key".to_string())),
            };
            groups.entry((sport.clone(), event.clone())).or_default().push(j);
            out.legs.push(LegOut {
                leg: if legs.len() > 1 { format!("{n}.{}", j + 1) } else { n.to_string() },
                sport,
                event,
                kind: leg.kind.clone(),
                side,
                subject: subject(leg),
                decimal_odds: dec.map(r6),
                book_prob: dec.map(|d| r6(1.0 / d)),
                model_prob: model.map(r6),
                market_prob: market.map(r6),
                ev_model: dec.zip(model).map(|(d, p)| r6(odds::ev(p, d))),
                ev_market: dec.zip(market).map(|(d, p)| r6(odds::ev(p, d))),
                note,
            });
        }

        // The payout: the line's own odds, else the product of its legs' odds.
        let dec = match &line.odds {
            Some(q) => odds::decimal(q, &h.odds).map(Some),
            None => Ok(product(&out.legs.iter().map(|l| l.decimal_odds).collect::<Vec<_>>())),
        };
        let dec = match (dec, bad) {
            (Ok(Some(d)), None) => d,
            (Ok(None), None) => {
                out.status = "error".into();
                out.reason = Some("no odds on the line or on every leg".into());
                lines.push(out);
                continue;
            }
            (Err(e), _) | (_, Some(e)) => {
                out.status = "error".into();
                out.reason = Some(e);
                lines.push(out);
                continue;
            }
        };

        let model = product(&out.legs.iter().map(|l| l.model_prob).collect::<Vec<_>>());
        let market = product(&out.legs.iter().map(|l| l.market_prob).collect::<Vec<_>>());
        for ((_, event), js) in &groups {
            if js.len() > 1 {
                out.flags.push(format!("{} legs on {event}: product of marginals, {CORRELATED}", js.len()));
            }
        }
        if groups.len() > 1 {
            out.flags.push(format!("legs on {} races: independent across races (product)", groups.len()));
        }
        let book_p = 1.0 / dec;
        out.decimal_odds = Some(r6(dec));
        out.book_prob = Some(r6(book_p));
        out.model_prob = model.map(r6);
        out.market_prob = market.map(r6);
        out.edge_model = model.map(|p| r6(p - book_p));
        out.edge_market = market.map(|p| r6(p - book_p));
        out.ev_model = model.map(|p| r6(odds::ev(p, dec)));
        out.ev_market = market.map(|p| r6(odds::ev(p, dec)));
        let basis_p = match sizing.basis {
            Basis::Model => model,
            Basis::Market => market,
        };
        out.kelly_full = basis_p.map(|p| r6(odds::kelly(p, dec)));
        lines.push(out);
    }

    // Stakes: bankroll x Kelly multiplier x full Kelly, then scaled down together if the book's total is over the cap.
    let raw: Vec<f64> = lines.iter().map(|l| l.kelly_full.unwrap_or(0.0) * sizing.kelly * sizing.bankroll).collect();
    let total: f64 = raw.iter().sum();
    let scale = if total > sizing.max_stake && total > 0.0 { sizing.max_stake / total } else { 1.0 };
    let mut total_stake = 0.0;
    for (l, s) in lines.iter_mut().zip(raw) {
        if l.kelly_full.is_some() {
            let st = (s * scale * 100.0).floor() / 100.0;
            total_stake += st;
            l.stake = Some(st);
        }
    }

    // Sum of implied probabilities per market title among single lines: over 1 is the margin, when the set is full.
    let mut by_title: BTreeMap<(String, String), (usize, f64)> = BTreeMap::new();
    for (line, out) in book.lines.iter().zip(&lines) {
        if let (Market::Table(m), Some(bp)) = (&line.market, out.book_prob)
            && m.kind != "combo"
        {
            let ev = m.event.clone().unwrap_or_else(|| h.event.clone());
            let e = by_title.entry((line.title.clone(), ev)).or_insert((0, 0.0));
            e.0 += 1;
            e.1 += bp;
        }
    }
    let overround = by_title
        .into_iter()
        .filter(|(_, (n, _))| *n > 1)
        .map(|((title, event), (n_lines, s))| Overround { title, event, n_lines, sum_book_prob: r6(s) })
        .collect();

    Report {
        venue: h.venue.clone(),
        event: h.event.clone(),
        sport: h.sport.clone(),
        captured_utc: h.captured_utc.clone(),
        odds: h.odds.clone(),
        currency: h.currency.clone(),
        fair_source: fair.fair.source.clone(),
        fair_as_of_utc: fair.fair.as_of_utc.clone(),
        sizing: SizingOut {
            basis: match sizing.basis {
                Basis::Model => "model",
                Basis::Market => "market",
            },
            bankroll: sizing.bankroll,
            kelly: sizing.kelly,
            max_stake: sizing.max_stake,
            scaled_to_cap: scale < 1.0,
        },
        lines,
        overround,
        unmapped,
        total_stake: (total_stake * 100.0).round() / 100.0,
        blend: "none: model and market shown side by side (owner, 2026-10-07; docs/sportsbook/slips.md)",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::book::{BookFile, FairFile};

    const BOOK: &str = r#"
[book]
venue = "book_x"
event = "2026-17"
sport = "f1"
odds = "decimal"

[[lines]]
id = "win"
title = "Race Winner"
selection = "Ann Alpha"
odds = 3.0
market = { kind = "race_win", driver = "Ann Alpha" }

[[lines]]
id = "win2"
title = "Race Winner"
selection = "Bea Beta"
odds = 2.0
market = { kind = "race_win", driver = "Bea Beta" }

[[lines]]
id = "h2h"
title = "Head to head"
selection = "Bea Beta"
odds = 1.8
market = { kind = "h2h", driver = "Bea Beta", opponent = "Ann Alpha" }

[[lines]]
id = "parlay"
title = "Parlay"
selection = "Cora Cup win + Dan Duke win"
market = { kind = "combo", legs = [
  { kind = "race_win", driver = "Cora Cup", sport = "nascar", event = "2026-30", odds = 2.0 },
  { kind = "race_win", driver = "Dan Duke", sport = "motogp", event = "2026-18", odds = 4.0 },
] }

[[lines]]
id = "sgp"
title = "Same race"
selection = "Ann Alpha win + podium"
odds = 2.5
market = { kind = "combo", legs = [
  { kind = "race_win", driver = "Ann Alpha" },
  { kind = "race_podium", driver = "Ann Alpha" },
] }

[[lines]]
title = "Red flag"
selection = "No"
odds = 1.5
market = "unmapped"
"#;

    const FAIR: &str = r#"
[[prices]]
kind = "race_win"
driver = "Ann Alpha"
model = 0.40
market = 0.30
[[prices]]
kind = "race_win"
driver = "Bea Beta"
model = 0.45
market = 0.50
[[prices]]
kind = "race_podium"
driver = "Ann Alpha"
model = 0.80
[[prices]]
kind = "h2h"
driver = "Ann Alpha"
opponent = "Bea Beta"
model = 0.40
market = 0.45
[[prices]]
sport = "nascar"
event = "2026-30"
kind = "race_win"
driver = "Cora Cup"
model = 0.5
market = 0.55
[[prices]]
sport = "motogp"
event = "2026-18"
kind = "race_win"
driver = "Dan Duke"
model = 0.3
market = 0.2
"#;

    fn run(max_stake: f64) -> Report {
        let book: BookFile = toml::from_str(BOOK).unwrap();
        let fair: FairFile = toml::from_str(FAIR).unwrap();
        price(&book, &fair, &Sizing { bankroll: 1000.0, kelly: 0.25, max_stake, basis: Basis::Model })
    }

    fn line<'a>(r: &'a Report, id: &str) -> &'a LineOut {
        r.lines.iter().find(|l| l.id == id).unwrap()
    }

    #[test]
    fn single_ev_both_sides() {
        let r = run(1e9);
        let w = line(&r, "win");
        assert_eq!(w.ev_model, Some(0.2)); // 0.4 x 3 - 1
        assert_eq!(w.ev_market, Some(-0.1));
        assert_eq!(w.kelly_full, Some(0.1));
        assert_eq!(w.stake, Some(25.0)); // 1000 x 0.25 x 0.1
    }

    #[test]
    fn reversed_h2h_is_the_complement() {
        let r = run(1e9);
        let l = line(&r, "h2h");
        assert_eq!(l.model_prob, Some(0.6));
        assert_eq!(l.market_prob, Some(0.55));
    }

    #[test]
    fn parlay_pays_product_and_is_independent() {
        let r = run(1e9);
        let l = line(&r, "parlay");
        assert_eq!(l.decimal_odds, Some(8.0));
        assert_eq!(l.model_prob, Some(0.15));
        assert_eq!(l.market_prob, Some(0.11));
        assert!(l.flags.iter().any(|f| f.contains("independent across races")));
    }

    #[test]
    fn same_race_legs_flagged_and_missing_market_is_none() {
        let r = run(1e9);
        let l = line(&r, "sgp");
        assert_eq!(l.model_prob, Some(0.32));
        assert_eq!(l.market_prob, None);
        assert!(l.flags.iter().any(|f| f.contains(CORRELATED)));
    }

    #[test]
    fn cap_scales_stakes_and_unmapped_is_listed() {
        let r = run(30.0);
        assert!(r.sizing.scaled_to_cap);
        assert!(r.total_stake <= 30.0);
        assert_eq!(r.unmapped, vec!["6".to_string()]);
    }

    #[test]
    fn overround_sums_a_title() {
        let r = run(1e9);
        let o = r.overround.iter().find(|o| o.title == "Race Winner").unwrap();
        assert_eq!(o.n_lines, 2);
        assert!((o.sum_book_prob - (1.0 / 3.0 + 0.5)).abs() < 1e-6);
    }
}
