//! Signal Theory — Universal Signal Detection Framework.
//!
//! Delegates to nexcore-signal-theory for axioms, theorems, detection,
//! SDT decision matrix, conservation verification, pipelines, and fusion.

use serde_json::{Value, json};

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("signal_theory_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "get-axioms" => axioms(),
        "get-theorems" => theorems(),
        "detect" => detect(args),
        "decision-matrix" => decision_matrix(args),
        "conservation-check" => conservation_check(args),
        "pipeline" => pipeline(args),
        "cascade" => cascade(args),
        "parallel" => parallel(args),
        _ => return None,
    };

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

fn err(msg: &str) -> Value {
    json!({"status": "error", "message": msg})
}

fn get_f64(v: &Value, k: &str) -> Option<f64> { v.get(k).and_then(|v| v.as_f64()) }
fn get_u64(v: &Value, k: &str) -> Option<u64> { v.get(k).and_then(|v| v.as_u64()) }
fn get_str<'a>(v: &'a Value, k: &str) -> Option<&'a str> { v.get(k).and_then(|v| v.as_str()) }

fn axioms() -> Value {
    use nexcore_signal_theory::prelude::*;
    let data: [(_, _, _, _); 6] = [
        ("A1", "Data Generation", "ν (Frequency)", <A1DataGeneration<1000> as Axiom>::statement()),
        ("A2", "Noise Dominance", "∅ (Void)", <A2NoiseDominance as Axiom>::statement()),
        ("A3", "Signal Existence", "∃ (Existence)", <A3SignalExistence as Axiom>::statement()),
        ("A4", "Boundary Requirement", "∂ (Boundary) [DOMINANT]", <A4BoundaryRequirement as Axiom>::statement()),
        ("A5", "Disproportionality", "κ (Comparison)", <A5Disproportionality as Axiom>::statement()),
        ("A6", "Causal Inference", "→ (Causality)", <A6CausalInference as Axiom>::statement()),
    ];
    json!({
        "status": "ok",
        "thesis": "All detection is boundary drawing",
        "dominant_primitive": "∂ (Boundary)",
        "axiom_count": 6,
        "axioms": data.iter().map(|(id, name, prim, stmt)| json!({"id": id, "name": name, "primitive": prim, "statement": stmt})).collect::<Vec<_>>(),
    })
}

fn theorems() -> Value {
    use nexcore_signal_theory::prelude::*;
    let registry = TheoremRegistry::build();
    json!({
        "status": "ok",
        "theorem_count": registry.theorems.len(),
        "theorems": registry.theorems.iter().map(|t| json!({"id": t.id, "name": t.name, "statement": t.statement, "prerequisites": t.prerequisites})).collect::<Vec<_>>(),
    })
}

fn detect(args: &Value) -> Value {
    use nexcore_signal_theory::prelude::*;
    let observed = match get_f64(args, "observed") { Some(v) => v, None => return err("Missing 'observed'") };
    let expected = match get_f64(args, "expected") { Some(v) => v, None => return err("Missing 'expected'") };
    let threshold = get_f64(args, "threshold").unwrap_or(2.0);

    let boundary = FixedBoundary::above(threshold, "detection");
    let ratio = Ratio::from_counts(observed, expected);
    let (ratio_value, detected, strength) = match ratio {
        Some(r) => (Some(r.0), boundary.evaluate(r.0), SignalStrengthLevel::from_ratio(r.0)),
        None => (None, false, SignalStrengthLevel::None),
    };
    let difference = Difference::from_counts(observed, expected);

    json!({
        "status": "ok",
        "observed": observed, "expected": expected, "threshold": threshold,
        "ratio": ratio_value, "difference": difference.0,
        "detected": detected, "strength": format!("{:?}", strength),
        "outcome": if detected { "Detected" } else { "NotDetected" },
    })
}

fn decision_matrix(args: &Value) -> Value {
    use nexcore_signal_theory::prelude::*;
    let h = get_u64(args, "hits").unwrap_or(0);
    let m = get_u64(args, "misses").unwrap_or(0);
    let fa = get_u64(args, "false_alarms").unwrap_or(0);
    let cr = get_u64(args, "correct_rejections").unwrap_or(0);

    let dm = DecisionMatrix::new(h, m, fa, cr);
    let dprime = DPrime::from_matrix(&dm);
    let bias = ResponseBias::from_matrix(&dm);

    json!({
        "status": "ok",
        "matrix": {"hits": dm.hits, "misses": dm.misses, "false_alarms": dm.false_alarms, "correct_rejections": dm.correct_rejections, "total": dm.total()},
        "metrics": {"sensitivity": dm.sensitivity(), "specificity": dm.specificity(), "ppv": dm.ppv(), "npv": dm.npv(), "accuracy": dm.accuracy(), "fpr": dm.false_positive_rate(), "fnr": dm.false_negative_rate(), "f1_score": dm.f1_score(), "mcc": dm.mcc()},
        "sdt": {"d_prime": dprime.0, "d_prime_level": dprime.level(), "response_bias": bias.0, "bias_description": bias.description()},
    })
}

