//! Entropy — Rust-native handler for NexVigilant Station.
//!
//! Routes `entropy_nexvigilant_com_*` tool calls to `nexcore-primitives::entropy`.

use nexcore_primitives::entropy::{self, LogBase};
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("entropy_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "compute" => handle_compute(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (entropy)");

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

fn parse_base(s: &str) -> Option<LogBase> {
    match s.to_lowercase().as_str() {
        "bits" | "bit" | "log2" => Some(LogBase::Bits),
        "nats" | "nat" | "ln" | "natural" => Some(LogBase::Nats),
        "hartleys" | "hartley" | "bans" | "log10" => Some(LogBase::Hartleys),
        _ => None,
    }
}

fn round6(v: f64) -> f64 {
    (v * 1_000_000.0).round() / 1_000_000.0
}

fn build_joint(flat: &[f64], rows: usize) -> Option<Vec<Vec<f64>>> {
    if rows == 0 || flat.len() % rows != 0 { return None; }
    let cols = flat.len() / rows;
    Some(flat.chunks(cols).map(|c| c.to_vec()).collect())
}

fn handle_compute(args: &Value) -> Value {
    let mode = match args.get("mode").and_then(|v| v.as_str()) {
        Some(m) => m.to_lowercase(),
        None => return err("missing required parameter: mode (shannon, cross, kl, mutual, normalized, conditional)"),
    };
    let dist_p: Vec<f64> = match args.get("distribution_p").and_then(|v| v.as_array()) {
        Some(arr) => arr.iter().filter_map(|v| v.as_f64()).collect(),
        None => return err("missing required parameter: distribution_p"),
    };
    let base = parse_base(args.get("base").and_then(|v| v.as_str()).unwrap_or("bits"))
        .unwrap_or(LogBase::Bits);
    let from_counts = args.get("from_counts").and_then(|v| v.as_bool()).unwrap_or(false);

    match mode.as_str() {
        "shannon" => {
            if from_counts {
                let counts: Vec<u64> = dist_p.iter().map(|&v| v as u64).collect();
                match entropy::shannon_entropy_measured_with_base(&counts, base) {
                    Ok(m) => ok(json!({
                        "value": round6(m.value.bits), "normalized": round6(m.value.normalized),
                        "sample_count": m.value.sample_count,
                        "confidence": round6(m.confidence.value()),
                        "base": base.unit_name(),
                    })),
                    Err(e) => err(&e.to_string()),
                }
            } else {
                match entropy::shannon_entropy_with_base(&dist_p, base) {
                    Ok(r) => ok(json!({
                        "value": round6(r.bits), "normalized": round6(r.normalized),
                        "sample_count": r.sample_count, "base": base.unit_name(),
                    })),
                    Err(e) => err(&e.to_string()),
                }
            }
        }
        "cross" => {
            let dist_q: Vec<f64> = match args.get("distribution_q").and_then(|v| v.as_array()) {
                Some(arr) => arr.iter().filter_map(|v| v.as_f64()).collect(),
                None => return err("cross-entropy requires distribution_q"),
            };
            match entropy::cross_entropy(&dist_p, &dist_q, base) {
                Ok(ce) => ok(json!({ "value": round6(ce), "base": base.unit_name() })),
                Err(e) => err(&e.to_string()),
            }
        }
        "kl" => {
            let dist_q: Vec<f64> = match args.get("distribution_q").and_then(|v| v.as_array()) {
                Some(arr) => arr.iter().filter_map(|v| v.as_f64()).collect(),
                None => return err("KL divergence requires distribution_q"),
            };
            match entropy::kl_divergence_with_base(&dist_p, &dist_q, base) {
                Ok(kl) => ok(json!({ "value": round6(kl), "base": base.unit_name() })),
                Err(e) => err(&e.to_string()),
            }
        }
        "mutual" => {
            let rows = match args.get("joint_rows").and_then(|v| v.as_u64()) {
                Some(r) => r as usize,
                None => return err("mutual information requires joint_rows"),
            };
            let joint = match build_joint(&dist_p, rows) {
                Some(j) => j,
                None => return err("distribution_p not divisible by joint_rows"),
            };
            match entropy::mutual_information_with_base(&joint, base) {
                Ok(mi) => ok(json!({ "value": round6(mi), "base": base.unit_name() })),
                Err(e) => err(&e.to_string()),
            }
        }
        "normalized" => {
            let dist = if from_counts {
                let sum: f64 = dist_p.iter().sum();
                if sum <= 0.0 { return err("from_counts requires non-zero counts"); }
                dist_p.iter().map(|&c| c / sum).collect()
            } else {
                dist_p
            };
            match entropy::normalized_entropy(&dist, base) {
                Ok(n) => ok(json!({ "value": round6(n), "range": "[0, 1]" })),
                Err(e) => err(&e.to_string()),
            }
        }
        "conditional" => {
            let rows = match args.get("joint_rows").and_then(|v| v.as_u64()) {
                Some(r) => r as usize,
                None => return err("conditional entropy requires joint_rows"),
            };
            let joint = match build_joint(&dist_p, rows) {
                Some(j) => j,
                None => return err("distribution_p not divisible by joint_rows"),
            };
            match entropy::conditional_entropy(&joint, base) {
                Ok(h) => ok(json!({ "value": round6(h), "base": base.unit_name() })),
                Err(e) => err(&e.to_string()),
            }
        }
        other => err(&format!("unknown mode '{other}'. Use: shannon, cross, kl, mutual, normalized, conditional")),
    }
}
