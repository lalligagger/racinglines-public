//! Odds presentations, the same six as `racinglines/books/schema.py` (`ODDS_FORMATS`, `check_odds`, `to_prob`).

use serde::Deserialize;

/// A quote as written in a book file: a number, or a string for fractional odds ("7/4").
#[derive(Debug, Clone, Deserialize, serde::Serialize, PartialEq)]
#[serde(untagged)]
pub enum Quote {
    Num(f64),
    Text(String),
}

impl std::fmt::Display for Quote {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Quote::Num(v) => write!(f, "{v}"),
            Quote::Text(s) => write!(f, "{s}"),
        }
    }
}

pub const FORMATS: [&str; 6] = ["decimal", "american", "fractional", "cents", "dollars", "prob"];

fn fractional(s: &str) -> Option<(u64, u64)> {
    let (a, b) = s.split_once('/')?;
    let (a, b) = (a.trim().parse::<u64>().ok()?, b.trim().parse::<u64>().ok()?);
    (a > 0 && b > 0).then_some((a, b))
}

/// The implied probability of a quote in `fmt` (the venue's margin still in it), or the reason it can't be odds.
pub fn to_prob(q: &Quote, fmt: &str) -> Result<f64, String> {
    if fmt == "fractional" {
        return match q {
            Quote::Text(s) => fractional(s)
                .map(|(a, b)| b as f64 / (a + b) as f64)
                .ok_or_else(|| format!("fractional odds {s:?} must be a string like \"7/4\"")),
            Quote::Num(v) => Err(format!("fractional odds {v} must be a string like \"7/4\"")),
        };
    }
    let v = match q {
        Quote::Num(v) => *v,
        Quote::Text(s) => return Err(format!("{s:?} is not a number")),
    };
    match fmt {
        "decimal" if v > 1.0 => Ok(1.0 / v),
        "decimal" => Err(format!("decimal odds {v} must be above 1")),
        "american" if v == v.trunc() && v.abs() >= 100.0 => {
            Ok(if v < 0.0 { -v / (100.0 - v) } else { 100.0 / (v + 100.0) })
        }
        "american" => Err(format!("American odds {v} must be an integer of at least 100 either way")),
        "cents" if v == v.trunc() && (1.0..=99.0).contains(&v) => Ok(v / 100.0),
        "cents" => Err(format!("cents {v} must be an integer from 1 to 99")),
        "dollars" | "prob" if v > 0.0 && v < 1.0 => Ok(v),
        "dollars" | "prob" => Err(format!("{fmt} {v} must be between 0 and 1")),
        _ => Err(format!("unknown odds format {fmt:?}")),
    }
}

/// The payout per unit staked, stake included: 1 / the implied probability (`slips.decimal_odds`).
pub fn decimal(q: &Quote, fmt: &str) -> Result<f64, String> {
    to_prob(q, fmt).map(|p| 1.0 / p)
}

/// EV per unit staked of a bet paying `dec` that wins with probability `p` (`slips._ev`).
pub fn ev(p: f64, dec: f64) -> f64 {
    p * dec - 1.0
}

/// The full-Kelly fraction of bankroll for a bet paying `dec` with win probability `p`; 0 when the EV is not positive.
pub fn kelly(p: f64, dec: f64) -> f64 {
    if dec <= 1.0 {
        return 0.0;
    }
    (ev(p, dec) / (dec - 1.0)).max(0.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn close(a: f64, b: f64) -> bool {
        (a - b).abs() < 1e-12
    }

    // Expected values computed with racinglines.books.schema.to_prob on the same inputs.
    #[test]
    fn to_prob_matches_python() {
        assert!(close(to_prob(&Quote::Num(3.5), "decimal").unwrap(), 0.2857142857142857));
        assert!(close(to_prob(&Quote::Num(-118.0), "american").unwrap(), 0.5412844036697247));
        assert!(close(to_prob(&Quote::Num(150.0), "american").unwrap(), 0.4));
        assert!(close(to_prob(&Quote::Text("7/4".into()), "fractional").unwrap(), 0.36363636363636365));
        assert!(close(to_prob(&Quote::Num(37.0), "cents").unwrap(), 0.37));
        assert!(close(to_prob(&Quote::Num(0.37), "dollars").unwrap(), 0.37));
    }

    #[test]
    fn rejects_what_python_rejects() {
        assert!(to_prob(&Quote::Num(1.0), "decimal").is_err());
        assert!(to_prob(&Quote::Num(99.0), "american").is_err());
        assert!(to_prob(&Quote::Num(-118.5), "american").is_err());
        assert!(to_prob(&Quote::Text("7-4".into()), "fractional").is_err());
        assert!(to_prob(&Quote::Num(0.0), "cents").is_err());
        assert!(to_prob(&Quote::Num(1.0), "prob").is_err());
        assert!(to_prob(&Quote::Num(2.0), "euro").is_err());
    }

    #[test]
    fn ev_and_kelly() {
        assert!(close(ev(0.4, 3.0), 0.2));
        assert!(close(kelly(0.4, 3.0), 0.1)); // (0.4*3-1)/(3-1)
        assert_eq!(kelly(0.3, 3.0), 0.0);
    }
}
