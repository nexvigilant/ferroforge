//! Combinatorics — Rust-native handler for NexVigilant Station.
//! Routes `combinatorics_nexvigilant_com_*` to `nexcore-combinatorics`.

use nexcore_combinatorics;
use serde_json::{Value, json};
use tracing::info;
use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("combinatorics_nexvigilant_com_")?.replace('_', "-");
    let result = match bare.as_str() {
        "catalan" => handle_catalan(args),
        "catalan-table" => handle_catalan_table(),
        "cycle-decomposition" => handle_cycle_decomposition(args),
        "min-transpositions" => handle_min_transpositions(args),
        "derangement" => handle_derangement(args),
        "derangement-probability" => handle_derangement_probability(args),
        "grid-paths" => handle_grid_paths(args),
        "binomial" => handle_binomial(args),
        "multinomial" => handle_multinomial(args),
        "josephus" => handle_josephus(args),
        "elimination-order" => handle_elimination_order(args),
        "linear-extensions" => handle_linear_extensions(args),
        _ => return None,
    };
    info!(tool = tool_name, "Handled natively (combinatorics)");
    Some(ToolCallResult {
        content: vec![ContentBlock::Text { text: serde_json::to_string_pretty(&result).unwrap_or_default() }],
        is_error: if result.get("status").and_then(|s| s.as_str()) == Some("error") { Some(true) } else { None },
    })
}

fn ok(v: Value) -> Value { let mut o = v; if let Some(m) = o.as_object_mut() { m.insert("status".into(), json!("ok")); } o }
fn err(msg: &str) -> Value { json!({ "status": "error", "error": msg }) }
fn get_u32(args: &Value, k: &str) -> Option<u32> { args.get(k).and_then(|v| v.as_u64()).map(|v| v as u32) }
fn get_u32_arr(args: &Value, k: &str) -> Option<Vec<u32>> {
    args.get(k).and_then(|v| v.as_array()).map(|a| a.iter().filter_map(|v| v.as_u64().map(|n| n as u32)).collect())
}
fn get_usize_arr(args: &Value, k: &str) -> Option<Vec<usize>> {
    args.get(k).and_then(|v| v.as_array()).map(|a| a.iter().filter_map(|v| v.as_u64().map(|n| n as usize)).collect())
}

fn handle_catalan(args: &Value) -> Value {
    let n = match get_u32(args, "n") { Some(v) => v, None => return err("missing: n") };
    ok(json!({ "n": n, "catalan": nexcore_combinatorics::catalan::catalan(n).to_string() }))
}
fn handle_catalan_table() -> Value {
    let t = nexcore_combinatorics::catalan::catalan_table();
    let items: Vec<_> = t.iter().map(|&(n, c)| json!({"n": n, "catalan": c.to_string()})).collect();
    ok(json!({ "count": items.len(), "table": items }))
}
fn handle_cycle_decomposition(args: &Value) -> Value {
    let p = match get_usize_arr(args, "permutation") { Some(v) => v, None => return err("missing: permutation") };
    ok(serde_json::to_value(nexcore_combinatorics::cycle_decomposition(&p)).unwrap_or_default())
}
fn handle_min_transpositions(args: &Value) -> Value {
    let p = match get_usize_arr(args, "permutation") { Some(v) => v, None => return err("missing: permutation") };
    ok(json!({ "n": p.len(), "min_transpositions": nexcore_combinatorics::min_transpositions(&p) }))
}
fn handle_derangement(args: &Value) -> Value {
    let n = match get_u32(args, "n") { Some(v) => v, None => return err("missing: n") };
    ok(json!({ "n": n, "derangements": nexcore_combinatorics::derangement(n).to_string() }))
}
fn handle_derangement_probability(args: &Value) -> Value {
    let n = match get_u32(args, "n") { Some(v) => v, None => return err("missing: n") };
    let p = nexcore_combinatorics::derangement_probability(n);
    let inv_e = 1.0_f64 / std::f64::consts::E;
    ok(json!({ "n": n, "probability": p, "converges_to_1_over_e": inv_e, "deviation": (p - inv_e).abs() }))
}
fn handle_grid_paths(args: &Value) -> Value {
    let m = match get_u32(args, "m") { Some(v) => v, None => return err("missing: m") };
    let n = match get_u32(args, "n") { Some(v) => v, None => return err("missing: n") };
    ok(json!({ "m": m, "n": n, "paths": nexcore_combinatorics::grid_paths(m, n).to_string() }))
}
fn handle_binomial(args: &Value) -> Value {
    let n = match get_u32(args, "n") { Some(v) => v, None => return err("missing: n") };
    let k = match get_u32(args, "k") { Some(v) => v, None => return err("missing: k") };
    ok(json!({ "n": n, "k": k, "binomial": nexcore_combinatorics::grid_paths::binomial(n, k).to_string() }))
}
fn handle_multinomial(args: &Value) -> Value {
    let lengths = match get_u32_arr(args, "lengths") { Some(v) => v, None => return err("missing: lengths") };
    let total: u32 = lengths.iter().sum();
    ok(json!({ "lengths": lengths, "total_elements": total, "multinomial": nexcore_combinatorics::grid_paths::multinomial(&lengths).to_string() }))
}
fn handle_josephus(args: &Value) -> Value {
    let n = match get_u32(args, "n") { Some(v) => v, None => return err("missing: n") };
    let k = match get_u32(args, "k") { Some(v) => v, None => return err("missing: k") };
    ok(json!({ "n": n, "k": k, "survivor_position": nexcore_combinatorics::josephus(n, k) }))
}
fn handle_elimination_order(args: &Value) -> Value {
    let n = match get_u32(args, "n") { Some(v) => v, None => return err("missing: n") };
    let k = match get_u32(args, "k") { Some(v) => v, None => return err("missing: k") };
    let order = nexcore_combinatorics::josephus::elimination_order(n, k);
    ok(json!({ "n": n, "k": k, "elimination_order": order, "survivor": order.last() }))
}
fn handle_linear_extensions(args: &Value) -> Value {
    let cl = match get_u32_arr(args, "chain_lengths") { Some(v) => v, None => return err("missing: chain_lengths") };
    let total: u32 = cl.iter().sum();
    ok(json!({ "chain_lengths": cl, "total_nodes": total, "linear_extensions": nexcore_combinatorics::count_linear_extensions_chains(&cl).to_string() }))
}
