//! Benefit-Risk Assessment — QBRI & QBR tools.
//!
//! Delegates to nexcore-qbr and nexcore-pv-core for validated computation.
//! Pure functions, no state — the crates do all the work.

use serde_json::{Value, json};

use crate::protocol::{ContentBlock, ToolCallResult};

/// Try to handle a benefit-risk tool call.
pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("benefit_risk_nexvigilant_com_")?
        .replace('_', "-");

    let result = handle(&bare, args)?;

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

fn handle(tool: &str, args: &Value) -> Option<Value> {
    match tool {
        "compute-qbri" => Some(compute_qbri(args)),
        "derive-qbri-thresholds" => Some(derive_qbri_thresholds(args)),
        "qbri-equation" => Some(qbri_equation()),
        "compute-qbr" => Some(compute_qbr(args)),
        "compute-qbr-simple" => Some(compute_qbr_simple(args)),
        "compute-therapeutic-window" => Some(compute_therapeutic_window(args)),
        _ => None,
    }
}

fn err(msg: &str) -> Value {
    json!({"status": "error", "message": msg})
}

fn get_f64(v: &Value, key: &str) -> Option<f64> {
    v.get(key).and_then(|v| v.as_f64())
}

fn get_u8(v: &Value, key: &str) -> Option<u8> {
    v.get(key).and_then(|v| v.as_u64()).map(|n| n as u8)
}

fn get_bool(v: &Value, key: &str, default: bool) -> bool {
    v.get(key).and_then(|v| v.as_bool()).unwrap_or(default)
}

// ─── QBRI (Expert Judgment) ─────────────────────────────────────────────────

fn compute_qbri(args: &Value) -> Value {
    use nexcore_pv_core::benefit_risk::{
        BenefitAssessment, QbriThresholds, RiskAssessment, compute_qbri as nx_qbri,
    };

    let benefit_effect = match get_f64(args, "benefit_effect") {
        Some(v) => v,
        None => return err("Missing 'benefit_effect'"),
    };
    let benefit_pvalue = match get_f64(args, "benefit_pvalue") {
        Some(v) => v,
        None => return err("Missing 'benefit_pvalue'"),
    };
    let unmet_need = match get_f64(args, "unmet_need") {
        Some(v) => v,
        None => return err("Missing 'unmet_need'"),
    };
    let risk_signal = match get_f64(args, "risk_signal") {
        Some(v) => v,
        None => return err("Missing 'risk_signal'"),
    };
    let risk_probability = match get_f64(args, "risk_probability") {
        Some(v) => v,
        None => return err("Missing 'risk_probability'"),
    };
    let risk_severity = match get_u8(args, "risk_severity") {
        Some(v) => v,
        None => return err("Missing 'risk_severity'"),
    };
    let reversible = get_bool(args, "reversible", true);

    let benefit = BenefitAssessment::from_trial(benefit_effect, benefit_pvalue, unmet_need);
    let risk = RiskAssessment::from_signal(risk_signal, risk_probability, risk_severity, reversible);
    let thresholds = QbriThresholds::default();
    let result = nx_qbri(&benefit, &risk, &thresholds);

    json!({
        "status": "ok",
        "qbri": {
            "index": format!("{:.3}", result.index),
            "decision": format!("{:?}", result.decision),
            "confidence": format!("{:.2}", result.confidence),
        },
        "components": {
            "benefit_score": format!("{:.3}", result.benefit_score),
            "risk_score": format!("{:.3}", result.risk_score),
        },
        "thresholds": {
            "tau_approve": thresholds.tau_approve,
            "tau_monitor": thresholds.tau_monitor,
            "tau_uncertain": thresholds.tau_uncertain,
        },
        "equation": "QBRI = (B × Pb × Ub) / (R × Pr × Sr × Tr)",
        "inputs": {
            "benefit": { "magnitude": benefit_effect, "probability": 1.0 - benefit_pvalue, "unmet_need": unmet_need },
            "risk": { "signal": risk_signal, "probability": risk_probability, "severity": risk_severity, "reversible": reversible },
        },
    })
}

