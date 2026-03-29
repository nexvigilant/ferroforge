//! Preemptive Pharmacovigilance — three-tier signal detection.
//!
//! Delegates to nexcore-preemptive-pv for reactive, predictive, and
//! preemptive (Gibbs thermodynamic) signal detection.

use nexcore_preemptive_pv::{
    gibbs, intervention, noise, predictive, preemptive, reactive,
    GibbsParams, NoiseParams, ReportingCounts,
};
use serde_json::{Value, json};

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("preemptive_pv_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "reactive" => handle_reactive(args),
        "gibbs" => handle_gibbs(args),
        "noise" => handle_noise(args),
        "evaluate" => handle_evaluate(args),
        "intervention" => handle_intervention(args),
        "required-strength" => handle_required_strength(args),
        "omega-table" => handle_omega_table(),
        _ => return None,
    };

    Some(ToolCallResult {
        content: vec![ContentBlock::Text { text: serde_json::to_string_pretty(&result).unwrap_or_default() }],
        is_error: if result.get("status").and_then(|s| s.as_str()) == Some("error") { Some(true) } else { None },
    })
}

fn err(msg: &str) -> Value { json!({"status": "error", "message": msg}) }
fn get_f64(v: &Value, k: &str) -> Option<f64> { v.get(k).and_then(|v| v.as_f64()) }

fn extract_counts(args: &Value) -> Option<ReportingCounts> {
    Some(ReportingCounts::new(
        get_f64(args, "a")?,
        get_f64(args, "b")?,
        get_f64(args, "c")?,
        get_f64(args, "d")?,
    ))
}

fn handle_reactive(args: &Value) -> Value {
    let counts = match extract_counts(args) {
        Some(c) => c,
        None => return err("Missing contingency table values: a, b, c, d"),
    };
    let threshold = get_f64(args, "threshold").unwrap_or(2.0);
    let strength = reactive::signal_strength(&counts);
    let detected = reactive::is_signal(&counts, threshold);

    json!({
        "status": "ok",
        "tier": "reactive",
        "signal_strength": strength,
        "threshold": threshold,
        "signal_detected": detected,
        "contingency": {"a": counts.a, "b": counts.b, "c": counts.c, "d": counts.d, "N": counts.total()},
    })
}

fn handle_gibbs(args: &Value) -> Value {
    let delta_h = match get_f64(args, "delta_h_mechanism") {
        Some(v) => v,
        None => return err("Missing 'delta_h_mechanism' (mechanistic plausibility 0-10)"),
    };
    let t_exposure = match get_f64(args, "t_exposure") {
        Some(v) => v,
        None => return err("Missing 't_exposure' (patient-years of exposure)"),
    };
    let delta_s = match get_f64(args, "delta_s_information") {
        Some(v) => v,
        None => return err("Missing 'delta_s_information' (information entropy of evidence)"),
    };

    let params = GibbsParams::new(delta_h, t_exposure, delta_s);
    let dg = gibbs::delta_g(&params);
    let favorable = gibbs::is_favorable(&params);
    let feasibility = gibbs::feasibility_score(&params);

    json!({
        "status": "ok",
        "tier": "preemptive",
        "delta_g": dg,
        "favorable": favorable,
        "feasibility_score": feasibility,
        "interpretation": if favorable {
            "Signal is thermodynamically favorable — spontaneous emergence expected"
        } else {
            "Signal is thermodynamically unfavorable — spontaneous emergence unlikely"
        },
        "inputs": {"delta_h_mechanism": delta_h, "t_exposure": t_exposure, "delta_s_information": delta_s},
    })
}

fn handle_noise(args: &Value) -> Value {
    let r_stimulated = match get_f64(args, "r_stimulated") {
        Some(v) => v,
        None => return err("Missing 'r_stimulated' (stimulated reporting rate)"),
    };
    let r_baseline = match get_f64(args, "r_baseline") {
        Some(v) => v,
        None => return err("Missing 'r_baseline' (baseline reporting rate)"),
    };
    let k = get_f64(args, "k").unwrap_or(1.0);

    let params = NoiseParams::with_k(r_stimulated, r_baseline, k);
    let eta_val = noise::eta(&params);
    let retention = noise::signal_retention(&params);
    let organic = noise::is_organic(&params);

    json!({
        "status": "ok",
        "eta": eta_val,
        "signal_retention": retention,
        "is_organic": organic,
        "interpretation": if organic { "Signal is organic — above noise floor" } else { "Signal may be noise-driven" },
    })
}

