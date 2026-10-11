//! rlslip: a Rust command-line demo of `racinglines book price` (docs/sportsbook/slips.md). It reads a book file of
//! generic sportsbook lines and a fair-price file, and prints each bet's book, model and market probability, EV
//! against both, and a fractional-Kelly stake under a per-book cap. No database and no network: the fair prices are
//! a file, where the Python command reads a stored model run and the linked exchange markets.

mod book;
mod odds;
mod price;

use clap::{Parser, Subcommand, ValueEnum};
use price::{Basis, LineOut, Report, Sizing};

#[derive(Parser)]
#[command(name = "rlslip", version, about = "Sportsbook slip EV against a model and a market (Rust demo)")]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// Price every line of a book file against a fair-price file.
    Price {
        /// A book file (docs/sportsbook/index.md schema).
        book: String,
        /// A fair-price file: [[prices]] with kind, driver / opponent / team / line, model, market.
        #[arg(long)]
        fair: String,
        /// Print the whole result as JSON.
        #[arg(long)]
        json: bool,
        /// Bankroll in the book's currency.
        #[arg(long, default_value_t = 1000.0)]
        bankroll: f64,
        /// Kelly multiplier (0.25 = quarter Kelly).
        #[arg(long, default_value_t = 0.25)]
        kelly: f64,
        /// Cap on the total staked across the whole book file (one venue, one event).
        #[arg(long, default_value_t = 100.0)]
        max_stake: f64,
        /// Which probability sizes the stakes. EV is always shown against both.
        #[arg(long, value_enum, default_value_t = BasisArg::Model)]
        basis: BasisArg,
    },
    /// Show one quote in every odds presentation.
    Odds {
        /// The quote, e.g. 3.5, -118, 7/4.
        #[arg(allow_negative_numbers = true)]
        value: String,
        /// Its presentation.
        #[arg(long, default_value = "decimal")]
        from: String,
    },
}

#[derive(Clone, Copy, ValueEnum)]
enum BasisArg {
    Model,
    Market,
}

fn pct(x: Option<f64>) -> String {
    x.map(|v| format!("{:.1}%", v * 100.0)).unwrap_or_else(|| "-".into())
}

fn signed(x: Option<f64>) -> String {
    x.map(|v| format!("{:+.1}%", v * 100.0)).unwrap_or_else(|| "-".into())
}

fn money(x: Option<f64>) -> String {
    x.map(|v| format!("{v:.2}")).unwrap_or_else(|| "-".into())
}

fn trunc(s: &str, n: usize) -> String {
    if s.chars().count() <= n { s.to_string() } else { s.chars().take(n - 1).collect::<String>() + "…" }
}

fn print_table(r: &Report) {
    println!(
        "{} · event {} · odds {} · captured {}",
        r.venue,
        r.event,
        r.odds,
        r.captured_utc.as_deref().unwrap_or("unknown")
    );
    println!(
        "fair: {} (as of {})",
        r.fair_source.as_deref().unwrap_or("unknown"),
        r.fair_as_of_utc.as_deref().unwrap_or("unknown")
    );
    println!();
    println!(
        "{:<8} {:<30} {:>7} {:>7} {:>7} {:>7} {:>8} {:>8} {:>7}",
        "id", "selection", "odds", "book", "model", "market", "EV mod", "EV mkt", "stake"
    );
    let row = |l: &LineOut| {
        println!(
            "{:<8} {:<30} {:>7} {:>7} {:>7} {:>7} {:>8} {:>8} {:>7}",
            trunc(&l.id, 8),
            trunc(&l.selection, 30),
            l.decimal_odds.map(|d| format!("{d:.2}")).unwrap_or_else(|| "-".into()),
            pct(l.book_prob),
            pct(l.model_prob),
            pct(l.market_prob),
            signed(l.ev_model),
            signed(l.ev_market),
            money(l.stake)
        );
    };
    for l in r.lines.iter().filter(|l| l.status == "priced") {
        row(l);
        if l.legs.len() > 1 {
            for g in &l.legs {
                println!(
                    "  {:<6} {:<30} {:>7} {:>7} {:>7} {:>7}",
                    g.leg,
                    trunc(&format!("{} {} {}", g.kind, g.subject, g.side), 30),
                    g.decimal_odds.map(|d| format!("{d:.2}")).unwrap_or_else(|| "".into()),
                    pct(g.book_prob),
                    pct(g.model_prob),
                    pct(g.market_prob)
                );
            }
        }
        for f in &l.flags {
            println!("  ! {f}");
        }
        for g in &l.legs {
            if let Some(n) = &g.note {
                println!("  · leg {}: {n}", g.leg);
            }
        }
    }
    println!();
    println!(
        "stakes: {} basis, {} x Kelly on {:.0} {}, cap {:.0} per book{} · total {:.2}",
        r.sizing.basis,
        r.sizing.kelly,
        r.sizing.bankroll,
        r.currency.as_deref().unwrap_or(""),
        r.sizing.max_stake,
        if r.sizing.scaled_to_cap { " (scaled down to the cap)" } else { "" },
        r.total_stake
    );
    if !r.overround.is_empty() {
        println!("sum of implied probabilities per title (over 100% is the margin when the set is complete):");
        for o in &r.overround {
            println!("  {:<40} {} lines  {:.1}%", trunc(&o.title, 40), o.n_lines, o.sum_book_prob * 100.0);
        }
    }
    for l in r.lines.iter().filter(|l| l.status != "priced") {
        println!("{} {}: {} ({})", l.status, l.id, l.selection, l.reason.as_deref().unwrap_or(""));
    }
    println!("blend: {}", r.blend);
}

fn run() -> Result<(), String> {
    match Cli::parse().cmd {
        Cmd::Price { book, fair, json, bankroll, kelly, max_stake, basis } => {
            if !(bankroll > 0.0 && kelly >= 0.0 && max_stake >= 0.0) {
                return Err("--bankroll must be positive; --kelly and --max-stake not negative".into());
            }
            let b: book::BookFile = book::load(&book)?;
            if !odds::FORMATS.contains(&b.book.odds.as_str()) {
                return Err(format!("{book}: unknown odds format {:?}", b.book.odds));
            }
            let f: book::FairFile = book::load(&fair)?;
            let basis = match basis {
                BasisArg::Model => Basis::Model,
                BasisArg::Market => Basis::Market,
            };
            let r = price::price(&b, &f, &Sizing { bankroll, kelly, max_stake, basis });
            if json {
                println!("{}", serde_json::to_string_pretty(&r).map_err(|e| e.to_string())?);
            } else {
                print_table(&r);
            }
        }
        Cmd::Odds { value, from } => {
            let q = match value.parse::<f64>() {
                Ok(v) if from != "fractional" => odds::Quote::Num(v),
                _ => odds::Quote::Text(value.clone()),
            };
            let p = odds::to_prob(&q, &from)?;
            let am = if p >= 0.5 { -(100.0 * p / (1.0 - p)) } else { 100.0 * (1.0 - p) / p };
            println!("implied probability  {:.4}", p);
            println!("decimal              {:.3}", 1.0 / p);
            println!("american             {:+.0}", am);
            println!("cents                {:.1}", p * 100.0);
        }
    }
    Ok(())
}

fn main() {
    if let Err(e) = run() {
        eprintln!("rlslip: {e}");
        std::process::exit(2);
    }
}
