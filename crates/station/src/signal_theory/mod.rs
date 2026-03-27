//! Signal Theory — Rust-native handler for NexVigilant Station.
//!
//! Routes `signal-theory_nexvigilant_com_*` tool calls to `nexcore-signal-theory`.

use nexcore_signal_theory::prelude::*;
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

/// Try to handle a signal-theory tool call. Returns `None` to fall through.
pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("signal-theory_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "get-axioms" => handle_axioms(),
        "get-theorems" => handle_theorems(),
        "detect" => handle_detect(args),
        "decision-matrix" => handle_decision_matrix(args),
        "conservation-check" => handle_conservation_check(args),
        "pipeline" => handle_pipeline(args),
        "cascade" => handle_cascade(args),
        "parallel" => handle_parallel(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (signal-theory)");

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

fn handle_axioms() -> Value {
    let axiom_data: [(&str, &str, &str, &str); 6] = [
        ("A1", "Data Generation", "ν (Frequency)", <A1DataGeneration<1000> as Axiom>::statement()),
        ("A2", "Noise Dominance", "∅ (Void)", <A2NoiseDominance as Axiom>::statement()),
        ("A3", "Signal Existence", "∃ (Existence)", <A3SignalExistence as Axiom>::statement()),
        ("A4", "Boundary Requirement", "∂ (Boundary) [DOMINANT]", <A4BoundaryRequirement as Axiom>::statement()),
        ("A5", "Disproportionality", "κ (Comparison)", <A5Disproportionality as Axiom>::statement()),
        ("A6", "Causal Inference", "→ (Causality)", <A6CausalInference as Axiom>::statement()),
    ];

    let axioms: Vec<_> = axiom_data
        .iter()
        .map(|(id, name, prim, stmt)| json!({
            "id": id, "name": name, "primitive": prim, "statement": stmt,
        }))
        .collect();

    ok(json!({
        "crate": "nexcore-signal-theory",
        "thesis": "All detection is boundary drawing",
        "dominant_primitive": "∂ (Boundary)",
        "axiom_count": 6,
        "axioms": axioms,
    }))
}

fn handle_theorems() -> Value {
    let registry = TheoremRegistry::build();
    let theorems: Vec<_> = registry
        .theorems
        .iter()
        .map(|t| json!({
            "id": t.id, "name": t.name,
            "statement": t.statement, "prerequisites": t.prerequisites,
        }))
        .collect();

    ok(json!({ "theorem_count": theorems.len(), "theorems": theorems }))
}

fn get_f64(args: &Value, key: &str) -> Option<f64> {
    args.get(key).and_then(|v| v.as_f64())
}

fn get_u64(args: &Value, key: &str) -> Option<u64> {
    args.get(key).and_then(|v| v.as_u64())
}

fn handle_detect(args: &Value) -> Value {
    let observed = match get_f64(args, "observed") {
        Some(v) => v,
        None => return err("missing required parameter: observed"),
    };
    let expected = match get_f64(args, "expected") {
        Some(v) => v,
        None => return err("missing required parameter: expected"),
    };
    let threshold = get_f64(args, "threshold").unwrap_or(2.0);

    let boundary = FixedBoundary::above(threshold, "detection");
    let ratio = Ratio::from_counts(observed, expected);
    let (ratio_value, detected, strength) = match ratio {
        Some(r) => {
            let det = boundary.evaluate(r.0);
            let s = SignalStrengthLevel::from_ratio(r.0);
            (Some(r.0), det, s)
        }
        None => (None, false, SignalStrengthLevel::None),
    };
    let difference = Difference::from_counts(observed, expected);

    ok(json!({
        "observed": observed, "expected": expected, "threshold": threshold,
        "ratio": ratio_value, "difference": difference.0,
        "detected": detected, "strength": format!("{strength:?}"),
        "outcome": if detected { "Detected" } else { "NotDetected" },
    }))
}

fn handle_decision_matrix(args: &Value) -> Value {
    let hits = match get_u64(args, "hits") {
        Some(v) => v,
        None => return err("missing required parameter: hits"),
    };
    let misses = match get_u64(args, "misses") {
        Some(v) => v,
        None => return err("missing required parameter: misses"),
    };
    let false_alarms = match get_u64(args, "false_alarms") {
        Some(v) => v,
        None => return err("missing required parameter: false_alarms"),
    };
    let correct_rejections = match get_u64(args, "correct_rejections") {
        Some(v) => v,
        None => return err("missing required parameter: correct_rejections"),
    };

    let m = DecisionMatrix::new(hits, misses, false_alarms, correct_rejections);
    let dprime = DPrime::from_matrix(&m);
    let bias = ResponseBias::from_matrix(&m);

    ok(json!({
        "matrix": {
            "hits": m.hits, "misses": m.misses,
            "false_alarms": m.false_alarms, "correct_rejections": m.correct_rejections,
            "total": m.total(),
        },
        "metrics": {
            "sensitivity": m.sensitivity(), "specificity": m.specificity(),
            "ppv": m.ppv(), "npv": m.npv(), "accuracy": m.accuracy(),
            "fpr": m.false_positive_rate(), "fnr": m.false_negative_rate(),
            "prevalence": m.prevalence(), "f1_score": m.f1_score(), "mcc": m.mcc(),
        },
        "sdt": {
            "d_prime": dprime.0, "d_prime_level": dprime.level(),
            "response_bias": bias.0, "bias_description": bias.description(),
        },
        "signal_present": m.signal_present(), "signal_absent": m.signal_absent(),
    }))
}

fn handle_conservation_check(args: &Value) -> Value {
    let hits = match get_u64(args, "hits") {
        Some(v) => v,
        None => return err("missing required parameter: hits"),
    };
    let misses = match get_u64(args, "misses") {
        Some(v) => v,
        None => return err("missing required parameter: misses"),
    };
    let fa = match get_u64(args, "false_alarms") {
        Some(v) => v,
        None => return err("missing required parameter: false_alarms"),
    };
    let cr = match get_u64(args, "correct_rejections") {
        Some(v) => v,
        None => return err("missing required parameter: correct_rejections"),
    };

    let m = DecisionMatrix::new(hits, misses, fa, cr);
    let mut report = ConservationReport::new();

    let expected_total = get_u64(args, "expected_total").unwrap_or(hits + misses + fa + cr);
    let l1 = L1TotalCountConservation;
    report.add("L1", l1.verify(&m, expected_total));

    if let Some(max_dp) = get_f64(args, "max_dprime") {
        let l4 = L4InformationConservation;
        let observed_dp = DPrime::from_matrix(&m).0;
        report.add("L4", l4.verify(observed_dp, max_dp));
    }

    let violations: Vec<_> = report
        .violations()
        .iter()
        .map(|(id, msg)| json!({"law": id, "violation": msg}))
        .collect();

    ok(json!({
        "all_satisfied": report.all_satisfied(),
        "laws_checked": report.results.len(),
        "violations": violations,
        "conservation_laws": [
            {"id": "L1", "name": "Total Count Conservation"},
            {"id": "L2", "name": "Base Rate Invariance"},
            {"id": "L3", "name": "Sensitivity-Specificity Tradeoff"},
            {"id": "L4", "name": "Information Conservation"},
        ],
    }))
}

fn handle_pipeline(args: &Value) -> Value {
    let value = match get_f64(args, "value") {
        Some(v) => v,
        None => return err("missing required parameter: value"),
    };
    let label = args.get("label").and_then(|v| v.as_str()).unwrap_or("pipeline");
    let stages = match args.get("stages").and_then(|v| v.as_array()) {
        Some(s) => s,
        None => return err("missing required parameter: stages"),
    };

    let mut stages_result = Vec::new();
    let mut all_passed = true;
    let mut first_failure: Option<String> = None;

    for (i, stage) in stages.iter().enumerate() {
        let name = stage.get("name").and_then(|v| v.as_str()).unwrap_or("unnamed");
        let phase = stage.get("phase").and_then(|v| v.as_str()).unwrap_or("");
        let threshold = stage.get("threshold").and_then(|v| v.as_f64()).unwrap_or(0.0);

        let boundary = FixedBoundary::above(threshold, "detection");
        let passed = boundary.evaluate(value);

        if !passed && first_failure.is_none() {
            first_failure = Some(name.to_string());
            all_passed = false;
        }

        stages_result.push(json!({
            "stage": i + 1, "name": name, "phase": phase,
            "threshold": threshold, "value": value, "passed": passed,
        }));
    }

    ok(json!({
        "label": label, "value": value,
        "stage_count": stages.len(), "all_passed": all_passed,
        "first_failure": first_failure, "stages": stages_result,
        "verdict": if all_passed { "SIGNAL_DETECTED" } else { "NOT_DETECTED" },
    }))
}

fn handle_cascade(args: &Value) -> Value {
    let value = match get_f64(args, "value") {
        Some(v) => v,
        None => return err("missing required parameter: value"),
    };
    let thresholds: Vec<f64> = match args.get("thresholds").and_then(|v| v.as_array()) {
        Some(arr) => arr.iter().filter_map(|v| v.as_f64()).collect(),
        None => return err("missing required parameter: thresholds"),
    };
    let labels: Vec<String> = match args.get("labels").and_then(|v| v.as_array()) {
        Some(arr) => arr.iter().filter_map(|v| v.as_str().map(String::from)).collect(),
        None => return err("missing required parameter: labels"),
    };

    if thresholds.len() != labels.len() {
        return err("thresholds and labels must have equal length");
    }

    let mut levels = Vec::new();
    let mut highest_level: Option<usize> = None;

    for (i, (threshold, label)) in thresholds.iter().zip(labels.iter()).enumerate() {
        let boundary = FixedBoundary::above(*threshold, "cascade");
        let exceeded = boundary.evaluate(value);
        if exceeded {
            highest_level = Some(i);
        }
        levels.push(json!({
            "level": i + 1, "label": label, "threshold": threshold, "exceeded": exceeded,
        }));
    }

    ok(json!({
        "value": value, "levels": levels,
        "highest_level_exceeded": highest_level.map(|l| l + 1),
        "highest_label": highest_level.and_then(|l| labels.get(l)),
        "verdict": if highest_level.is_some() { "SIGNAL_DETECTED" } else { "NOT_DETECTED" },
    }))
}

fn handle_parallel(args: &Value) -> Value {
    let value = match get_f64(args, "value") {
        Some(v) => v,
        None => return err("missing required parameter: value"),
    };
    let t1 = match get_f64(args, "threshold_1") {
        Some(v) => v,
        None => return err("missing required parameter: threshold_1"),
    };
    let t2 = match get_f64(args, "threshold_2") {
        Some(v) => v,
        None => return err("missing required parameter: threshold_2"),
    };
    let label_1 = args.get("label_1").and_then(|v| v.as_str()).unwrap_or("detector_1");
    let label_2 = args.get("label_2").and_then(|v| v.as_str()).unwrap_or("detector_2");
    let mode = args.get("mode").and_then(|v| v.as_str()).unwrap_or("both");

    let b1 = FixedBoundary::above(t1, "detector_1");
    let b2 = FixedBoundary::above(t2, "detector_2");
    let d1 = b1.evaluate(value);
    let d2 = b2.evaluate(value);
    let combined = if mode == "either" { d1 || d2 } else { d1 && d2 };

    ok(json!({
        "value": value, "mode": mode,
        "detector_1": { "label": label_1, "threshold": t1, "detected": d1 },
        "detector_2": { "label": label_2, "threshold": t2, "detected": d2 },
        "combined_result": combined,
        "verdict": if combined { "SIGNAL_DETECTED" } else { "NOT_DETECTED" },
    }))
}