fn derive_qbri_thresholds(args: &Value) -> Value {
    use nexcore_pv_core::benefit_risk::{derive_thresholds, generate_synthetic_data};

    let use_synthetic = get_bool(args, "use_synthetic", true);
    let data = generate_synthetic_data();
    let result = derive_thresholds(&data);
    let t = &result.thresholds;

    json!({
        "status": "ok",
        "derived_thresholds": {
            "tau_approve": format!("{:.2}", t.tau_approve),
            "tau_monitor": format!("{:.2}", t.tau_monitor),
            "tau_uncertain": format!("{:.2}", t.tau_uncertain),
        },
        "optimization": {
            "accuracy": format!("{:.1}%", result.accuracy * 100.0),
            "n_drugs": result.n_drugs,
        },
        "interpretation": {
            "approve": format!("QBRI > {:.2}", t.tau_approve),
            "rems": format!("QBRI ∈ [{:.2}, {:.2}]", t.tau_monitor, t.tau_approve),
            "more_data": format!("QBRI ∈ [{:.2}, {:.2}]", t.tau_uncertain, t.tau_monitor),
            "reject": format!("QBRI < {:.2}", t.tau_uncertain),
        },
        "data_source": if use_synthetic { "synthetic (8 drugs)" } else { "historical" },
    })
}

fn qbri_equation() -> Value {
    json!({
        "status": "ok",
        "equation": "QBRI = (B × Pb × Ub) / (R × Pr × Sr × Tr)",
        "variables": {
            "B": "Benefit magnitude (effect size from trial)",
            "Pb": "P(benefit) = 1 - p-value",
            "Ub": "Unmet medical need [1-10]",
            "R": "Risk signal strength (PRR/ROR from FAERS)",
            "Pr": "P(causal) from Naranjo/WHO-UMC",
            "Sr": "Severity on Hartwig-Siegel scale [1-7]",
            "Tr": "Treatability factor (reversible: 0.5, irreversible: 1.0)",
        },
        "thresholds": {
            "tau_approve": 2.0,
            "tau_monitor": 1.0,
            "tau_uncertain": 0.5,
        },
        "decisions": {
            "Approve": "QBRI > tau_approve — benefits clearly outweigh risks",
            "Monitor": "tau_monitor < QBRI ≤ tau_approve — approve with REMS/risk management",
            "MoreData": "tau_uncertain < QBRI ≤ tau_monitor — insufficient evidence, request more data",
            "Reject": "QBRI ≤ tau_uncertain — risks outweigh benefits",
        },
    })
}

// ─── QBR (Statistical Evidence) ─────────────────────────────────────────────

fn extract_table(v: &Value) -> Option<nexcore_pv_core::signals::ContingencyTable> {
    let a = v.get("a")?.as_u64()?;
    let b = v.get("b")?.as_u64()?;
    let c = v.get("c")?.as_u64()?;
    let d = v.get("d")?.as_u64()?;
    Some(nexcore_pv_core::signals::ContingencyTable::new(a, b, c, d))
}

fn parse_method(s: &str) -> Option<nexcore_qbr::QbrSignalMethod> {
    match s {
        "prr" => Some(nexcore_qbr::QbrSignalMethod::Prr),
        "ror" => Some(nexcore_qbr::QbrSignalMethod::Ror),
        "ic" => Some(nexcore_qbr::QbrSignalMethod::Ic),
        "ebgm" => Some(nexcore_qbr::QbrSignalMethod::Ebgm),
        _ => None,
    }
}

fn measured_json(m: &nexcore_constants::Measured<f64>) -> Value {
    json!({"value": m.value, "confidence": m.confidence.value()})
}

fn compute_qbr(args: &Value) -> Value {
    let method_str = args.get("method").and_then(|v| v.as_str()).unwrap_or("");
    let method = match parse_method(method_str) {
        Some(m) => m,
        None => return err("Invalid method. Must be: prr, ror, ic, or ebgm"),
    };

    let benefit_tables: Vec<_> = args.get("benefit_tables")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(extract_table).collect())
        .unwrap_or_default();

    let risk_tables: Vec<_> = args.get("risk_tables")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(extract_table).collect())
        .unwrap_or_default();

    if benefit_tables.is_empty() || risk_tables.is_empty() {
        return err("Need at least one benefit_table and one risk_table with {a, b, c, d}");
    }

    let input = nexcore_qbr::BenefitRiskInput {
        benefit_tables,
        risk_tables,
        benefit_weights: None,
        risk_weights: None,
        hill_efficacy: None,
        hill_toxicity: None,
        integration_bounds: None,
        method,
    };

    match nexcore_qbr::compute_qbr(&input) {
        Ok(qbr) => json!({
            "status": "ok",
            "simple": measured_json(&qbr.simple),
            "bayesian": qbr.bayesian.as_ref().map(measured_json),
            "composite": qbr.composite.as_ref().map(measured_json),
            "therapeutic_window": qbr.therapeutic_window.as_ref().map(measured_json),
            "details": {
                "benefit_signal": measured_json(&qbr.details.benefit_signal),
                "risk_signal": measured_json(&qbr.details.risk_signal),
                "method": format!("{:?}", qbr.details.method).to_lowercase(),
            },
        }),
        Err(e) => err(&e.to_string()),
    }
}

