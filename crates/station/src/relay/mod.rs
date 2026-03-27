//! Relay — Rust-native handler for NexVigilant Station.
//! Routes `relay_nexvigilant_com_*` to `nexcore-primitives::relay`.

use nexcore_primitives::relay::{Fidelity, RelayChain, RelayHop};
use nexcore_signal_pipeline::relay as pipeline_relay;
use serde_json::{Value, json};
use tracing::info;
use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("relay_nexvigilant_com_")?.replace('_', "-");
    let result = match bare.as_str() {
        "chain-verify" => handle_chain_verify(args),
        "pv-pipeline" => handle_pv_pipeline(),
        "core-detection" => handle_core_detection(),
        "fidelity-compose" => handle_fidelity_compose(args),
        _ => return None,
    };
    info!(tool = tool_name, "Handled natively (relay)");
    Some(ToolCallResult {
        content: vec![ContentBlock::Text { text: serde_json::to_string_pretty(&result).unwrap_or_default() }],
        is_error: if result.get("status").and_then(|s| s.as_str()) == Some("error") { Some(true) } else { None },
    })
}

fn ok(v: Value) -> Value { let mut o = v; if let Some(m) = o.as_object_mut() { m.insert("status".into(), json!("ok")); } o }
fn err(msg: &str) -> Value { json!({ "status": "error", "error": msg }) }

fn chain_to_json(chain: &RelayChain) -> Value {
    let v = chain.verify();
    let hops: Vec<_> = chain.hops().iter().map(|h| json!({
        "stage": h.stage, "fidelity": h.fidelity.value(), "threshold": h.threshold, "activated": h.activated,
    })).collect();
    let weakest = chain.weakest_hop().map(|h| json!({"stage": h.stage, "fidelity": h.fidelity.value()}));

    json!({
        "total_fidelity": chain.total_fidelity().value(),
        "signal_loss_pct": chain.signal_loss() * 100.0,
        "active_hops": chain.active_hop_count(), "total_hops": chain.hop_count(),
        "axioms": {
            "a1_directionality": v.a1_directionality, "a2_mediation": v.a2_mediation,
            "a3_preservation": v.a3_preservation, "a4_threshold": v.a4_threshold,
            "a5_boundedness": v.a5_boundedness,
        },
        "axioms_passing": v.axioms_passing(), "is_valid": v.is_valid(),
        "weakest_hop": weakest, "hops": hops,
    })
}

fn handle_chain_verify(args: &Value) -> Value {
    let f_min = args.get("f_min").and_then(|v| v.as_f64()).unwrap_or(0.80);
    let hops = match args.get("hops").and_then(|v| v.as_array()) {
        Some(a) => a,
        None => return err("missing: hops array"),
    };

    let mut chain = RelayChain::new(f_min);
    for hop in hops {
        let stage = hop.get("stage").and_then(|v| v.as_str()).unwrap_or("unknown");
        let fidelity = hop.get("fidelity").and_then(|v| v.as_f64()).unwrap_or(1.0);
        let threshold = hop.get("threshold").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let activated = hop.get("activated").and_then(|v| v.as_bool()).unwrap_or(true);

        if activated {
            chain.add_hop(RelayHop::new(stage, Fidelity::new(fidelity), threshold));
        } else {
            chain.add_hop(RelayHop::inactive(stage, threshold));
        }
    }

    ok(chain_to_json(&chain))
}

fn handle_pv_pipeline() -> Value {
    let chain = pipeline_relay::pv_pipeline_chain();
    let mut result = chain_to_json(&chain);
    if let Some(map) = result.as_object_mut() {
        map.insert("pipeline".into(), json!("pv_signal_detection"));
        map.insert("description".into(), json!("Full 7-stage PV signal pipeline: ingest → normalize → detect → threshold → store → alert → report"));
        map.insert("passes_safety_critical".into(), json!(chain.verify_preservation()));
    }
    ok(result)
}

fn handle_core_detection() -> Value {
    let chain = pipeline_relay::core_detection_chain();
    let mut result = chain_to_json(&chain);
    if let Some(map) = result.as_object_mut() {
        map.insert("pipeline".into(), json!("core_detection"));
        map.insert("description".into(), json!("Core 4-stage: ingest → detect → threshold → alert"));
        map.insert("passes_safety_critical".into(), json!(chain.verify_preservation()));
    }
    ok(result)
}

fn handle_fidelity_compose(args: &Value) -> Value {
    let values: Vec<f64> = match args.get("values").and_then(|v| v.as_array()) {
        Some(a) => a.iter().filter_map(|v| v.as_f64()).collect(),
        None => return err("missing: values array"),
    };
    let mut composed = Fidelity::PERFECT;
    for &v in &values { composed = composed.compose(Fidelity::new(v)); }

    ok(json!({
        "input_values": values, "composed_fidelity": composed.value(),
        "signal_loss_pct": composed.loss() * 100.0, "hop_count": values.len(),
        "meets_safety_critical": composed.meets_minimum(0.80),
    }))
}
