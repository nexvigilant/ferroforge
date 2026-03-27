//! Molecular Weight — Rust-native handler for NexVigilant Station.
//!
//! Routes `molecular-weight_nexvigilant_com_*` tool calls to `nexcore-lex-primitiva`.

use nexcore_lex_primitiva::molecular_weight::{
    AtomicMass, MolecularFormula, max_atomic_mass, max_molecular_weight, min_atomic_mass,
    shannon_entropy,
};
use nexcore_lex_primitiva::primitiva::LexPrimitiva;
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("molecular-weight_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "compute" => handle_compute(args),
        "periodic-table" => handle_periodic_table(),
        "compare" => handle_compare(args),
        "predict-transfer" => handle_predict_transfer(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (molecular-weight)");

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

fn round3(v: f64) -> f64 {
    (v * 1000.0).round() / 1000.0
}

fn parse_primitive(input: &str) -> Option<LexPrimitiva> {
    LexPrimitiva::all()
        .iter()
        .find(|p| p.symbol() == input || p.name().eq_ignore_ascii_case(input))
        .copied()
}

fn parse_primitive_list(args: &Value, key: &str) -> Option<Vec<LexPrimitiva>> {
    let arr = args.get(key).and_then(|v| v.as_array())?;
    let prims: Vec<_> = arr
        .iter()
        .filter_map(|v| v.as_str().and_then(|s| parse_primitive(s.trim())))
        .collect();
    if prims.is_empty() { None } else { Some(prims) }
}

fn handle_compute(args: &Value) -> Value {
    let primitives = match parse_primitive_list(args, "primitives") {
        Some(p) => p,
        None => return err("missing or empty 'primitives' array — use names (e.g., 'state') or symbols (e.g., 'ς')"),
    };
    let name = args.get("name").and_then(|v| v.as_str()).unwrap_or("unnamed");

    let mut formula = MolecularFormula::new(name);
    for p in &primitives {
        formula = formula.with(*p);
    }
    let weight = formula.weight();

    let masses: Vec<_> = formula
        .atomic_masses()
        .iter()
        .map(|m| json!({
            "primitive": m.primitive().name(), "symbol": m.primitive().symbol(),
            "mass_bits": round3(m.bits()), "frequency": m.frequency(),
            "probability": round3(m.probability()),
        }))
        .collect();

    ok(json!({
        "concept": name, "formula": formula.formula_string(),
        "molecular_weight_daltons": round3(weight.daltons()),
        "primitive_count": weight.primitive_count(),
        "average_mass": round3(weight.average_mass()),
        "transfer_class": format!("{}", weight.transfer_class()),
        "predicted_transfer_confidence": round3(weight.predicted_transfer()),
        "tier_prediction": format!("{}", weight.tier_aware_class()),
        "hybrid_transfer_confidence": round3(weight.predicted_transfer_hybrid()),
        "constituents": masses,
    }))
}

fn handle_periodic_table() -> Value {
    let table: Vec<_> = AtomicMass::periodic_table()
        .iter()
        .enumerate()
        .map(|(i, m)| json!({
            "rank": i + 1,
            "primitive": m.primitive().name(), "symbol": m.primitive().symbol(),
            "mass_bits": round3(m.bits()), "frequency": m.frequency(),
            "probability": round3(m.probability()),
        }))
        .collect();

    ok(json!({
        "total_primitives": 16, "shannon_entropy_bits": round3(shannon_entropy()),
        "lightest_atom": {
            "primitive": min_atomic_mass().primitive().name(),
            "mass_bits": round3(min_atomic_mass().bits()),
        },
        "heaviest_atom": {
            "primitive": max_atomic_mass().primitive().name(),
            "mass_bits": round3(max_atomic_mass().bits()),
        },
        "max_molecular_weight": round3(max_molecular_weight().daltons()),
        "periodic_table": table,
    }))
}

fn handle_compare(args: &Value) -> Value {
    let prims_a = match parse_primitive_list(args, "primitives_a") {
        Some(p) => p,
        None => return err("missing or empty 'primitives_a'"),
    };
    let prims_b = match parse_primitive_list(args, "primitives_b") {
        Some(p) => p,
        None => return err("missing or empty 'primitives_b'"),
    };
    let name_a = args.get("name_a").and_then(|v| v.as_str()).unwrap_or("concept_a");
    let name_b = args.get("name_b").and_then(|v| v.as_str()).unwrap_or("concept_b");

    let formula_a = MolecularFormula::new(name_a).with_all(&prims_a);
    let formula_b = MolecularFormula::new(name_b).with_all(&prims_b);
    let wa = formula_a.weight();
    let wb = formula_b.weight();

    let set_a: std::collections::HashSet<_> = prims_a.iter().collect();
    let set_b: std::collections::HashSet<_> = prims_b.iter().collect();
    let shared: Vec<_> = set_a.intersection(&set_b).map(|p| p.name()).collect();
    let only_a: Vec<_> = set_a.difference(&set_b).map(|p| p.name()).collect();
    let only_b: Vec<_> = set_b.difference(&set_a).map(|p| p.name()).collect();
    let jaccard = if set_a.is_empty() && set_b.is_empty() {
        0.0
    } else {
        shared.len() as f64 / set_a.union(&set_b).count() as f64
    };

    ok(json!({
        "concept_a": {
            "name": name_a, "formula": formula_a.formula_string(),
            "molecular_weight": round3(wa.daltons()),
            "transfer_class": format!("{}", wa.transfer_class()),
        },
        "concept_b": {
            "name": name_b, "formula": formula_b.formula_string(),
            "molecular_weight": round3(wb.daltons()),
            "transfer_class": format!("{}", wb.transfer_class()),
        },
        "comparison": {
            "weight_delta": round3((wa.daltons() - wb.daltons()).abs()),
            "heavier": if wa.daltons() > wb.daltons() { name_a } else { name_b },
            "shared_primitives": shared, "only_in_a": only_a, "only_in_b": only_b,
            "jaccard_similarity": round3(jaccard),
            "same_transfer_class": wa.transfer_class() == wb.transfer_class(),
        },
    }))
}

fn handle_predict_transfer(args: &Value) -> Value {
    let primitives = match parse_primitive_list(args, "primitives") {
        Some(p) => p,
        None => return err("missing or empty 'primitives' array"),
    };

    let weight = MolecularFormula::weight_of(&primitives);
    let transfer = weight.predicted_transfer();
    let hybrid = weight.predicted_transfer_hybrid();

    ok(json!({
        "molecular_weight": round3(weight.daltons()),
        "predicted_transfer_confidence": round3(transfer),
        "hybrid_transfer_confidence": round3(hybrid),
        "transfer_class": format!("{}", weight.transfer_class()),
        "tier_prediction": format!("{}", weight.tier_aware_class()),
        "primitive_count": weight.primitive_count(),
        "average_mass": round3(weight.average_mass()),
        "interpretation": format!("{:.1}% transfer (MW-only), {:.1}% transfer (hybrid tier-aware)", transfer * 100.0, hybrid * 100.0),
    }))
}
