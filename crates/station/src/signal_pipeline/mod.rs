//! Signal Pipeline — Rust-native handler for NexVigilant Station.
//!
//! Routes `signal-pipeline_nexvigilant_com_*` tool calls to `nexcore-signal-pipeline`.
//! 9 tools: compute_all, batch_compute, detect, validate, thresholds, report,
//! relay_chain, transfer, primitives.

use nexcore_signal_pipeline::prelude::*;
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("signal-pipeline_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "compute-all" => handle_compute_all(args),
        "detect" => handle_detect(args),
        "thresholds" => handle_thresholds(args),
        "primitives" => handle_primitives(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (signal-pipeline)");

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

fn get_u64(args: &Value, key: &str) -> Option<u64> {
    args.get(key).and_then(|v| v.as_u64())
}

fn handle_compute_all(args: &Value) -> Value {
    let a = match get_u64(args, "a") {
        Some(v) => v,
        None => return err("missing required parameter: a (drug+event count)"),
    };
    let b = match get_u64(args, "b") {
        Some(v) => v,
        None => return err("missing required parameter: b (drug+no-event count)"),
    };
    let c = match get_u64(args, "c") {
        Some(v) => v,
        None => return err("missing required parameter: c (no-drug+event count)"),
    };
    let d = match get_u64(args, "d") {
        Some(v) => v,
        None => return err("missing required parameter: d (no-drug+no-event count)"),
    };

    let table = ContingencyTable::new(a, b, c, d);
    let metrics = nexcore_signal_pipeline::stats::compute_all(&table);

    ok(json!({
        "table": { "a": a, "b": b, "c": c, "d": d, "total": table.total() },
        "metrics": {
            "prr": metrics.prr.as_ref().map(|p| p.0),
            "ror": metrics.ror.as_ref().map(|r| r.0),
            "ic": metrics.ic.0,
            "ebgm": metrics.ebgm.0,
            "chi_square": metrics.chi_square.0,
            "strength": format!("{:?}", metrics.strength),
        },
    }))
}

fn handle_detect(args: &Value) -> Value {
    let a = match get_u64(args, "a") {
        Some(v) => v,
        None => return err("missing required parameter: a"),
    };
    let b = match get_u64(args, "b") {
        Some(v) => v,
        None => return err("missing required parameter: b"),
    };
    let c = match get_u64(args, "c") {
        Some(v) => v,
        None => return err("missing required parameter: c"),
    };
    let d = match get_u64(args, "d") {
        Some(v) => v,
        None => return err("missing required parameter: d"),
    };

    let table = ContingencyTable::new(a, b, c, d);
    let metrics = nexcore_signal_pipeline::stats::compute_all(&table);
    let detected = metrics.prr.as_ref().map_or(false, |p| p.0 >= 2.0)
        || metrics.ror.as_ref().map_or(false, |r| r.0 >= 2.0);

    ok(json!({
        "detected": detected,
        "prr": metrics.prr.as_ref().map(|p| p.0),
        "ror": metrics.ror.as_ref().map(|r| r.0),
        "ic": metrics.ic.0,
        "ebgm": metrics.ebgm.0,
        "strength": format!("{:?}", metrics.strength),
        "verdict": if detected { "SIGNAL_DETECTED" } else { "NOT_DETECTED" },
    }))
}

fn handle_thresholds(_args: &Value) -> Value {
    ok(json!({
        "evans_thresholds": {
            "prr": { "signal": 2.0, "strong": 5.0 },
            "ror": { "signal": 2.0, "strong": 5.0 },
            "ic": { "signal": 0.0, "strong": 2.0 },
            "ebgm": { "signal": 2.0, "strong": 5.0 },
            "chi_square": { "signal": 4.0 },
        },
        "source": "Evans et al. signal detection thresholds",
    }))
}

fn handle_primitives(_args: &Value) -> Value {
    ok(json!({
        "pipeline_primitives": [
            { "symbol": "N", "name": "Quantity", "role": "Contingency table cell counts" },
            { "symbol": "κ", "name": "Comparison", "role": "Disproportionality ratios (PRR/ROR)" },
            { "symbol": "∂", "name": "Boundary", "role": "Signal detection thresholds" },
            { "symbol": "∃", "name": "Existence", "role": "Signal existence determination" },
            { "symbol": "→", "name": "Causality", "role": "Signal-to-action inference" },
        ],
    }))
}
