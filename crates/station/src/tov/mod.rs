//! Theory of Vigilance — Rust-native handler for NexVigilant Station.
//!
//! Routes `tov_nexvigilant_com_*` tool calls to `nexcore-tov`.
//! 3 tools: signal_strength, stability_shell, epistemic_trust.

use nexcore_pv_core::SafetyMargin;
use nexcore_tov::{
    Bits, ComplexityChi, QuantityUnit, RecognitionR, SignalStrengthS, StabilityShell, TemporalT,
    UniquenessU,
};
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("tov_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "compute-signal-strength" => handle_signal_strength(args),
        "check-stability-shell" => handle_stability_shell(args),
        "score-epistemic-trust" => handle_epistemic_trust(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (tov)");

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
    let mut obj = v;
    if let Some(map) = obj.as_object_mut() {
        map.insert("status".into(), json!("ok"));
    }
    obj
}

fn err(msg: &str) -> Value {
    json!({ "status": "error", "error": msg })
}

fn get_f64(args: &Value, key: &str) -> Option<f64> {
    args.get(key).and_then(|v| v.as_f64())
}

fn handle_signal_strength(args: &Value) -> Value {
    let uniqueness_bits = match get_f64(args, "uniqueness_bits") {
        Some(v) => v,
        None => return err("missing required parameter: uniqueness_bits"),
    };
    let recognition = match get_f64(args, "recognition") {
        Some(v) => v,
        None => return err("missing required parameter: recognition"),
    };
    let temporal = match get_f64(args, "temporal") {
        Some(v) => v,
        None => return err("missing required parameter: temporal"),
    };

    let u = UniquenessU(Bits(uniqueness_bits));
    let r = RecognitionR(recognition.clamp(0.0, 1.0));
    let t = TemporalT(temporal.clamp(0.0, 1.0));
    let s = SignalStrengthS::calculate(u, r, t);

    ok(json!({
        "signal_strength_bits": s.0.0,
        "components": {
            "uniqueness_U": uniqueness_bits,
            "recognition_R": r.0,
            "temporal_T": t.0,
        },
        "equation": "S = U * R * T",
        "interpretation": if s.0.0 > 5.0 {
            "Strong signal — high uniqueness, recognition, and recency"
        } else if s.0.0 > 2.0 {
            "Moderate signal — warrants investigation"
        } else if s.0.0 > 0.5 {
            "Weak signal — monitor but low priority"
        } else {
            "Negligible signal — no action needed"
        },
    }))
}

fn handle_stability_shell(args: &Value) -> Value {
    let complexity = match get_f64(args, "complexity") {
        Some(v) => v as u64,
        None => return err("missing required parameter: complexity"),
    };

    let chi = ComplexityChi(QuantityUnit(complexity));
    let is_stable = chi.is_closed_shell();
    let distance = chi.distance_to_stability();

    ok(json!({
        "complexity": complexity,
        "is_closed_shell": is_stable,
        "distance_to_stability": distance,
        "magic_numbers": [2, 8, 20, 28, 50, 82, 126, 184, 258, 350],
        "interpretation": if is_stable {
            "At a magic number — system is at a stability point"
        } else if distance <= 2 {
            "Near a magic number — close to stability"
        } else if distance <= 5 {
            "Moderate distance from stability — consider refactoring"
        } else {
            "Far from stability — structural risk"
        },
    }))
}

fn handle_epistemic_trust(args: &Value) -> Value {
    let levels: Vec<u8> = match args.get("levels_covered").and_then(|v| v.as_array()) {
        Some(arr) => arr
            .iter()
            .filter_map(|v| v.as_u64().map(|n| n as u8))
            .collect(),
        None => return err("missing required parameter: levels_covered (array of level numbers 1-8)"),
    };
    let sources = args
        .get("sources")
        .and_then(|v| v.as_u64())
        .unwrap_or(1) as usize;

    let score = SafetyMargin::score_epistemic_trust(&levels, sources);

    ok(json!({
        "epistemic_trust": (score * 1000.0).round() / 1000.0,
        "levels_covered": levels,
        "level_count": levels.len(),
        "total_levels": 8,
        "coverage_ratio": (levels.len() as f64 / 8.0 * 100.0).round() / 100.0,
        "sources": sources,
        "interpretation": if score > 0.8 {
            "High epistemic trust — comprehensive evidence across hierarchy"
        } else if score > 0.5 {
            "Moderate epistemic trust — reasonable coverage"
        } else if score > 0.2 {
            "Low epistemic trust — limited evidence coverage"
        } else {
            "Very low epistemic trust — insufficient evidence"
        },
    }))
}
