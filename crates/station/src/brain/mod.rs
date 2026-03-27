//! Brain — Rust-native handler for NexVigilant Station.
//! Routes `brain_nexvigilant_com_*` to `nexcore-brain`.

use nexcore_brain::implicit::ImplicitKnowledge;
use nexcore_brain::metrics::{BrainHealth, BrainSnapshot, GrowthRate};
use nexcore_brain::session::BrainSession;
use serde_json::{Value, json};
use tracing::info;
use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("brain_nexvigilant_com_")?.replace('_', "-");
    let result = match bare.as_str() {
        "session-list" => handle_session_list(args),
        "session-load" => handle_session_load(args),
        "implicit-get" => handle_implicit_get(args),
        "implicit-stats" => handle_implicit_stats(),
        "patterns-by-relevance" => handle_patterns_by_relevance(),
        "find-corrections" => handle_find_corrections(),
        "belief-list" => handle_belief_list(),
        "belief-get" => handle_belief_get(args),
        "trust-global" => handle_trust_global(),
        "health" => handle_health(),
        "summary" => handle_summary(),
        "growth-rate" => handle_growth_rate(),
        "artifact-get" => handle_artifact_get(args),
        "artifact-diff" => handle_artifact_diff(),
        _ => return None,
    };
    info!(tool = tool_name, "Handled natively (brain)");
    Some(ToolCallResult {
        content: vec![ContentBlock::Text { text: serde_json::to_string_pretty(&result).unwrap_or_default() }],
        is_error: if result.get("status").and_then(|s| s.as_str()) == Some("error") { Some(true) } else { None },
    })
}

fn ok(v: Value) -> Value { let mut o = v; if let Some(m) = o.as_object_mut() { m.insert("status".into(), json!("ok")); } o }
fn err(msg: &str) -> Value { json!({ "status": "error", "error": msg }) }

fn load_implicit() -> Result<ImplicitKnowledge, String> {
    ImplicitKnowledge::load().map_err(|e| format!("{e}"))
}

fn handle_session_list(args: &Value) -> Value {
    let limit = args.get("limit").and_then(|v| v.as_u64()).unwrap_or(20) as usize;
    match BrainSession::list_all() {
        Ok(entries) => {
            let data: Vec<Value> = entries.iter().take(limit).map(|e| json!({
                "id": e.id, "description": e.description, "created_at": e.created_at.to_rfc3339(),
            })).collect();
            ok(json!({ "session_count": data.len(), "sessions": data }))
        }
        Err(e) => err(&format!("{e}")),
    }
}

fn handle_session_load(args: &Value) -> Value {
    let id = match args.get("session_id").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing: session_id"),
    };
    match BrainSession::load_str(id) {
        Ok(session) => ok(json!({
            "id": session.id, "dir": session.dir().to_string_lossy(),
            "created_at": session.created_at.to_rfc3339(),
        })),
        Err(e) => err(&format!("{e}")),
    }
}

fn handle_artifact_get(args: &Value) -> Value {
    let name = match args.get("name").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing: name"),
    };
    let session = match args.get("session_id").and_then(|v| v.as_str()) {
        Some(id) => BrainSession::load_str(id),
        None => BrainSession::load_latest(),
    };
    match session {
        Ok(s) => {
            let path = s.dir().join(format!("{name}.md"));
            if path.exists() {
                match std::fs::read_to_string(&path) {
                    Ok(content) => ok(json!({
                        "name": name, "content_length": content.len(),
                        "content_preview": &content[..content.len().min(500)],
                    })),
                    Err(e) => err(&format!("read error: {e}")),
                }
            } else {
                err(&format!("artifact '{name}' not found in session"))
            }
        }
        Err(e) => err(&format!("{e}")),
    }
}

fn handle_artifact_diff() -> Value {
    err("artifact-diff requires version context; use brain_artifact_diff via nexcore MCP")
}

