//! ToV Proofs — Harm Attenuation Theorem (T10.2).
//! Routes `tov_proofs_nexvigilant_com_*`. Delegates to `nexcore-tov-proofs`.
//!
//! By Matthew A. Campion, PharmD.

use nexcore_tov_proofs::attenuation::{
    self, PropagationProbability,
};
use serde_json::{Value, json};
use tracing::info;
use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("tov-proofs_nexvigilant_com_")?.replace('_', "-");
    let result = match bare.as_str() {
        "harm-probability" => handle_harm_probability(args),
        "exponential-harm" => handle_exponential_harm(args),
        "protective-depth" => handle_protective_depth(args),
        "verify-attenuation" => handle_verify_attenuation(args),
        "attenuation-rate" => handle_attenuation_rate(args),
        _ => return None,
    };
    info!(tool = tool_name, "Handled natively (tov-proofs)");
    Some(ToolCallResult {
        content: vec![ContentBlock::Text {
            text: serde_json::to_string_pretty(&result).unwrap_or_default(),
        }],
        is_error: if result.get("status").and_then(|s| s.as_str()) == Some("error") {
            Some(true)
        } else {
            None
        },
    })
}

fn ok(v: Value) -> Value {
    let mut o = v;
    if let Some(m) = o.as_object_mut() { m.insert("status".into(), json!("ok")); }
    o
}
fn err(msg: &str) -> Value { json!({ "status": "error", "error": msg }) }
fn r6(v: f64) -> f64 { (v * 1_000_000.0).round() / 1_000_000.0 }

fn parse_probs(args: &Value) -> Result<Vec<PropagationProbability>, Value> {
    let arr = match args.get("probabilities").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return Err(err("missing: probabilities (array of numbers in (0,1))")),
    };
    let mut probs = Vec::with_capacity(arr.len());
    for (i, v) in arr.iter().enumerate() {
        let f = match v.as_f64() {
            Some(f) => f,
            None => return Err(err(&format!("probabilities[{i}] is not a number"))),
        };
        if f <= 0.0 || f >= 1.0 {
            return Err(err(&format!("probabilities[{i}] = {f} must be in (0, 1)")));
        }
        probs.push(PropagationProbability::new(f));
    }
    if probs.is_empty() {
        return Err(err("probabilities must not be empty"));
    }
    Ok(probs)
}

fn handle_harm_probability(args: &Value) -> Value {
    let probs = match parse_probs(args) {
        Ok(p) => p,
        Err(e) => return e,
    };
    let hp = attenuation::harm_probability(&probs);
    let alpha = attenuation::attenuation_rate(&probs);

    ok(json!({
        "harm_probability": r6(hp),
        "layer_count": probs.len(),
        "attenuation_rate": r6(alpha),
        "formula": "ℙ(H|δs₁) = ∏ᵢP_{i→i+1}",
    }))
}

fn handle_exponential_harm(args: &Value) -> Value {
    let alpha = match args.get("alpha").and_then(|v| v.as_f64()) {
        Some(a) if a > 0.0 => a,
        _ => return err("alpha must be a positive number"),
    };
    let harm_level = match args.get("harm_level").and_then(|v| v.as_u64()) {
        Some(h) if h >= 1 => h as usize,
        _ => return err("harm_level must be an integer >= 1"),
    };

    let hp = attenuation::harm_probability_exponential(alpha, harm_level);

    ok(json!({
        "harm_probability": r6(hp),
        "alpha": alpha,
        "harm_level": harm_level,
        "formula": "ℙ(H) = e^{-α(H-1)}",
    }))
}

fn handle_protective_depth(args: &Value) -> Value {
    let target = match args.get("target_probability").and_then(|v| v.as_f64()) {
        Some(t) if t > 0.0 && t < 1.0 => t,
        _ => return err("target_probability must be in (0, 1)"),
    };
    let alpha = match args.get("attenuation_rate").and_then(|v| v.as_f64()) {
        Some(a) if a > 0.0 => a,
        _ => return err("attenuation_rate must be a positive number"),
    };

    let depth = attenuation::protective_depth(target, alpha);
    let achieved = attenuation::harm_probability_exponential(alpha, depth);

    ok(json!({
        "min_depth": depth,
        "achieved_probability": r6(achieved),
        "target_probability": target,
        "formula": "H ≥ 1 + log(1/ε)/α",
    }))
}

fn handle_verify_attenuation(args: &Value) -> Value {
    let probs = match parse_probs(args) {
        Ok(p) => p,
        Err(e) => return e,
    };
    let holds = attenuation::verify_attenuation(&probs);
    let bound = attenuation::uniform_bound(&probs);

    ok(json!({
        "attenuation_holds": holds,
        "layer_count": probs.len(),
        "uniform_bound": r6(bound),
        "theorem": "Harm decreases monotonically with protective depth",
    }))
}

fn handle_attenuation_rate(args: &Value) -> Value {
    let probs = match parse_probs(args) {
        Ok(p) => p,
        Err(e) => return e,
    };
    let alpha = attenuation::attenuation_rate(&probs);
    let geo_mean = (-alpha).exp();
    let interp = if alpha > 1.0 {
        "Strong attenuation — harm decays rapidly"
    } else if alpha > 0.3 {
        "Moderate attenuation — adequate protective layering"
    } else {
        "Weak attenuation — consider additional safety barriers"
    };

    ok(json!({
        "alpha": r6(alpha),
        "geometric_mean": r6(geo_mean),
        "interpretation": interp,
        "formula": "α = -log(P̄) where P̄ = geometric mean",
    }))
}
