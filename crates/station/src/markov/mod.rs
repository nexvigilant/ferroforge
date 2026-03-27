//! Markov — Rust-native handler for NexVigilant Station.
//! Routes `markov_nexvigilant_com_*` to `stem-math::markov`.

use stem_math::markov::MarkovChain;
use serde_json::{Value, json};
use tracing::info;
use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("markov_nexvigilant_com_")?.replace('_', "-");
    let result = match bare.as_str() {
        "analyze" => handle_analyze(args),
        "from-data" => handle_from_data(args),
        _ => return None,
    };
    info!(tool = tool_name, "Handled natively (markov)");
    Some(ToolCallResult {
        content: vec![ContentBlock::Text { text: serde_json::to_string_pretty(&result).unwrap_or_default() }],
        is_error: if result.get("status").and_then(|s| s.as_str()) == Some("error") { Some(true) } else { None },
    })
}

fn ok(v: Value) -> Value { let mut o = v; if let Some(m) = o.as_object_mut() { m.insert("status".into(), json!("ok")); } o }
fn err(msg: &str) -> Value { json!({ "status": "error", "error": msg }) }
fn r6(v: f64) -> f64 { (v * 1_000_000.0).round() / 1_000_000.0 }

fn parse_transitions(args: &Value) -> Option<Vec<(usize, usize, f64)>> {
    args.get("transitions").and_then(|v| v.as_array()).map(|arr| {
        arr.iter().filter_map(|t| {
            let from = t.get("from").and_then(|v| v.as_u64())? as usize;
            let to = t.get("to").and_then(|v| v.as_u64())? as usize;
            let p = t.get("probability").and_then(|v| v.as_f64())?;
            Some((from, to, p))
        }).collect()
    })
}

fn parse_states(args: &Value) -> Option<Vec<String>> {
    args.get("states").and_then(|v| v.as_array()).map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect())
}

fn build_chain(states: Vec<String>, transitions: &[(usize, usize, f64)]) -> Result<MarkovChain<String>, String> {
    let n = states.len();
    for &(from, to, _) in transitions {
        if from >= n || to >= n { return Err(format!("transition ({from},{to}) exceeds state count {n}")); }
    }
    MarkovChain::from_transitions(states, transitions).ok_or_else(|| "failed to build chain".to_string())
}

