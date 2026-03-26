//! Pricing engine for NexVigilant Station toll billing.
//!
//! Maps model IDs to Vertex AI per-token rates, applies the 30% harness
//! premium, and computes costs in microcents (1/10000 of a cent) for precision.
//!
//! Rate card versioned for invoice auditability.

use serde::{Deserialize, Serialize};

/// NexVigilant harness premium: 30% on top of standard model rates.
const HARNESS_MARKUP: f64 = 0.30;

/// Rate card version — increment when rates change.
const RATE_CARD_VERSION: &str = "2026-03-26-v1";

/// Per-model pricing in dollars per million tokens.
/// Source: Vertex AI / Anthropic API pricing as of 2026-03-26.
const RATES: &[ModelRate] = &[
    ModelRate {
        model_id: "claude-opus-4-6",
        input_per_million: 15.00,
        output_per_million: 75.00,
    },
    ModelRate {
        model_id: "claude-sonnet-4-6",
        input_per_million: 3.00,
        output_per_million: 15.00,
    },
    ModelRate {
        model_id: "claude-haiku-4-5",
        input_per_million: 0.80,
        output_per_million: 4.00,
    },
    ModelRate {
        model_id: "gemini-2.5-pro",
        input_per_million: 1.25,
        output_per_million: 10.00,
    },
    ModelRate {
        model_id: "gemini-2.5-flash",
        input_per_million: 0.15,
        output_per_million: 0.60,
    },
    ModelRate {
        model_id: "gpt-4o",
        input_per_million: 2.50,
        output_per_million: 10.00,
    },
];

/// Default rate for unknown models (conservative: Sonnet-level pricing).
const DEFAULT_RATE: ModelRate = ModelRate {
    model_id: "default",
    input_per_million: 3.00,
    output_per_million: 15.00,
};

struct ModelRate {
    model_id: &'static str,
    input_per_million: f64,
    output_per_million: f64,
}

/// Cost breakdown for a single tool call.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CostBreakdown {
    /// Base cost in microcents (standard model rate)
    pub base_cost_microcents: u64,
    /// Harness markup in microcents (30% premium)
    pub markup_microcents: u64,
    /// Total cost in microcents (base + markup)
    pub total_microcents: u64,
    /// Which rate card version was used
    pub rate_card_version: String,
    /// Model ID used for pricing
    pub model_id: String,
}

/// Rate card entry for public display.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RateCardEntry {
    pub model_id: String,
    pub input_per_million_usd: f64,
    pub output_per_million_usd: f64,
    pub harness_multiplier: f64,
    pub input_with_harness: f64,
    pub output_with_harness: f64,
}

/// Compute the cost of a tool call based on token counts and model.
///
/// Returns `None` if no model_id is provided (free tier or unidentified caller).
pub fn compute_cost(
    model_id: Option<&str>,
    input_tokens: u64,
    output_tokens: u64,
) -> Option<CostBreakdown> {
    let model = model_id?;

    let rate = RATES
        .iter()
        .find(|r| model.contains(r.model_id))
        .unwrap_or(&DEFAULT_RATE);

    // Convert from dollars-per-million to microcents-per-token
    // 1 dollar = 1_000_000 microcents (100 cents × 10_000 microcents/cent)
    // cost_dollars = tokens × rate_per_million / 1_000_000
    // cost_microcents = cost_dollars × 1_000_000 = tokens × rate_per_million
    let input_base = (input_tokens as f64 * rate.input_per_million) as u64;
    let output_base = (output_tokens as f64 * rate.output_per_million) as u64;
    let base_cost = input_base + output_base;
    let markup = (base_cost as f64 * HARNESS_MARKUP) as u64;

    Some(CostBreakdown {
        base_cost_microcents: base_cost,
        markup_microcents: markup,
        total_microcents: base_cost + markup,
        rate_card_version: RATE_CARD_VERSION.to_string(),
        model_id: model.to_string(),
    })
}

/// Get the full rate card for public display.
pub fn get_rate_card() -> Vec<RateCardEntry> {
    RATES
        .iter()
        .map(|r| RateCardEntry {
            model_id: r.model_id.to_string(),
            input_per_million_usd: r.input_per_million,
            output_per_million_usd: r.output_per_million,
            harness_multiplier: 1.0 + HARNESS_MARKUP,
            input_with_harness: r.input_per_million * (1.0 + HARNESS_MARKUP),
            output_with_harness: r.output_per_million * (1.0 + HARNESS_MARKUP),
        })
        .collect()
}

/// Get the harness markup percentage.
pub fn harness_markup_pct() -> f64 {
    HARNESS_MARKUP * 100.0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compute_cost_opus() {
        let cost = compute_cost(Some("claude-opus-4-6"), 1000, 500).unwrap();
        // input: 1000 * 15.0 = 15000 microcents
        // output: 500 * 75.0 = 37500 microcents
        // base: 52500, markup: 15750, total: 68250
        assert_eq!(cost.base_cost_microcents, 52500);
        assert_eq!(cost.markup_microcents, 15750);
        assert_eq!(cost.total_microcents, 68250);
        assert_eq!(cost.rate_card_version, RATE_CARD_VERSION);
    }

    #[test]
    fn test_compute_cost_sonnet() {
        let cost = compute_cost(Some("claude-sonnet-4-6"), 1000, 500).unwrap();
        // input: 1000 * 3.0 = 3000
        // output: 500 * 15.0 = 7500
        // base: 10500, markup: 3150, total: 13650
        assert_eq!(cost.base_cost_microcents, 10500);
        assert_eq!(cost.markup_microcents, 3150);
        assert_eq!(cost.total_microcents, 13650);
    }

    #[test]
    fn test_compute_cost_haiku() {
        let cost = compute_cost(Some("claude-haiku-4-5"), 10000, 5000).unwrap();
        // input: 10000 * 0.8 = 8000
        // output: 5000 * 4.0 = 20000
        // base: 28000, markup: 8400, total: 36400
        assert_eq!(cost.base_cost_microcents, 28000);
        assert_eq!(cost.markup_microcents, 8400);
        assert_eq!(cost.total_microcents, 36400);
    }

    #[test]
    fn test_no_model_returns_none() {
        assert!(compute_cost(None, 1000, 500).is_none());
    }

    #[test]
    fn test_unknown_model_uses_default() {
        let cost = compute_cost(Some("unknown-model-v99"), 1000, 500).unwrap();
        // Uses default (Sonnet-level): same as sonnet test
        assert_eq!(cost.base_cost_microcents, 10500);
    }

    #[test]
    fn test_rate_card_completeness() {
        let card = get_rate_card();
        assert_eq!(card.len(), RATES.len());
        for entry in &card {
            assert!(entry.harness_multiplier > 1.0);
            assert!(entry.input_with_harness > entry.input_per_million_usd);
            assert!(entry.output_with_harness > entry.output_per_million_usd);
        }
    }

    #[test]
    fn test_harness_markup() {
        assert!((harness_markup_pct() - 30.0).abs() < f64::EPSILON);
    }
}
