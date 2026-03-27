//! Phenotype — Rust-native handler for NexVigilant Station.
//!
//! Routes `phenotype_nexvigilant_com_*` tool calls to `nexcore-phenotype`.
//! 2 tools: mutate (adversarial JSON generation), verify (drift detection).

use nexcore_phenotype::{Mutation, mutate, mutate_all, verify_with_threshold};
use nexcore_transcriptase::infer;
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("phenotype_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "mutate" => handle_mutate(args),
        "verify" => handle_verify(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (phenotype)");

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

fn handle_mutate(args: &Value) -> Value {
    let json_input = match get_str(args, "json_input") {
        Some(v) => v,
        None => return err("missing required parameter: json_input"),
    };
    let input: Value = match serde_json::from_str(json_input) {
        Ok(v) => v,
        Err(e) => return err(&format!("Invalid JSON: {e}")),
    };
    let mutation_name = get_str(args, "mutation");

    let schema = infer(&input);

    if let Some(m_name) = mutation_name {
        let mutation = match m_name.to_lowercase().as_str() {
            "type_mismatch" => Mutation::TypeMismatch,
            "add_field" => Mutation::AddField,
            "remove_field" => Mutation::RemoveField,
            "range_expand" => Mutation::RangeExpand,
            "length_change" => Mutation::LengthChange,
            "array_resize" => Mutation::ArrayResize,
            "structure_swap" => Mutation::StructureSwap,
            _ => return err(&format!("Unknown mutation: {m_name}. Valid: type_mismatch, add_field, remove_field, range_expand, length_change, array_resize, structure_swap")),
        };
        let phenotype = mutate(&schema, mutation);
        ok(json!({
            "mutation": m_name,
            "original": input,
            "mutated": phenotype.data,
            "mutations_applied": phenotype.mutations_applied.iter().map(|m| m.to_string()).collect::<Vec<_>>(),
            "expected_drifts": phenotype.expected_drifts,
        }))
    } else {
        let all = mutate_all(&schema);
        let mutations: Vec<Value> = all
            .iter()
            .map(|p| {
                json!({
                    "mutations_applied": p.mutations_applied.iter().map(|m| m.to_string()).collect::<Vec<_>>(),
                    "mutated": p.data,
                    "expected_drifts": p.expected_drifts,
                })
            })
            .collect();
        ok(json!({
            "original": input,
            "mutation_count": mutations.len(),
            "mutations": mutations,
        }))
    }
}

fn handle_verify(args: &Value) -> Value {
    let json_input = match get_str(args, "json_input") {
        Some(v) => v,
        None => return err("missing required parameter: json_input"),
    };
    let input: Value = match serde_json::from_str(json_input) {
        Ok(v) => v,
        Err(e) => return err(&format!("Invalid JSON: {e}")),
    };
    let threshold = args.get("threshold").and_then(|v| v.as_f64()).unwrap_or(0.5);

    let schema = infer(&input);
    let all = mutate_all(&schema);
    let results: Vec<Value> = all
        .iter()
        .map(|p| {
            let passed = verify_with_threshold(&schema, p, threshold).unwrap_or(false);
            json!({
                "mutations": p.mutations_applied.iter().map(|m| m.to_string()).collect::<Vec<_>>(),
                "passed": passed,
            })
        })
        .collect();
    let all_passed = results.iter().all(|r| r["passed"].as_bool().unwrap_or(false));

    ok(json!({
        "threshold": threshold,
        "total_mutations": results.len(),
        "all_passed": all_passed,
        "results": results,
    }))
}