fn handle_analyze(args: &Value) -> Value {
    let states = match parse_states(args) { Some(s) if !s.is_empty() => s, _ => return err("missing: states") };
    let trans = match parse_transitions(args) { Some(t) => t, None => return err("missing: transitions") };
    let mode = args.get("analysis").and_then(|v| v.as_str()).unwrap_or("summary").to_lowercase();

    let mc = match build_chain(states, &trans) { Ok(c) => c, Err(e) => return err(&e) };

    match mode.as_str() {
        "summary" => {
            let s = mc.summary();
            let pi: Vec<_> = mc.states().iter().zip(s.stationary_distribution.iter())
                .map(|(st, &p)| json!({"state": st, "probability": r6(p)})).collect();
            ok(json!({ "analysis": "summary", "state_count": s.state_count, "is_ergodic": s.is_ergodic,
                "stationary_distribution": pi, "entropy_rate": r6(s.entropy_rate) }))
        }
        "stationary" => {
            let pi = mc.stationary_distribution(1000, 1e-10);
            let data: Vec<_> = mc.states().iter().zip(pi.value.iter())
                .map(|(st, &p)| json!({"state": st, "probability": r6(p)})).collect();
            ok(json!({ "analysis": "stationary", "distribution": data, "confidence": r6(pi.confidence.value()) }))
        }
        "n-step" => {
            let from = args.get("from_state").and_then(|v| v.as_u64()).map(|v| v as usize);
            let to = args.get("to_state").and_then(|v| v.as_u64()).map(|v| v as usize);
            let steps = args.get("steps").and_then(|v| v.as_u64()).unwrap_or(1) as u32;
            let (f, t) = match (from, to) { (Some(f), Some(t)) => (f, t), _ => return err("n_step requires from_state and to_state") };
            match mc.n_step_probability(f, t, steps) {
                Some(p) => ok(json!({ "analysis": "n_step", "from": mc.state(f), "to": mc.state(t), "steps": steps, "probability": r6(p) })),
                None => err("invalid state indices"),
            }
        }
        "ergodicity" => {
            ok(json!({ "analysis": "ergodicity", "is_ergodic": mc.is_ergodic(), "is_irreducible": mc.is_irreducible(), "is_aperiodic": mc.is_aperiodic() }))
        }
        "entropy" => {
            let h = mc.entropy_rate();
            let max_h = (mc.state_count() as f64).log2();
            ok(json!({ "analysis": "entropy", "entropy_rate": r6(h.value), "max_entropy": r6(max_h),
                "normalized": r6(if max_h > 0.0 { h.value / max_h } else { 0.0 }) }))
        }
        "mfpt" => {
            let from = args.get("from_state").and_then(|v| v.as_u64()).map(|v| v as usize);
            let to = args.get("to_state").and_then(|v| v.as_u64()).map(|v| v as usize);
            let (f, t) = match (from, to) { (Some(f), Some(t)) => (f, t), _ => return err("mfpt requires from_state and to_state") };
            match mc.mean_first_passage_time(f, t, 10000) {
                Some(time) => ok(json!({ "analysis": "mfpt", "from": mc.state(f), "to": mc.state(t), "mean_steps": r6(time) })),
                None => ok(json!({ "analysis": "mfpt", "from": mc.state(f), "to": mc.state(t), "mean_steps": null, "unreachable": true })),
            }
        }
        "classify" => {
            let data: Vec<_> = mc.classify_states().iter().map(|&(idx, class)| {
                json!({ "state": mc.state(idx), "index": idx, "class": format!("{class:?}") })
            }).collect();
            ok(json!({ "analysis": "classify", "classifications": data }))
        }
        "classes" => {
            let cls: Vec<_> = mc.communicating_classes().iter().enumerate().map(|(i, c)| {
                let labels: Vec<_> = c.states.iter().filter_map(|&idx| mc.state(idx).cloned()).collect();
                json!({ "class": i, "type": format!("{:?}", c.class_type), "size": c.states.len(), "states": labels })
            }).collect();
            ok(json!({ "analysis": "classes", "class_count": cls.len(), "classes": cls }))
        }
        other => err(&format!("unknown analysis '{other}'. Use: summary, stationary, n_step, classify, classes, ergodicity, entropy, mfpt")),
    }
}

fn handle_from_data(args: &Value) -> Value {
    let states = match parse_states(args) { Some(s) if !s.is_empty() => s, _ => return err("missing: states") };
    let sequences: Vec<Vec<usize>> = match args.get("sequences").and_then(|v| v.as_array()) {
        Some(arr) => arr.iter().map(|seq| {
            seq.as_array().map(|a| a.iter().filter_map(|v| v.as_u64().map(|n| n as usize)).collect()).unwrap_or_default()
        }).collect(),
        None => return err("missing: sequences"),
    };
    if sequences.is_empty() { return err("no sequences provided"); }

    let n = states.len();
    for (si, seq) in sequences.iter().enumerate() {
        for &idx in seq {
            if idx >= n { return err(&format!("sequence {si} has index {idx} >= state count {n}")); }
        }
    }

    let mc = match MarkovChain::from_observed_data(states, &sequences) {
        Some(c) => c,
        None => return err("failed to estimate chain from data"),
    };
    let s = mc.summary();
    let pi: Vec<_> = mc.states().iter().zip(s.stationary_distribution.iter())
        .map(|(st, &p)| json!({"state": st, "probability": r6(p)})).collect();

    let total_trans: usize = sequences.iter().map(|s| s.len().saturating_sub(1)).sum();

    ok(json!({ "analysis": "from_data", "state_count": mc.state_count(), "sequences_analyzed": sequences.len(),
        "total_transitions": total_trans, "is_ergodic": s.is_ergodic, "stationary_distribution": pi, "entropy_rate": r6(s.entropy_rate) }))
}