fn handle_implicit_get(args: &Value) -> Value {
    let store = match args.get("store").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing: store (patterns, corrections, beliefs, trust)"),
    };
    let ik = match load_implicit() { Ok(ik) => ik, Err(e) => return err(&e) };

    match store {
        "patterns" => {
            let patterns = ik.list_patterns();
            let data: Vec<Value> = patterns.iter().map(|p| json!({
                "description": p.description, "pattern_type": p.pattern_type,
                "confidence": p.effective_confidence(), "examples": p.examples.len(),
            })).collect();
            ok(json!({ "count": data.len(), "patterns": data }))
        }
        "corrections" => {
            let corrections = ik.list_corrections();
            let data: Vec<Value> = corrections.iter().map(|c| json!({
                "mistake": c.mistake, "correction": c.correction,
                "confidence": c.effective_confidence(), "active": c.is_active(),
            })).collect();
            ok(json!({ "count": data.len(), "corrections": data }))
        }
        "beliefs" => {
            let beliefs = ik.list_beliefs();
            let data: Vec<Value> = beliefs.iter().map(|b| json!({
                "id": b.id, "proposition": b.proposition, "category": b.category,
                "confidence": b.effective_confidence(),
            })).collect();
            ok(json!({ "count": data.len(), "beliefs": data }))
        }
        "trust" => {
            let trust = ik.list_trust();
            let data: Vec<Value> = trust.iter().map(|t| json!({
                "domain": t.domain, "trusted": t.is_trusted(0.5),
            })).collect();
            ok(json!({ "count": data.len(), "trust": data }))
        }
        other => err(&format!("unknown store '{other}'")),
    }
}

fn handle_implicit_stats() -> Value {
    match load_implicit() {
        Ok(ik) => ok(json!({
            "pattern_count": ik.list_patterns().len(),
            "correction_count": ik.list_corrections().len(),
            "belief_count": ik.list_beliefs().len(),
            "trust_count": ik.list_trust().len(),
            "global_trust": ik.global_trust_score(),
        })),
        Err(e) => err(&e),
    }
}

fn handle_patterns_by_relevance() -> Value {
    match load_implicit() {
        Ok(ik) => {
            let ranked = ik.list_patterns_by_relevance();
            let data: Vec<Value> = ranked.iter().take(20).map(|(p, score)| json!({
                "description": p.description, "relevance": score, "type": p.pattern_type,
            })).collect();
            ok(json!({ "count": data.len(), "patterns": data }))
        }
        Err(e) => err(&e),
    }
}

fn handle_find_corrections() -> Value {
    match load_implicit() {
        Ok(ik) => {
            let active: Vec<Value> = ik.list_corrections().iter()
                .filter(|c| c.is_active())
                .map(|c| json!({
                    "mistake": c.mistake, "correction": c.correction,
                    "confidence": c.effective_confidence(),
                })).collect();
            ok(json!({ "active_count": active.len(), "corrections": active }))
        }
        Err(e) => err(&e),
    }
}

fn handle_belief_list() -> Value {
    match load_implicit() {
        Ok(ik) => {
            let data: Vec<Value> = ik.list_beliefs().iter().map(|b| json!({
                "id": b.id, "proposition": b.proposition, "confidence": b.effective_confidence(),
            })).collect();
            ok(json!({ "count": data.len(), "beliefs": data }))
        }
        Err(e) => err(&e),
    }
}

fn handle_belief_get(args: &Value) -> Value {
    let key = match args.get("key").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing: key"),
    };
    match load_implicit() {
        Ok(ik) => match ik.list_beliefs().iter().find(|b| b.id == key || b.proposition.contains(key)) {
            Some(b) => ok(json!({
                "id": b.id, "proposition": b.proposition, "category": b.category,
                "confidence": b.effective_confidence(), "evidence_count": b.evidence.len(),
            })),
            None => err(&format!("belief '{key}' not found")),
        },
        Err(e) => err(&e),
    }
}

fn handle_trust_global() -> Value {
    match load_implicit() {
        Ok(ik) => {
            let trust = ik.list_trust();
            let data: Vec<Value> = trust.iter().map(|t| json!({
                "domain": t.domain, "trusted": t.is_trusted(0.5),
            })).collect();
            ok(json!({ "global_score": ik.global_trust_score(), "domains": data }))
        }
        Err(e) => err(&e),
    }
}

fn handle_health() -> Value {
    match BrainHealth::collect() {
        Ok(h) => ok(serde_json::to_value(&h).unwrap_or(json!({"collected": true}))),
        Err(e) => err(&format!("{e}")),
    }
}

fn handle_summary() -> Value {
    match BrainSnapshot::collect() {
        Ok(s) => ok(serde_json::to_value(&s).unwrap_or(json!({"collected": true}))),
        Err(e) => err(&format!("{e}")),
    }
}

fn handle_growth_rate() -> Value {
    match GrowthRate::calculate(30) {
        Ok(g) => ok(serde_json::to_value(&g).unwrap_or(json!({"calculated": true}))),
        Err(e) => err(&format!("{e}")),
    }
}
