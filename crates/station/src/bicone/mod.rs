//! Bicone Geometry — convergent-divergent shape analysis.
//! Routes `bicone_nexvigilant_com_*`. Delegates to `nexcore-bicone`.

use nexcore_bicone::{metrics, types::BiconeProfile};
use serde_json::{Value, json};
use tracing::info;
use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("bicone_nexvigilant_com_")?.replace('_', "-");
    let result = match bare.as_str() {
        "compute-metrics" => handle_compute_metrics(args),
        "compare-profiles" => handle_compare_profiles(args),
        "hill-profile" => handle_hill_profile(args),
        _ => return None,
    };
    info!(tool = tool_name, "Handled natively (bicone)");
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
fn r4(v: f64) -> f64 { (v * 10000.0).round() / 10000.0 }

fn get_f64_arr(a: &Value, k: &str) -> Option<Vec<f64>> {
    a.get(k).and_then(|v| v.as_array()).map(|a| a.iter().filter_map(|v| v.as_f64()).collect())
}

fn handle_compute_metrics(args: &Value) -> Value {
    let widths = match get_f64_arr(args, "widths") {
        Some(w) if w.len() >= 3 => w,
        _ => return err("widths must be an array of at least 3 numbers"),
    };
    let profile = BiconeProfile { width_sequence: widths, level_labels: None };

    match metrics::compute_metrics(&profile) {
        Ok(m) => ok(json!({
            "volume": r4(m.volume),
            "entropy": r4(m.entropy),
            "entropy_normalized": r4(m.entropy_normalized),
            "asymmetry_ratio": r4(m.asymmetry_ratio),
            "convergence_rate": r4(m.convergence_rate),
            "singularity_index": m.singularity_index,
            "total_nodes": r4(m.total_nodes),
            "level_count": m.level_count,
        })),
        Err(e) => err(&e.to_string()),
    }
}

fn handle_compare_profiles(args: &Value) -> Value {
    let a = match get_f64_arr(args, "widths_a") {
        Some(w) if w.len() >= 3 => w,
        _ => return err("widths_a must be an array of at least 3 numbers"),
    };
    let b = match get_f64_arr(args, "widths_b") {
        Some(w) if w.len() >= 3 => w,
        _ => return err("widths_b must be an array of at least 3 numbers"),
    };
    let pa = BiconeProfile { width_sequence: a, level_labels: None };
    let pb = BiconeProfile { width_sequence: b, level_labels: None };

    match metrics::compare_profiles(&pa, &pb) {
        Ok(cmp) => ok(json!({
            "overlap": r4(cmp.overlap),
            "classification": cmp.classification,
            "divergent_levels": cmp.divergent_levels,
        })),
        Err(e) => err(&e.to_string()),
    }
}

fn handle_hill_profile(args: &Value) -> Value {
    let widths = match get_f64_arr(args, "widths") {
        Some(w) if w.len() >= 3 => w,
        _ => return err("widths must be an array of at least 3 numbers"),
    };

    let mut sorted = widths.clone();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let default_k = sorted[sorted.len() / 2];

    let k_half = args.get("k_half").and_then(|v| v.as_f64()).unwrap_or(default_k);
    let n_hill = args.get("n_hill").and_then(|v| v.as_f64()).unwrap_or(2.0);

    let activations = metrics::hill_profile(&widths, k_half, n_hill);

    ok(json!({
        "activations": activations.iter().map(|a| json!({
            "level": a.level,
            "width": r4(a.width),
            "activation": r4(a.response),
        })).collect::<Vec<_>>(),
        "k_half": r4(k_half),
        "n_hill": r4(n_hill),
    }))
}
