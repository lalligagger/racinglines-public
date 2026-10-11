//! The book file (docs/sportsbook/index.md, docs/sportsbook/slips.md) and the fair-price file this demo reads.
//!
//! Only the fields pricing needs are read; anything else in the file (notes, source refs, aliases) is ignored.

use crate::odds::Quote;
use serde::Deserialize;

#[derive(Debug, Deserialize)]
pub struct BookFile {
    pub book: Header,
    #[serde(default)]
    pub lines: Vec<Line>,
}

#[derive(Debug, Deserialize)]
pub struct Header {
    pub venue: String,
    pub event: String,
    #[serde(default)]
    pub sport: Option<String>,
    #[serde(default)]
    pub captured_utc: Option<String>,
    pub odds: String,
    #[serde(default)]
    pub currency: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct Line {
    #[serde(default)]
    pub id: Option<String>,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub selection: String,
    #[serde(default)]
    pub odds: Option<Quote>,
    pub market: Market,
}

/// `market = "unmapped"`, or a market table.
#[derive(Debug, Deserialize)]
#[serde(untagged)]
pub enum Market {
    Unmapped(String),
    Table(Box<Leg>),
}

/// A market table: a single line's market, or one leg of a combo (`kind = "combo"`, `legs = [...]`).
#[derive(Debug, Clone, Deserialize, Default)]
pub struct Leg {
    pub kind: String,
    #[serde(default)]
    pub driver: Option<String>,
    #[serde(default)]
    pub opponent: Option<String>,
    #[serde(default)]
    pub team: Option<String>,
    #[serde(default)]
    pub line: Option<f64>,
    #[serde(default)]
    pub side: Option<String>,
    #[serde(default)]
    pub sport: Option<String>,
    #[serde(default)]
    pub event: Option<String>,
    #[serde(default)]
    pub odds: Option<Quote>,
    #[serde(default)]
    pub legs: Vec<Leg>,
}

/// Fair probabilities for the yes / over side of each market, keyed like a leg. In the app these come from a stored
/// model run and the linked exchange market (`racinglines book price`); here they are a plain file.
#[derive(Debug, Deserialize)]
pub struct FairFile {
    #[serde(default)]
    pub fair: FairHeader,
    #[serde(default)]
    pub prices: Vec<Price>,
}

#[derive(Debug, Deserialize, Default)]
pub struct FairHeader {
    #[serde(default)]
    pub source: Option<String>,
    #[serde(default)]
    pub as_of_utc: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct Price {
    #[serde(default)]
    pub sport: Option<String>,
    #[serde(default)]
    pub event: Option<String>,
    pub kind: String,
    #[serde(default)]
    pub driver: Option<String>,
    #[serde(default)]
    pub opponent: Option<String>,
    #[serde(default)]
    pub team: Option<String>,
    #[serde(default)]
    pub line: Option<f64>,
    #[serde(default)]
    pub model: Option<f64>,
    #[serde(default)]
    pub market: Option<f64>,
}

pub fn load<T: for<'de> Deserialize<'de>>(path: &str) -> Result<T, String> {
    let raw = std::fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))?;
    toml::from_str(&raw).map_err(|e| format!("{path}: {e}"))
}
