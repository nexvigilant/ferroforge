//! Edit Distance — Rust-native handler for NexVigilant Station.
//!
//! Routes `edit_distance_nexvigilant_com_*` tool calls to `nexcore-edit-distance`.

use nexcore_edit_distance::prelude::*;
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("edit_distance_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "compute" => handle_compute(args),
        "similarity" => handle_similarity(args),
        "traceback" => handle_traceback(args),
        "batch" => handle_batch(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (edit_distance)");

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

fn round6(v: f64) -> f64 {
    (v * 1_000_000.0).round() / 1_000_000.0
}

fn compute_distance(source: &str, target: &str, algorithm: &str) -> Result<f64, String> {
    match algorithm {
        "levenshtein" | "lev" => Ok(levenshtein(source, target)),
        "damerau" | "damerau-levenshtein" | "dl" => Ok(damerau_levenshtein(source, target)),
        "lcs" | "indel" => Ok(lcs_distance(source, target)),
        other => Err(format!("Unknown algorithm: {other}. Use: levenshtein, damerau, lcs")),
    }
}

fn similarity_from_distance(distance: f64, src_len: usize, tgt_len: usize) -> f64 {
    let max_len = src_len.max(tgt_len);
    if max_len == 0 {
        1.0
    } else {
        1.0 - (distance / max_len as f64)
    }
}

// ---------------------------------------------------------------------------
// Tool handlers
// ---------------------------------------------------------------------------

fn handle_compute(args: &Value) -> Value {
    let source = match args.get("source").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing required parameter: source"),
    };
    let target = match args.get("target").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing required parameter: target"),
    };
    let algorithm = args
        .get("algorithm")
        .and_then(|v| v.as_str())
        .unwrap_or("levenshtein");

    let distance = match compute_distance(source, target, algorithm) {
        Ok(d) => d,
        Err(e) => return err(&e),
    };

    let src_len = source.chars().count();
    let tgt_len = target.chars().count();
    let sim = similarity_from_distance(distance, src_len, tgt_len);

    ok(json!({
        "distance": distance,
        "similarity": round6(sim),
        "algorithm": algorithm,
        "source_len": src_len,
        "target_len": tgt_len,
    }))
}

fn handle_similarity(args: &Value) -> Value {
    let source = match args.get("source").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing required parameter: source"),
    };
    let target = match args.get("target").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing required parameter: target"),
    };
    let threshold = args
        .get("threshold")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.8);

    let distance = levenshtein(source, target);
    let src_len = source.chars().count();
    let tgt_len = target.chars().count();
    let sim = similarity_from_distance(distance, src_len, tgt_len);

    ok(json!({
        "similarity": round6(sim),
        "threshold": threshold,
        "passes": sim >= threshold,
        "distance": distance,
    }))
}

fn handle_traceback(args: &Value) -> Value {
    let source = match args.get("source").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing required parameter: source"),
    };
    let target = match args.get("target").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing required parameter: target"),
    };

    let metric = LevenshteinTraceback::default();
    let distance = metric.str_distance(source, target);
    let ops = metric.operations(&source.chars().collect::<Vec<_>>(), &target.chars().collect::<Vec<_>>());

    let ops_json: Vec<Value> = ops
        .unwrap_or_default()
        .iter()
        .map(|op| json!(format!("{op:?}")))
        .collect();

    ok(json!({
        "distance": distance,
        "operations": ops_json,
        "source": source,
        "target": target,
    }))
}

fn handle_batch(args: &Value) -> Value {
    let query = match args.get("query").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing required parameter: query"),
    };
    let candidates: Vec<&str> = match args.get("candidates").and_then(|v| v.as_array()) {
        Some(arr) => arr.iter().filter_map(|v| v.as_str()).collect(),
        None => return err("missing required parameter: candidates"),
    };
    let limit = args.get("limit").and_then(|v| v.as_u64()).map(|n| n as usize);
    let min_similarity = args
        .get("min_similarity")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);
    let algorithm = args
        .get("algorithm")
        .and_then(|v| v.as_str())
        .unwrap_or("levenshtein");

    let query_len = query.chars().count();
    let total = candidates.len();

    let mut matches: Vec<Value> = candidates
        .iter()
        .filter_map(|&candidate| {
            let distance = compute_distance(query, candidate, algorithm).ok()?;
            let cand_len = candidate.chars().count();
            let sim = similarity_from_distance(distance, query_len, cand_len);
            if sim >= min_similarity {
                Some(json!({
                    "candidate": candidate,
                    "distance": distance,
                    "similarity": round6(sim),
                }))
            } else {
                None
            }
        })
        .collect();

    // Sort by similarity descending
    matches.sort_by(|a, b| {
        b.get("similarity")
            .and_then(|v| v.as_f64())
            .unwrap_or(0.0)
            .partial_cmp(
                &a.get("similarity")
                    .and_then(|v| v.as_f64())
                    .unwrap_or(0.0),
            )
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    if let Some(n) = limit {
        matches.truncate(n);
    }

    ok(json!({
        "matches": matches,
        "total_candidates": total,
        "query": query,
        "algorithm": algorithm,
    }))
}
