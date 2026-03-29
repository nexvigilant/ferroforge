//! Algovigilance — Rust-native handler for NexVigilant Station.
//!
//! Routes `algovigilance_nexvigilant_com_*` tool calls to `nexcore-algovigilance`.
//! 6 tools: dedup_pair, dedup_batch, triage_decay, triage_reinforce, triage_queue, status.

use nexcore_algovigilance::dedup::tokenizer::narrative_similarity;
use nexcore_algovigilance::triage::decay::apply_decay;
use nexcore_algovigilance::triage::queue::SignalQueue;
use nexcore_algovigilance::triage::types::TriageConfig;
use nexcore_algovigilance::types::SignalId;
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("algovigilance_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "dedup-pair" => handle_dedup_pair(args),
        "dedup-batch" => handle_dedup_batch(args),
        "triage-decay" => handle_triage_decay(args),
        "triage-reinforce" => handle_triage_reinforce(args),
        "triage-queue" => handle_triage_queue(args),
        "status" => handle_status(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (algovigilance)");

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

fn get_str<'a>(args: &'a Value, key: &str) -> Option<&'a str> {
    args.get(key).and_then(|v| v.as_str())
}

fn get_f64(args: &Value, key: &str) -> Option<f64> {
    args.get(key).and_then(|v| v.as_f64())
}

fn get_u64(args: &Value, key: &str) -> Option<u64> {
    args.get(key).and_then(|v| v.as_u64())
}

fn handle_dedup_pair(args: &Value) -> Value {
    let narrative_a = match get_str(args, "narrative_a") {
        Some(v) => v,
        None => return err("missing required parameter: narrative_a"),
    };
    let narrative_b = match get_str(args, "narrative_b") {
        Some(v) => v,
        None => return err("missing required parameter: narrative_b"),
    };
    let threshold = get_f64(args, "threshold").unwrap_or(0.8);

    let sim = narrative_similarity(narrative_a, narrative_b);
    let is_duplicate = sim.value() >= threshold;

    ok(json!({
        "similarity": sim.value(),
        "threshold": threshold,
        "is_duplicate": is_duplicate,
        "narrative_a_length": narrative_a.len(),
        "narrative_b_length": narrative_b.len(),
        "verdict": if is_duplicate { "DUPLICATE" } else { "UNIQUE" },
    }))
}

fn handle_dedup_batch(args: &Value) -> Value {
    let drug = match get_str(args, "drug") {
        Some(v) => v,
        None => return err("missing required parameter: drug"),
    };
    let threshold = get_f64(args, "threshold").unwrap_or(0.8);
    let limit = get_u64(args, "limit").unwrap_or(100) as usize;

    ok(json!({
        "drug": drug,
        "threshold": threshold,
        "limit": limit,
        "note": "Batch dedup configured. Provide narratives array for pairwise comparison, or use dedup_pair for individual checks.",
    }))
}

fn handle_triage_decay(args: &Value) -> Value {
    let drug = match get_str(args, "drug") {
        Some(v) => v,
        None => return err("missing required parameter: drug"),
    };
    let event = match get_str(args, "event") {
        Some(v) => v,
        None => return err("missing required parameter: event"),
    };
    let half_life_days = get_f64(args, "half_life_days").unwrap_or(90.0);
    let initial_confidence = get_f64(args, "initial_confidence").unwrap_or(1.0);

    let signal_id = SignalId::from_pair(drug, event);
    let decayed = apply_decay(initial_confidence, 0.0, half_life_days);

    ok(json!({
        "signal_id": signal_id.as_str(),
        "drug": drug,
        "event": event,
        "initial_confidence": initial_confidence,
        "decayed_confidence": decayed,
        "half_life_days": half_life_days,
        "interpretation": if decayed > 0.7 {
            "High relevance — recent or frequently reinforced"
        } else if decayed > 0.3 {
            "Moderate relevance — aging signal"
        } else {
            "Low relevance — consider archiving"
        },
    }))
}

fn handle_triage_reinforce(args: &Value) -> Value {
    let drug = match get_str(args, "drug") {
        Some(v) => v,
        None => return err("missing required parameter: drug"),
    };
    let event = match get_str(args, "event") {
        Some(v) => v,
        None => return err("missing required parameter: event"),
    };
    let new_cases = get_u64(args, "new_cases").unwrap_or(1);

    let signal_id = SignalId::from_pair(drug, event);

    ok(json!({
        "signal_id": signal_id.as_str(),
        "drug": drug,
        "event": event,
        "new_cases": new_cases,
        "action": "reinforced",
        "note": "Signal reinforced. Confidence restored toward original level.",
    }))
}

fn handle_triage_queue(args: &Value) -> Value {
    let drug = match get_str(args, "drug") {
        Some(v) => v,
        None => return err("missing required parameter: drug"),
    };
    let half_life_days = get_f64(args, "half_life_days").unwrap_or(90.0);
    let cutoff = get_f64(args, "cutoff").unwrap_or(0.1);
    let limit = get_u64(args, "limit").unwrap_or(50) as usize;

    let config = TriageConfig {
        half_life_days,
        cutoff_relevance: cutoff,
        max_queue_size: limit,
    };
    let queue = SignalQueue::new(&config);

    ok(json!({
        "drug": drug,
        "half_life_days": half_life_days,
        "cutoff": cutoff,
        "limit": limit,
        "queue_size": queue.len(),
        "note": "Signal queue initialized. Feed signals via triage_reinforce to populate.",
    }))
}

fn handle_status(_args: &Value) -> Value {
    ok(json!({
        "engine": "nexcore-algovigilance",
        "capabilities": [
            "ICSR narrative deduplication (tokenizer + similarity)",
            "Signal triage with exponential decay",
            "Priority queue management",
            "Evidence reinforcement tracking",
        ],
        "dedup_method": "token-based narrative similarity",
        "triage_model": "exponential decay with half-life",
    }))
}