fn handle_evaluate(args: &Value) -> Value {
    let counts = match extract_counts(args) {
        Some(c) => c,
        None => return err("Missing contingency table values: a, b, c, d"),
    };

    let delta_h = get_f64(args, "delta_h_mechanism").unwrap_or(5.0);
    let t_exposure = get_f64(args, "t_exposure").unwrap_or(1000.0);
    let delta_s = get_f64(args, "delta_s_information").unwrap_or(1.0);

    let gibbs_params = GibbsParams::new(delta_h, t_exposure, delta_s);

    // Reactive tier
    let strength = reactive::signal_strength(&counts);
    let reactive_detected = reactive::is_signal_default(&counts);

    // Preemptive tier
    let dg = gibbs::delta_g(&gibbs_params);
    let favorable = gibbs::is_favorable(&gibbs_params);

    let tier = if favorable && reactive_detected {
        "preemptive"
    } else if reactive_detected {
        "reactive"
    } else {
        "none"
    };

    json!({
        "status": "ok",
        "reactive": {"signal_strength": strength, "detected": reactive_detected},
        "preemptive": {"delta_g": dg, "favorable": favorable},
        "tier": tier,
        "recommendation": match tier {
            "preemptive" => "Signal detected at preemptive tier — immediate investigation recommended",
            "reactive" => "Signal detected at reactive tier — standard signal evaluation indicated",
            _ => "No signal detected at any tier",
        },
    })
}

fn handle_intervention(args: &Value) -> Value {
    let v_max = match get_f64(args, "signal_strength") { Some(v) => v, None => return err("Missing 'signal_strength'") };
    let inhibitor = match get_f64(args, "intervention_strength") { Some(v) => v, None => return err("Missing 'intervention_strength'") };
    let k_m = get_f64(args, "k_m").unwrap_or(1.0);
    let k_i = get_f64(args, "k_i").unwrap_or(1.0);
    let substrate = get_f64(args, "substrate").unwrap_or(1.0);

    let inhibited = intervention::inhibited_rate(v_max, substrate, inhibitor, k_m, k_i);
    let uninhibited = intervention::uninhibited_rate(v_max, substrate, k_m);
    let reduction = if uninhibited > 0.0 { 1.0 - (inhibited / uninhibited) } else { 0.0 };

    json!({
        "status": "ok",
        "uninhibited_rate": uninhibited,
        "inhibited_rate": inhibited,
        "reduction_fraction": reduction,
        "reduction_pct": format!("{:.1}%", reduction * 100.0),
        "effective": reduction > 0.3,
    })
}

fn handle_required_strength(args: &Value) -> Value {
    let v_max = match get_f64(args, "signal_strength") { Some(v) => v, None => return err("Missing 'signal_strength'") };
    let target = get_f64(args, "target_reduction").unwrap_or(0.5);
    let k_m = get_f64(args, "k_m").unwrap_or(1.0);
    let k_i = get_f64(args, "k_i").unwrap_or(1.0);
    let substrate = get_f64(args, "substrate").unwrap_or(1.0);

    let result = intervention::required_intervention_strength(v_max, substrate, target, k_m, k_i);

    json!({
        "status": "ok",
        "required_strength": result,
        "target_reduction": target,
        "achievable": result.is_finite() && result > 0.0,
    })
}

fn handle_omega_table() -> Value {
    json!({
        "status": "ok",
        "description": "Seriousness severity weights based on ICH E2A criteria",
        "tiers": [
            {"seriousness": "NonSerious", "severity_score": 0.2, "description": "Non-serious adverse event"},
            {"seriousness": "Hospitalization", "severity_score": 0.4, "description": "Required or prolonged hospitalization"},
            {"seriousness": "Disability", "severity_score": 0.6, "description": "Persistent or significant disability"},
            {"seriousness": "LifeThreatening", "severity_score": 0.8, "description": "Life-threatening event"},
            {"seriousness": "Fatal", "severity_score": 1.0, "description": "Death"},
        ],
    })
}
