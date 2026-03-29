//! Helix Computing — Conservation Law as Computable Geometry.
//! Routes `helix_nexvigilant_com_*`. Delegates to `nexcore-helix` crate.
//!
//! By Matthew A. Campion, PharmD.

use nexcore_helix::{
    ConservationInput, Turn,
    conservation, derivatives, helix_position, mutualism_test,
    can_advance, binding_laws, vice_risk,
    dna::Codon,
};
use serde_json::{Value, json};
use tracing::info;
use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("helix_nexvigilant_com_")?.replace('_', "-");
    let result = match bare.as_str() {
        "conservation-check" => handle_conservation_check(args),
        "helix-position" => handle_helix_position(args),
        "mutualism-test" => handle_mutualism_test(args),
        "encode" => handle_encode(args),
        "advance" => handle_advance(args),
        _ => return None,
    };
    info!(tool = tool_name, "Handled natively (helix via nexcore-helix)");
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
    if let Some(m) = o.as_object_mut() {
        m.insert("status".into(), json!("ok"));
    }
    o
}
fn err(msg: &str) -> Value {
    json!({ "status": "error", "error": msg })
}
fn r4(v: f64) -> f64 {
    (v * 10000.0).round() / 10000.0
}
fn get_f64(a: &Value, k: &str) -> Option<f64> {
    a.get(k).and_then(|v| v.as_f64())
}
fn unit(v: f64) -> bool {
    (0.0..=1.0).contains(&v)
}

fn handle_conservation_check(args: &Value) -> Value {
    let b = match get_f64(args, "boundary") { Some(v) if unit(v) => v, _ => return err("boundary must be in [0,1]") };
    let s = match get_f64(args, "state") { Some(v) if unit(v) => v, _ => return err("state must be in [0,1]") };
    let v = match get_f64(args, "void") { Some(v) if unit(v) => v, _ => return err("void must be in [0,1]") };

    let input = ConservationInput { boundary: b, state: s, void: v };
    let result = conservation(input);
    let d = derivatives(input);
    let codon = Codon::encode(input);

    ok(json!({
        "existence": r4(result.existence),
        "boundary": b, "state": s, "void": v,
        "weakest_primitive": result.weakest.symbol(),
        "classification": result.classification.label(),
        "formula": "∃ = ∂(×(ς, ∅))",
        "d_existence_d_boundary": r4(d.d_boundary),
        "d_existence_d_state": r4(d.d_state),
        "d_existence_d_void": r4(d.d_void),
        "highest_leverage": d.highest_leverage.symbol(),
        "vice_risk": vice_risk(result.weakest),
        "binding_laws": binding_laws(result.weakest),
        "codon": codon.as_str(),
        "is_stop_codon": codon.is_stop(),
    }))
}

fn handle_helix_position(args: &Value) -> Value {
    let turn_idx = match args.get("turn").and_then(|v| v.as_u64()) {
        Some(t) if t <= 4 => t as usize,
        _ => return err("turn must be 0-4"),
    };
    let turn = match Turn::from_index(turn_idx) {
        Some(t) => t,
        None => return err("invalid turn"),
    };
    let theta = get_f64(args, "theta").unwrap_or(0.0);
    let pos = helix_position(turn, theta);

    ok(json!({
        "turn": turn_idx,
        "turn_name": turn.name(),
        "what": turn.what(),
        "encoding": turn.encoding(),
        "altitude": r4(pos.z),
        "theta": r4(pos.theta),
        "x": r4(pos.x), "y": r4(pos.y), "z": r4(pos.z),
        "helix_properties": {
            "advances": "→ — moves to higher resolution with each turn",
            "returns": "κ — same angular truth revisited at each altitude",
            "bounds": "∂ — radius separates inside from outside"
        }
    }))
}