fn compute_qbr_simple(args: &Value) -> Value {
    let method_str = args.get("method").and_then(|v| v.as_str()).unwrap_or("");
    let method = match parse_method(method_str) {
        Some(m) => m,
        None => return err("Invalid method. Must be: prr, ror, ic, or ebgm"),
    };

    let benefit_ct = match args.get("benefit_table").and_then(extract_table) {
        Some(ct) => ct,
        None => return err("Missing or invalid benefit_table {a, b, c, d}"),
    };
    let risk_ct = match args.get("risk_table").and_then(extract_table) {
        Some(ct) => ct,
        None => return err("Missing or invalid risk_table {a, b, c, d}"),
    };

    let qbr_ratio = match nexcore_qbr::compute_simple(&benefit_ct, &risk_ct, method) {
        Ok(r) => r,
        Err(e) => return err(&e.to_string()),
    };
    let benefit_signal = match nexcore_qbr::signal::extract_signal_strength(&benefit_ct, method) {
        Ok(s) => s,
        Err(e) => return err(&e.to_string()),
    };
    let risk_signal = match nexcore_qbr::signal::extract_signal_strength(&risk_ct, method) {
        Ok(s) => s,
        Err(e) => return err(&e.to_string()),
    };

    json!({
        "status": "ok",
        "qbr": measured_json(&qbr_ratio),
        "benefit_signal": measured_json(&benefit_signal),
        "risk_signal": measured_json(&risk_signal),
        "method": format!("{:?}", method).to_lowercase(),
    })
}

fn compute_therapeutic_window(args: &Value) -> Value {
    use nexcore_primitives::chemistry::cooperativity::hill_response;

    let efficacy = match args.get("efficacy") {
        Some(v) => nexcore_qbr::HillCurveParams {
            k_half: get_f64(v, "k_half").unwrap_or(10.0),
            n_hill: get_f64(v, "n_hill").unwrap_or(1.0),
        },
        None => return err("Missing 'efficacy' {k_half, n_hill}"),
    };
    let toxicity = match args.get("toxicity") {
        Some(v) => nexcore_qbr::HillCurveParams {
            k_half: get_f64(v, "k_half").unwrap_or(100.0),
            n_hill: get_f64(v, "n_hill").unwrap_or(1.0),
        },
        None => return err("Missing 'toxicity' {k_half, n_hill}"),
    };

    let bounds_val = args.get("bounds");
    let bounds = nexcore_qbr::IntegrationBounds {
        dose_min: bounds_val.and_then(|b| get_f64(b, "dose_min")).unwrap_or(0.1),
        dose_max: bounds_val.and_then(|b| get_f64(b, "dose_max")).unwrap_or(100.0),
        intervals: bounds_val.and_then(|b| b.get("intervals").and_then(|v| v.as_u64()).map(|n| n as usize)).unwrap_or(1000),
    };

    let tw = match nexcore_qbr::compute_therapeutic_window(&efficacy, &toxicity, &bounds) {
        Ok(r) => r,
        Err(e) => return err(&e.to_string()),
    };

    let n = if bounds.intervals % 2 != 0 { bounds.intervals + 1 } else { bounds.intervals };
    let eff_auc = nexcore_qbr::simpson_integrate(
        |d| hill_response(d, efficacy.k_half, efficacy.n_hill), bounds.dose_min, bounds.dose_max, n,
    ).unwrap_or(0.0);
    let tox_auc = nexcore_qbr::simpson_integrate(
        |d| hill_response(d, toxicity.k_half, toxicity.n_hill), bounds.dose_min, bounds.dose_max, n,
    ).unwrap_or(0.0);

    json!({
        "status": "ok",
        "therapeutic_window": measured_json(&tw),
        "efficacy_auc": eff_auc,
        "toxicity_auc": tox_auc,
        "bounds": { "dose_min": bounds.dose_min, "dose_max": bounds.dose_max, "intervals": n },
    })
}
