//! Harm Taxonomy — 8-type classification from Theory of Vigilance §9.
//! Routes `harm-taxonomy_nexvigilant_com_*`. Delegates to `nexcore-harm-taxonomy`.

use nexcore_harm_taxonomy::{
    HarmTypeId, HarmTypeDefinition, HarmAxiomConnection, HarmTypeCombination,
    PerturbationMultiplicity, TemporalProfile, ResponseDeterminism,
    classify_harm_event, verify_exhaustiveness,
};
use serde_json::{Value, json};
use tracing::info;
use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("harm-taxonomy_nexvigilant_com_")?.replace('_', "-");
    let result = match bare.as_str() {
        "classify" => handle_classify(args),
        "catalog" => handle_catalog(),
        "axiom-connection" => handle_axiom_connection(args),
        "manifestation-levels" => handle_manifestation_levels(args),
        "combinations" => handle_combinations(),
        "verify-exhaustiveness" => handle_verify_exhaustiveness(),
        _ => return None,
    };
    info!(tool = tool_name, "Handled natively (harm-taxonomy)");
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

fn parse_harm_type(s: &str) -> Option<HarmTypeId> {
    match s.to_uppercase().as_str() {
        "A" => Some(HarmTypeId::A),
        "B" => Some(HarmTypeId::B),
        "C" => Some(HarmTypeId::C),
        "D" => Some(HarmTypeId::D),
        "E" => Some(HarmTypeId::E),
        "F" => Some(HarmTypeId::F),
        "G" => Some(HarmTypeId::G),
        "H" => Some(HarmTypeId::H),
        _ => None,
    }
}

fn handle_classify(args: &Value) -> Value {
    let mult = match args.get("multiplicity").and_then(|v| v.as_str()) {
        Some("single") => PerturbationMultiplicity::Single,
        Some("multiple") => PerturbationMultiplicity::Multiple,
        _ => return err("multiplicity must be 'single' or 'multiple'"),
    };
    let temp = match args.get("temporal").and_then(|v| v.as_str()) {
        Some("acute") => TemporalProfile::Acute,
        Some("chronic") => TemporalProfile::Chronic,
        _ => return err("temporal must be 'acute' or 'chronic'"),
    };
    let det = match args.get("determinism").and_then(|v| v.as_str()) {
        Some("deterministic") => ResponseDeterminism::Deterministic,
        Some("stochastic") => ResponseDeterminism::Stochastic,
        _ => return err("determinism must be 'deterministic' or 'stochastic'"),
    };

    let result = classify_harm_event(mult, temp, det);
    let def = HarmTypeDefinition::from_id(result.primary_type);
    let axiom = HarmAxiomConnection::for_type(result.primary_type);
    let levels = def.manifestation_level.levels();

    ok(json!({
        "harm_type": result.primary_type.name(),
        "name": def.name,
        "confidence": result.confidence,
        "definition": def.definition,
        "mechanism": def.mechanism,
        "conservation_connection": def.conservation_connection,
        "intervention_strategy": def.intervention_strategy,
        "primary_axiom": axiom.primary_axiom.name(),
        "axiom_connection": axiom.connection,
        "manifestation_levels": levels,
        "reasoning": result.reasoning,
        "secondary_types": result.secondary_types.iter().map(|t| t.name()).collect::<Vec<_>>(),
        "recommended_interventions": result.recommended_interventions,
        "reference": "Theory of Vigilance §9"
    }))
}

fn handle_catalog() -> Value {
    let types: Vec<Value> = HarmTypeDefinition::catalog()
        .into_iter()
        .map(|def| {
            let axiom = HarmAxiomConnection::for_type(def.id);
            json!({
                "letter": def.id.name(),
                "name": def.name,
                "definition": def.definition,
                "mechanism": def.mechanism,
                "conservation_connection": def.conservation_connection,
                "primary_axiom": axiom.primary_axiom.name(),
                "manifestation_levels": def.manifestation_level.levels(),
                "notes": def.notes,
            })
        })
        .collect();
    let count = types.len();

    ok(json!({
        "types": types,
        "total": count,
        "source": "Theory of Vigilance §9 — 2³ = 8 harm types from three binary characteristics"
    }))
}

fn handle_axiom_connection(args: &Value) -> Value {
    let ht = match args.get("harm_type").and_then(|v| v.as_str()).and_then(parse_harm_type) {
        Some(h) => h,
        None => return err("harm_type must be A through H"),
    };
    let conn = HarmAxiomConnection::for_type(ht);

    ok(json!({
        "harm_type": ht.name(),
        "primary_axiom": conn.primary_axiom.name(),
        "connection": conn.connection,
        "reference": "Theory of Vigilance §9.2"
    }))
}

fn handle_manifestation_levels(args: &Value) -> Value {
    let ht = match args.get("harm_type").and_then(|v| v.as_str()).and_then(parse_harm_type) {
        Some(h) => h,
        None => return err("harm_type must be A through H"),
    };
    let def = HarmTypeDefinition::from_id(ht);

    ok(json!({
        "harm_type": ht.name(),
        "min_level": def.manifestation_level.min_level,
        "max_level": def.manifestation_level.max_level,
        "levels": def.manifestation_level.levels(),
        "reference": "Theory of Vigilance §9.1.1"
    }))
}

fn handle_combinations() -> Value {
    let combos: Vec<Value> = HarmTypeCombination::common_combinations()
        .into_iter()
        .map(|c| {
            json!({
                "primary": c.primary.name(),
                "secondary": c.secondary.name(),
                "name": c.name,
                "description": c.description,
            })
        })
        .collect();
    let count = combos.len();

    ok(json!({
        "combinations": combos,
        "total": count,
    }))
}

fn handle_verify_exhaustiveness() -> Value {
    let result = verify_exhaustiveness();

    ok(json!({
        "exhaustive": result.is_exhaustive,
        "total_combinations": result.total_types,
        "covered": result.defined_types,
        "coverage": result.coverage,
        "proof": "2³ = 8 combinations of (multiplicity × temporal × determinism). All 8 covered by types A-H.",
        "reference": "Theory of Vigilance §9.0 Proposition 9.0.1"
    }))
}