fn handle_mutualism_test(args: &Value) -> Value {
    let sb = match get_f64(args, "existence_self_before") { Some(v) if unit(v) => v, _ => return err("existence_self_before must be in [0,1]") };
    let sa = match get_f64(args, "existence_self_after") { Some(v) if unit(v) => v, _ => return err("existence_self_after must be in [0,1]") };
    let ob = match get_f64(args, "existence_other_before") { Some(v) if unit(v) => v, _ => return err("existence_other_before must be in [0,1]") };
    let oa = match get_f64(args, "existence_other_after") { Some(v) if unit(v) => v, _ => return err("existence_other_after must be in [0,1]") };

    let result = mutualism_test(sb, sa, ob, oa);

    ok(json!({
        "mutualistic": result.mutualistic,
        "delta_self": r4(result.delta_self),
        "delta_other": r4(result.delta_other),
        "net_existence": r4(result.net_existence),
        "classification": result.classification.label(),
        "conservation_holds": result.conservation_holds,
    }))
}

fn handle_encode(args: &Value) -> Value {
    let concept = match args.get("concept").and_then(|v| v.as_str()) {
        Some(c) => c.to_string(),
        None => return err("missing: concept"),
    };
    let primitives: Vec<String> = match args.get("primitives").and_then(|v| v.as_array()) {
        Some(arr) => arr.iter().filter_map(|v| v.as_str().map(String::from)).collect(),
        None => return err("missing: primitives"),
    };
    let b = match get_f64(args, "boundary") { Some(v) if unit(v) => v, _ => return err("boundary must be in [0,1]") };
    let s = match get_f64(args, "state") { Some(v) if unit(v) => v, _ => return err("state must be in [0,1]") };
    let v = match get_f64(args, "void") { Some(v) if unit(v) => v, _ => return err("void must be in [0,1]") };

    let input = ConservationInput { boundary: b, state: s, void: v };
    let result = conservation(input);
    let d = derivatives(input);
    let codon = Codon::encode(input);

    let balance = 1.0 - (s - v).abs();
    let mutualism_score = r4(b * balance * result.existence);

    let turns = vec![
        json!({ "turn": 0, "name": "Primitives", "encoding": format!("{} composed of {} T1 primitives: [{}]", concept, primitives.len(), primitives.join(", ")) }),
        json!({ "turn": 1, "name": "Conservation", "encoding": format!("∃={:.3} = ∂({:.2}) × ς({:.2}) × ∅({:.2})", result.existence, b, s, v) }),
        json!({ "turn": 2, "name": "Crystalbook", "encoding": format!("Governed by Laws {:?}. Vice risk: {}", binding_laws(result.weakest), vice_risk(result.weakest)) }),
        json!({ "turn": 3, "name": "Derivative Identity", "encoding": format!("∂∃/∂∂={}, ∂∃/∂ς={}, ∂∃/∂∅={}. Leverage: {}", r4(d.d_boundary), r4(d.d_state), r4(d.d_void), d.highest_leverage.symbol()) }),
        json!({ "turn": 4, "name": "Mutualism", "encoding": format!("Score: {:.3}. {}", mutualism_score, if mutualism_score >= 0.3 { "Serves shared existence." } else if mutualism_score >= 0.1 { "Partial mutualism." } else { "Low mutualism signal." }) }),
    ];

    ok(json!({
        "concept": concept,
        "turns": turns,
        "existence": r4(result.existence),
        "helix_complete": true,
        "mutualism_score": mutualism_score,
        "codon": codon.as_str(),
        "is_stop_codon": codon.is_stop(),
        "weakest": result.weakest.symbol(),
        "classification": result.classification.label(),
    }))
}

fn handle_advance(args: &Value) -> Value {
    let turn_idx = match args.get("current_turn").and_then(|v| v.as_u64()) {
        Some(t) if t <= 4 => t as usize,
        _ => return err("current_turn must be 0-4"),
    };
    let turn = match Turn::from_index(turn_idx) {
        Some(t) => t,
        None => return err("invalid turn"),
    };
    let existence = match get_f64(args, "current_existence") {
        Some(v) if unit(v) => v,
        _ => return err("current_existence must be in [0,1]"),
    };

    let next = match turn.next() {
        Some(n) => n,
        None => return err("Already at turn 4 (Mutualism). The helix is complete."),
    };

    let ready = can_advance(turn, existence);

    ok(json!({
        "from_turn": turn_idx,
        "to_turn": turn_idx + 1,
        "from_name": turn.name(),
        "to_name": next.name(),
        "can_advance": ready,
        "current_existence": r4(existence),
        "requirement": next.what(),
    }))
}
