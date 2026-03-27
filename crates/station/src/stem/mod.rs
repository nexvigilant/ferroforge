//! STEM — Rust-native handler for NexVigilant Station.
//!
//! Routes `stem_nexvigilant_com_*` tool calls to stem-math, stem-phys,
//! stem-complex, stem-number-theory, stem-topology.

use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("stem_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        // Complex numbers
        "complex-arithmetic" => handle_complex_arithmetic(args),
        "complex-polar" => handle_complex_polar(args),
        // Number theory
        "factorize" => handle_factorize(args),
        "euler-totient" => handle_euler_totient(args),
        "prime-test" => handle_prime_test(args),
        // Topology
        "persistence-point" => handle_persistence_point(args),
        "betti-numbers" => handle_betti_numbers(args),
        // Physics
        "conservation-check" => handle_physics_conservation(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (stem)");

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

fn get_f64(args: &Value, key: &str) -> Option<f64> {
    args.get(key).and_then(|v| v.as_f64())
}

fn get_u64(args: &Value, key: &str) -> Option<u64> {
    args.get(key).and_then(|v| v.as_u64())
}

// ── Complex Numbers (stem-complex) ──────────────────────────────────────

fn handle_complex_arithmetic(args: &Value) -> Value {
    let ar = get_f64(args, "a_real").unwrap_or(0.0);
    let ai = get_f64(args, "a_imag").unwrap_or(0.0);
    let br = get_f64(args, "b_real").unwrap_or(0.0);
    let bi = get_f64(args, "b_imag").unwrap_or(0.0);

    let a = stem_complex::Complex::from((ar, ai));
    let b = stem_complex::Complex::from((br, bi));

    let sum = a + b;
    let diff = a - b;
    let prod = a * b;
    let quot = a.div(b);

    ok(json!({
        "a": { "re": ar, "im": ai },
        "b": { "re": br, "im": bi },
        "sum": { "re": sum.re, "im": sum.im },
        "difference": { "re": diff.re, "im": diff.im },
        "product": { "re": prod.re, "im": prod.im },
        "quotient": match quot {
            Ok(q) => json!({ "re": q.re, "im": q.im }),
            Err(_) => json!("division by zero"),
        },
        "a_magnitude": a.abs(),
        "a_argument": a.arg(),
    }))
}

fn handle_complex_polar(args: &Value) -> Value {
    let r = match get_f64(args, "r") {
        Some(v) => v,
        None => return err("missing required parameter: r"),
    };
    let theta = match get_f64(args, "theta") {
        Some(v) => v,
        None => return err("missing required parameter: theta"),
    };

    let z = stem_complex::Complex::polar(r, theta);

    ok(json!({
        "polar": { "r": r, "theta": theta },
        "rectangular": { "re": z.re, "im": z.im },
        "magnitude": z.abs(),
        "argument": z.arg(),
    }))
}

// ── Number Theory (stem-number-theory) ──────────────────────────────────

fn handle_factorize(args: &Value) -> Value {
    let n = match get_u64(args, "n") {
        Some(v) if v >= 2 => v,
        Some(_) => return err("n must be >= 2"),
        None => return err("missing required parameter: n"),
    };

    let factors = stem_number_theory::factorize::factorize(n);
    let factor_list: Vec<Value> = factors
        .iter()
        .map(|(p, e)| json!({ "prime": p, "exponent": e }))
        .collect();

    ok(json!({
        "n": n,
        "factors": factor_list,
        "is_prime": factors.len() == 1 && factors[0].1 == 1,
        "factorization": factors.iter().map(|(p, e)| {
            if *e == 1 { format!("{p}") } else { format!("{p}^{e}") }
        }).collect::<Vec<_>>().join(" × "),
    }))
}

fn handle_euler_totient(args: &Value) -> Value {
    let n = match get_u64(args, "n") {
        Some(v) if v >= 1 => v,
        Some(_) => return err("n must be >= 1"),
        None => return err("missing required parameter: n"),
    };

    let phi = stem_number_theory::arithmetic::euler_totient(n);
    let mu = stem_number_theory::arithmetic::mobius_mu(n);
    let lambda = stem_number_theory::arithmetic::liouville_lambda(n);

    ok(json!({
        "n": n,
        "euler_totient": phi,
        "mobius_mu": mu,
        "liouville_lambda": lambda,
        "totient_ratio": phi as f64 / n as f64,
    }))
}

fn handle_prime_test(args: &Value) -> Value {
    let n = match get_u64(args, "n") {
        Some(v) if v >= 2 => v,
        Some(_) => return err("n must be >= 2"),
        None => return err("missing required parameter: n"),
    };

    let factors = stem_number_theory::factorize::factorize(n);
    let is_prime = factors.len() == 1 && factors[0].1 == 1;
    let omega = stem_number_theory::arithmetic::omega(n);
    let big_omega = stem_number_theory::arithmetic::big_omega(n);

    ok(json!({
        "n": n,
        "is_prime": is_prime,
        "distinct_prime_factors": omega,
        "total_prime_factors": big_omega,
    }))
}

// ── Topology (stem-topology) ────────────────────────────────────────────

fn handle_persistence_point(args: &Value) -> Value {
    let birth = match get_f64(args, "birth") {
        Some(v) => v,
        None => return err("missing required parameter: birth"),
    };
    let death = match get_f64(args, "death") {
        Some(v) => v,
        None => return err("missing required parameter: death"),
    };
    let dimension = get_u64(args, "dimension").unwrap_or(0) as usize;
    let max_filtration = get_f64(args, "max_filtration").unwrap_or(death * 1.5);

    let pt = stem_topology::diagram::PersistencePoint::new(birth, death, dimension);

    ok(json!({
        "birth": birth,
        "death": death,
        "dimension": dimension,
        "persistence": pt.persistence(),
        "persistence_ratio": pt.persistence_ratio(max_filtration),
        "is_infinite": pt.is_infinite(),
        "is_stable": pt.is_stable(0.1, 0.1, max_filtration),
    }))
}

fn handle_betti_numbers(args: &Value) -> Value {
    let points = match args.get("points").and_then(|v| v.as_array()) {
        Some(arr) => arr,
        None => return err("missing required parameter: points (array of {birth, death, dimension})"),
    };
    let at_filtration = get_f64(args, "at_filtration").unwrap_or(1.0);

    let mut diagram = stem_topology::diagram::PersistenceDiagram::new();
    for p in points {
        let b = p.get("birth").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let d = p.get("death").and_then(|v| v.as_f64()).unwrap_or(f64::INFINITY);
        let dim = p.get("dimension").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
        diagram.add_point(stem_topology::diagram::PersistencePoint::new(b, d, dim));
    }

    let betti = stem_topology::betti::betti_numbers(&diagram, at_filtration);

    ok(json!({
        "at_filtration": at_filtration,
        "betti_0": betti.at_dim(0),
        "betti_1": betti.at_dim(1),
        "betti_2": betti.at_dim(2),
        "total_points": points.len(),
    }))
}

// ── Physics (stem-phys) ─────────────────────────────────────────────────

fn handle_physics_conservation(args: &Value) -> Value {
    let initial = match get_f64(args, "initial") {
        Some(v) => v,
        None => return err("missing required parameter: initial"),
    };
    let final_val = match get_f64(args, "final") {
        Some(v) => v,
        None => return err("missing required parameter: final"),
    };
    let tolerance = get_f64(args, "tolerance").unwrap_or(1e-10);

    let diff = (initial - final_val).abs();
    let conserved = diff <= tolerance;

    ok(json!({
        "initial": initial,
        "final": final_val,
        "tolerance": tolerance,
        "conserved": conserved,
        "difference": diff,
        "interpretation": if conserved { "Energy conserved within tolerance" } else { "Conservation violated" },
    }))
}
