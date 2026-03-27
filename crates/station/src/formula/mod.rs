//! Formula — Rust-native handler for NexVigilant Station.
//! Routes `formula_nexvigilant_com_*`. Pure inline math, no crate deps.

use serde_json::{Value, json};
use tracing::info;
use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("formula_nexvigilant_com_")?.replace('_', "-");
    let result = match bare.as_str() {
        "signal-strength" => handle_signal_strength(args),
        "domain-distance" => handle_domain_distance(args),
        "flywheel-velocity" => handle_flywheel_velocity(args),
        "token-ratio" => handle_token_ratio(args),
        "spectral-overlap" => handle_spectral_overlap(args),
        _ => return None,
    };
    info!(tool = tool_name, "Handled natively (formula)");
    Some(ToolCallResult {
        content: vec![ContentBlock::Text { text: serde_json::to_string_pretty(&result).unwrap_or_default() }],
        is_error: if result.get("status").and_then(|s| s.as_str()) == Some("error") { Some(true) } else { None },
    })
}

fn ok(v: Value) -> Value { let mut o = v; if let Some(m) = o.as_object_mut() { m.insert("status".into(), json!("ok")); } o }
fn err(msg: &str) -> Value { json!({ "status": "error", "error": msg }) }
fn r4(v: f64) -> f64 { (v * 10000.0).round() / 10000.0 }
fn get_f64(a: &Value, k: &str) -> Option<f64> { a.get(k).and_then(|v| v.as_f64()) }
fn get_f64_arr(a: &Value, k: &str) -> Option<Vec<f64>> { a.get(k).and_then(|v| v.as_array()).map(|a| a.iter().filter_map(|v| v.as_f64()).collect()) }
fn get_str_arr(a: &Value, k: &str) -> Option<Vec<String>> { a.get(k).and_then(|v| v.as_array()).map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect()) }

fn handle_signal_strength(args: &Value) -> Value {
    let u = match get_f64(args, "unexpectedness") { Some(v) if (0.0..=1.0).contains(&v) => v, _ => return err("unexpectedness must be in [0,1]") };
    let r = match get_f64(args, "robustness") { Some(v) if (0.0..=1.0).contains(&v) => v, _ => return err("robustness must be in [0,1]") };
    let t = match get_f64(args, "therapeutic_importance") { Some(v) if (0.0..=1.0).contains(&v) => v, _ => return err("therapeutic_importance must be in [0,1]") };
    let s = u * r * t;
    let class = if s >= 0.5 { "strong" } else if s >= 0.2 { "moderate" } else if s >= 0.05 { "weak" } else { "negligible" };
    ok(json!({ "signal_strength": r4(s), "unexpectedness": u, "robustness": r, "therapeutic_importance": t, "classification": class, "formula": "S = U × R × T" }))
}

fn handle_domain_distance(args: &Value) -> Value {
    let pa = match get_str_arr(args, "primitives_a") { Some(v) => v, None => return err("missing: primitives_a") };
    let pb = match get_str_arr(args, "primitives_b") { Some(v) => v, None => return err("missing: primitives_b") };
    let w1 = get_f64(args, "w1").unwrap_or(0.5);
    let w2 = get_f64(args, "w2").unwrap_or(0.3);
    let w3 = get_f64(args, "w3").unwrap_or(0.2);

    let a: std::collections::HashSet<String> = pa.iter().map(|s| s.to_lowercase()).collect();
    let b: std::collections::HashSet<String> = pb.iter().map(|s| s.to_lowercase()).collect();

    let t1_names = ["sequence","σ","mapping","μ","state","ς","recursion","ρ","void","∅","boundary","∂","frequency","ν","existence","∃","persistence","π","causality","→","comparison","κ","quantity","n","location","λ","irreversibility","∝","sum","Σ","product","×"];
    let is_t1 = |s: &str| t1_names.contains(&s.to_lowercase().as_str());

    let a_t1: std::collections::HashSet<_> = a.iter().filter(|s| is_t1(s)).collect();
    let b_t1: std::collections::HashSet<_> = b.iter().filter(|s| is_t1(s)).collect();
    let a_t3: std::collections::HashSet<_> = a.iter().filter(|s| !is_t1(s)).collect();
    let b_t3: std::collections::HashSet<_> = b.iter().filter(|s| !is_t1(s)).collect();

    let jaccard = |a: &std::collections::HashSet<&String>, b: &std::collections::HashSet<&String>| -> f64 {
        let i = a.intersection(b).count() as f64;
        let u = a.union(b).count() as f64;
        if u == 0.0 { 1.0 } else { i / u }
    };

    let t1_o = jaccard(&a_t1, &b_t1);
    let t3_o = jaccard(&a_t3, &b_t3);
    let all_a: std::collections::HashSet<_> = a.iter().collect();
    let all_b: std::collections::HashSet<_> = b.iter().collect();
    let t2_o = jaccard(&all_a, &all_b);

    let weighted = w1 * t1_o + w2 * t2_o + w3 * t3_o;
    let dist = (1.0 - weighted).clamp(0.0, 1.0);
    let class = if dist <= 0.2 { "very_close" } else if dist <= 0.4 { "close" } else if dist <= 0.6 { "moderate" } else if dist <= 0.8 { "distant" } else { "very_distant" };

    ok(json!({ "distance": r4(dist), "t1_overlap": r4(t1_o), "t2_overlap": r4(t2_o), "t3_overlap": r4(t3_o), "classification": class, "formula": "d = 1 - (w1×T1 + w2×T2 + w3×T3)" }))
}

