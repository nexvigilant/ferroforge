//! Stoichiometry — Rust-native handler for NexVigilant Station.
//!
//! Routes `stoichiometry_nexvigilant_com_*` tool calls to `nexcore-stoichiometry`.

use nexcore_lex_primitiva::primitiva::LexPrimitiva;
use nexcore_stoichiometry::balance::Balancer;
use nexcore_stoichiometry::prelude::*;
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("stoichiometry_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "encode" => handle_encode(args),
        "decode" => handle_decode(args),
        "sisters" => handle_sisters(args),
        "mass-state" => handle_mass_state(args),
        "dictionary" => handle_dictionary(args),
        "is-balanced" => handle_is_balanced(args),
        "prove" => handle_prove(args),
        "is-isomer" => handle_is_isomer(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (stoichiometry)");

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

fn parse_source(source: &str) -> DefinitionSource {
    let lower = source.to_lowercase();
    if lower.starts_with("ich") {
        DefinitionSource::IchGuideline(source.to_string())
    } else if lower.starts_with("cioms") {
        DefinitionSource::CiomsReport(source.to_string())
    } else if lower.starts_with("fda") {
        DefinitionSource::FdaGuidance(source.to_string())
    } else if lower.starts_with("who") {
        DefinitionSource::WhoDrug(source.to_string())
    } else if lower.starts_with("meddra") {
        DefinitionSource::MedDRA(source.to_string())
    } else {
        DefinitionSource::Custom(source.to_string())
    }
}

fn parse_primitive(name: &str) -> Option<LexPrimitiva> {
    match name.to_lowercase().as_str() {
        "causality" | "cause" | "→" => Some(LexPrimitiva::Causality),
        "quantity" | "n" => Some(LexPrimitiva::Quantity),
        "existence" | "∃" => Some(LexPrimitiva::Existence),
        "comparison" | "κ" => Some(LexPrimitiva::Comparison),
        "state" | "ς" => Some(LexPrimitiva::State),
        "mapping" | "μ" => Some(LexPrimitiva::Mapping),
        "sequence" | "σ" => Some(LexPrimitiva::Sequence),
        "recursion" | "ρ" => Some(LexPrimitiva::Recursion),
        "void" | "∅" => Some(LexPrimitiva::Void),
        "boundary" | "∂" => Some(LexPrimitiva::Boundary),
        "frequency" | "ν" => Some(LexPrimitiva::Frequency),
        "location" | "λ" => Some(LexPrimitiva::Location),
        "persistence" | "π" => Some(LexPrimitiva::Persistence),
        "irreversibility" | "∝" => Some(LexPrimitiva::Irreversibility),
        "sum" | "Σ" => Some(LexPrimitiva::Sum),
        "product" | "×" => Some(LexPrimitiva::Product),
        _ => None,
    }
}

fn handle_encode(args: &Value) -> Value {
    let concept = match get_str(args, "concept") {
        Some(s) => s,
        None => return err("missing required parameter: concept"),
    };
    let definition = match get_str(args, "definition") {
        Some(s) => s,
        None => return err("missing required parameter: definition"),
    };
    let source = parse_source(get_str(args, "source").unwrap_or("custom"));
    let mut codec = StoichiometricCodec::builtin();

    match codec.encode(concept, definition, source) {
        Ok(equation) => {
            let eq_json = serde_json::to_value(&equation).unwrap_or(json!(null));
            ok(json!({
                "concept": concept, "definition": definition,
                "equation": eq_json,
                "balanced": equation.balance.is_balanced,
                "delta": equation.balance.delta,
                "reactant_count": equation.reactants.len(),
                "display": format!("{equation}"),
            }))
        }
        Err(e) => err(&format!("{e}")),
    }
}

fn handle_decode(args: &Value) -> Value {
    let eq_json = match get_str(args, "equation_json") {
        Some(s) => s,
        None => return err("missing required parameter: equation_json"),
    };
    let equation: BalancedEquation = match serde_json::from_str(eq_json) {
        Ok(eq) => eq,
        Err(e) => return err(&format!("invalid equation JSON: {e}")),
    };
    let codec = StoichiometricCodec::builtin();
    match codec.decode(&equation) {
        Some(answer) => {
            let answer_json = serde_json::to_value(&answer).unwrap_or(json!(null));
            ok(json!({ "answer": answer_json, "display": format!("{answer}") }))
        }
        None => err("no matching concept found for the given equation"),
    }
}

fn handle_sisters(args: &Value) -> Value {
    let concept = match get_str(args, "concept") {
        Some(s) => s,
        None => return err("missing required parameter: concept"),
    };
    let threshold = get_f64(args, "threshold").unwrap_or(0.5);
    let codec = StoichiometricCodec::builtin();

    let term = match codec.dictionary().lookup(concept) {
        Some(t) => t.clone(),
        None => return err(&format!("concept '{concept}' not found in dictionary")),
    };

    let sisters = codec.find_sisters(&term.equation, threshold);
    let sisters_json: Vec<Value> = sisters
        .iter()
        .map(|s| serde_json::to_value(s).unwrap_or(json!({"name": s.name, "similarity": s.similarity})))
        .collect();

    ok(json!({
        "concept": concept, "threshold": threshold,
        "sister_count": sisters.len(), "sisters": sisters_json,
    }))
}

fn handle_mass_state(args: &Value) -> Value {
    let concept = match get_str(args, "concept") {
        Some(s) => s,
        None => return err("missing required parameter: concept"),
    };
    let codec = StoichiometricCodec::builtin();
    let term = match codec.dictionary().lookup(concept) {
        Some(t) => t.clone(),
        None => return err(&format!("concept '{concept}' not found in dictionary")),
    };

    let state = MassState::from_equation(&term.equation);
    let depleted: Vec<String> = state.depleted().iter().map(|p| format!("{p:?}")).collect();
    let saturated: Vec<String> = state.saturated().iter().map(|p| format!("{p:?}")).collect();

    ok(json!({
        "concept": concept,
        "total_mass": state.total_mass(), "entropy": state.entropy(),
        "max_entropy": MassState::max_entropy(),
        "entropy_ratio": if MassState::max_entropy() > 0.0 { state.entropy() / MassState::max_entropy() } else { 0.0 },
        "gibbs_free_energy": state.gibbs_free_energy(),
        "is_equilibrium": state.is_equilibrium(),
        "depleted_primitives": depleted, "depleted_count": state.depleted().len(),
        "saturated_primitives": saturated, "saturated_count": state.saturated().len(),
    }))
}

fn handle_dictionary(args: &Value) -> Value {
    let action = get_str(args, "action").unwrap_or("list");
    let codec = StoichiometricCodec::builtin();
    let dict = codec.dictionary();

    match action {
        "list" => {
            let terms: Vec<Value> = dict.all_terms().iter().map(|t| json!({
                "name": t.name, "definition": t.definition,
                "source": format!("{}", t.source),
                "balanced": t.equation.balance.is_balanced,
                "display": format!("{}", t.equation),
            })).collect();
            ok(json!({ "action": "list", "term_count": terms.len(), "terms": terms }))
        }
        "search" => {
            let filter = match get_str(args, "filter_primitive") {
                Some(s) if !s.is_empty() => s,
                _ => return err("filter_primitive is required when action is 'search'"),
            };
            let target = match parse_primitive(filter) {
                Some(p) => p,
                None => return err(&format!("unknown primitive '{filter}'")),
            };
            let terms: Vec<Value> = dict.all_terms().iter()
                .filter(|t| t.equation.concept.formula.primitives().contains(&target))
                .map(|t| json!({
                    "name": t.name, "definition": t.definition,
                    "primitive_count": t.equation.concept.formula.primitives().iter().filter(|p| **p == target).count(),
                    "display": format!("{}", t.equation),
                }))
                .collect();
            ok(json!({ "action": "search", "filter_primitive": filter, "match_count": terms.len(), "terms": terms }))
        }
        other => err(&format!("unknown action '{other}'. Use 'list' or 'search'")),
    }
}

fn handle_is_balanced(args: &Value) -> Value {
    let eq_json = match get_str(args, "equation_json") {
        Some(s) => s,
        None => return err("missing required parameter: equation_json"),
    };
    let equation: BalancedEquation = match serde_json::from_str(eq_json) {
        Ok(eq) => eq,
        Err(e) => return err(&format!("invalid equation JSON: {e}")),
    };
    let balanced = Balancer::is_balanced(&equation);
    let deficit = Balancer::deficit(&equation);

    ok(json!({
        "is_balanced": balanced, "deficit": deficit, "concept": equation.concept.name,
    }))
}

fn handle_prove(args: &Value) -> Value {
    let eq_json = match get_str(args, "equation_json") {
        Some(s) => s,
        None => return err("missing required parameter: equation_json"),
    };
    let equation: BalancedEquation = match serde_json::from_str(eq_json) {
        Ok(eq) => eq,
        Err(e) => return err(&format!("invalid equation JSON: {e}")),
    };
    let proof = Balancer::prove(&equation.reactants, &equation.concept);
    let proof_json = serde_json::to_value(&proof).unwrap_or(json!(null));

    ok(json!({
        "concept": equation.concept.name,
        "proof": proof_json,
        "is_balanced": proof.is_balanced, "delta": proof.delta,
        "reactant_mass": proof.reactant_mass, "product_mass": proof.product_mass,
    }))
}

fn handle_is_isomer(args: &Value) -> Value {
    let a_json = match get_str(args, "equation_a_json") {
        Some(s) => s,
        None => return err("missing required parameter: equation_a_json"),
    };
    let b_json = match get_str(args, "equation_b_json") {
        Some(s) => s,
        None => return err("missing required parameter: equation_b_json"),
    };
    let eq_a: BalancedEquation = match serde_json::from_str(a_json) {
        Ok(eq) => eq,
        Err(e) => return err(&format!("invalid equation A JSON: {e}")),
    };
    let eq_b: BalancedEquation = match serde_json::from_str(b_json) {
        Ok(eq) => eq,
        Err(e) => return err(&format!("invalid equation B JSON: {e}")),
    };

    let isomer = nexcore_stoichiometry::sister::is_isomer(&eq_a, &eq_b);
    let similarity = nexcore_stoichiometry::sister::jaccard_similarity(
        eq_a.concept.formula.primitives(),
        eq_b.concept.formula.primitives(),
    );

    ok(json!({
        "is_isomer": isomer,
        "concept_a": eq_a.concept.name, "concept_b": eq_b.concept.name,
        "jaccard_similarity": format!("{similarity:.3}"),
    }))
}