fn conservation_check(args: &Value) -> Value {
    use nexcore_signal_theory::prelude::*;
    let h = get_u64(args, "hits").unwrap_or(0);
    let m = get_u64(args, "misses").unwrap_or(0);
    let fa = get_u64(args, "false_alarms").unwrap_or(0);
    let cr = get_u64(args, "correct_rejections").unwrap_or(0);

    let dm = DecisionMatrix::new(h, m, fa, cr);
    let mut report = ConservationReport::new();

    let expected_total = get_u64(args, "expected_total").unwrap_or(h + m + fa + cr);
    report.add("L1", L1TotalCountConservation.verify(&dm, expected_total));

    if let Some(max_dp) = get_f64(args, "max_dprime") {
        let observed_dp = DPrime::from_matrix(&dm).0;
        report.add("L4", L4InformationConservation.verify(observed_dp, max_dp));
    }

    json!({
        "status": "ok",
        "all_satisfied": report.all_satisfied(),
        "laws_checked": report.results.len(),
        "violations": report.violations().iter().map(|(id, msg)| json!({"law": id, "violation": msg})).collect::<Vec<_>>(),
    })
}

fn pipeline(args: &Value) -> Value {
    use nexcore_signal_theory::prelude::*;
    let value = match get_f64(args, "value") { Some(v) => v, None => return err("Missing 'value'") };
    let label = get_str(args, "label").unwrap_or("pipeline");
    let stages = match args.get("stages").and_then(|v| v.as_array()) { Some(s) => s, None => return err("Missing 'stages' array") };

    let mut results = Vec::new();
    let mut all_passed = true;
    let mut first_failure: Option<String> = None;

    for (i, stage) in stages.iter().enumerate() {
        let name = get_str(stage, "name").unwrap_or("unnamed");
        let phase = get_str(stage, "phase").unwrap_or("");
        let threshold = get_f64(stage, "threshold").unwrap_or(0.0);
        let boundary = FixedBoundary::above(threshold, "detection");
        let passed = boundary.evaluate(value);
        if !passed && first_failure.is_none() { first_failure = Some(name.to_string()); all_passed = false; }
        results.push(json!({"stage": i + 1, "name": name, "phase": phase, "threshold": threshold, "passed": passed}));
    }

    json!({"status": "ok", "label": label, "value": value, "all_passed": all_passed, "first_failure": first_failure, "stages": results, "verdict": if all_passed { "SIGNAL_DETECTED" } else { "NOT_DETECTED" }})
}

fn cascade(args: &Value) -> Value {
    use nexcore_signal_theory::prelude::*;
    let value = match get_f64(args, "value") { Some(v) => v, None => return err("Missing 'value'") };
    let thresholds: Vec<f64> = args.get("thresholds").and_then(|v| v.as_array()).map(|a| a.iter().filter_map(|v| v.as_f64()).collect()).unwrap_or_default();
    let labels: Vec<&str> = args.get("labels").and_then(|v| v.as_array()).map(|a| a.iter().filter_map(|v| v.as_str()).collect()).unwrap_or_default();

    if thresholds.len() != labels.len() { return err("thresholds and labels must have equal length"); }

    let mut highest: Option<usize> = None;
    let levels: Vec<_> = thresholds.iter().zip(labels.iter()).enumerate().map(|(i, (t, l))| {
        let exceeded = FixedBoundary::above(*t, "cascade").evaluate(value);
        if exceeded { highest = Some(i); }
        json!({"level": i + 1, "label": l, "threshold": t, "exceeded": exceeded})
    }).collect();

    json!({"status": "ok", "value": value, "levels": levels, "highest_level_exceeded": highest.map(|l| l + 1), "highest_label": highest.and_then(|l| labels.get(l)), "verdict": if highest.is_some() { "SIGNAL_DETECTED" } else { "NOT_DETECTED" }})
}

fn parallel(args: &Value) -> Value {
    use nexcore_signal_theory::prelude::*;
    let value = match get_f64(args, "value") { Some(v) => v, None => return err("Missing 'value'") };
    let t1 = get_f64(args, "threshold_1").unwrap_or(2.0);
    let t2 = get_f64(args, "threshold_2").unwrap_or(2.0);
    let l1 = get_str(args, "label_1").unwrap_or("detector_1");
    let l2 = get_str(args, "label_2").unwrap_or("detector_2");
    let mode = get_str(args, "mode").unwrap_or("both");

    let d1 = FixedBoundary::above(t1, "d1").evaluate(value);
    let d2 = FixedBoundary::above(t2, "d2").evaluate(value);
    let combined = if mode == "either" { d1 || d2 } else { d1 && d2 };

    json!({"status": "ok", "value": value, "mode": mode, "detector_1": {"label": l1, "threshold": t1, "detected": d1}, "detector_2": {"label": l2, "threshold": t2, "detected": d2}, "combined_result": combined, "verdict": if combined { "SIGNAL_DETECTED" } else { "NOT_DETECTED" }})
}