fn handle_flywheel_velocity(args: &Value) -> Value {
    let fails = match get_f64_arr(args, "failure_timestamps") { Some(v) => v, None => return err("missing: failure_timestamps") };
    let fixes = match get_f64_arr(args, "fix_timestamps") { Some(v) => v, None => return err("missing: fix_timestamps") };
    if fails.len() != fixes.len() { return err("timestamp arrays must have same length"); }
    if fails.is_empty() { return err("need at least one pair"); }

    let mut deltas = Vec::new();
    for (f, x) in fails.iter().zip(fixes.iter()) { if x >= f { deltas.push(x - f); } }
    if deltas.is_empty() { return err("all pairs have fix < failure"); }

    let avg_ms = deltas.iter().sum::<f64>() / deltas.len() as f64;
    let avg_h = avg_ms / 3_600_000.0;
    let vel = if avg_h > 0.0 { 1.0 / avg_h } else { f64::INFINITY };
    let class = if avg_h <= 1.0 { "exceptional" } else if avg_h <= 24.0 { "target" } else if avg_h <= 168.0 { "acceptable" } else { "slow" };

    ok(json!({ "velocity_per_hour": r4(vel), "avg_delta_hours": r4(avg_h), "valid_pairs": deltas.len(), "classification": class }))
}

fn handle_token_ratio(args: &Value) -> Value {
    let tokens = match args.get("token_count").and_then(|v| v.as_u64()) { Some(v) => v, None => return err("missing: token_count") };
    let ops = match args.get("operation_count").and_then(|v| v.as_u64()) { Some(v) if v > 0 => v, _ => return err("operation_count must be > 0") };
    let ratio = tokens as f64 / ops as f64;
    let class = if ratio <= 0.5 { "excellent" } else if ratio <= 1.0 { "target" } else if ratio <= 2.0 { "verbose" } else { "wasteful" };
    ok(json!({ "token_ratio": r4(ratio), "operations_per_token": r4(1.0 / ratio), "classification": class }))
}

fn handle_spectral_overlap(args: &Value) -> Value {
    let a = match get_f64_arr(args, "spectrum_a") { Some(v) => v, None => return err("missing: spectrum_a") };
    let b = match get_f64_arr(args, "spectrum_b") { Some(v) => v, None => return err("missing: spectrum_b") };
    if a.len() != b.len() { return err("spectra must have same dimensionality"); }
    if a.is_empty() { return err("spectra must not be empty"); }

    let dot: f64 = a.iter().zip(b.iter()).map(|(x, y)| x * y).sum();
    let na: f64 = a.iter().map(|x| x * x).sum::<f64>().sqrt();
    let nb: f64 = b.iter().map(|x| x * x).sum::<f64>().sqrt();
    let denom = na * nb;
    if denom == 0.0 { return err("zero vector"); }
    let overlap = dot / denom;
    let class = if overlap >= 0.9 { "highly_similar" } else if overlap >= 0.7 { "similar" } else if overlap >= 0.4 { "moderate" } else if overlap >= 0.0 { "dissimilar" } else { "anti_correlated" };

    ok(json!({ "overlap": r4(overlap), "dimensionality": a.len(), "classification": class }))
}
