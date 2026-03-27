//! Preemptive Pharmacovigilance — Rust-native handler for NexVigilant Station.
//!
//! Routes `preemptive-pv_nexvigilant_com_*` tool calls to `nexcore-preemptive-pv`.

use nexcore_preemptive_pv::{
    GibbsParams, NoiseParams, ReportingCounts, ReportingDataPoint, Seriousness,
};
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

/// Try to handle a preemptive-pv tool call. Returns `None` to fall through.
pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("preemptive-pv_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "reactive" => handle_reactive(args),
        "predictive" => handle_predictive(args),
        "gibbs" => handle_gibbs(args),
        "evaluate" => handle_evaluate(args),
        "trajectory" => handle_trajectory(args),
        "severity" => handle_severity(args),
        "noise" => handle_noise(args),
        "intervention" => handle_intervention(args),
        "required-strength" => handle_required_strength(args),
        "omega-table" => handle_omega_table(),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (preemptive-pv)");

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

fn get_str<'a>(args: &'a Value, key: &str) -> Option<&'a str> {
    args.get(key).and_then(|v| v.as_str())
}

fn parse_seriousness(s: &str) -> Option<Seriousness> {
    match s.to_lowercase().as_str() {
        "non_serious" | "nonserious" | "none" => Some(Seriousness::NonSerious),
        "hospitalization" | "hospital" => Some(Seriousness::Hospitalization),
        "disability" => Some(Seriousness::Disability),
        "life_threatening" | "lifethreatening" => Some(Seriousness::LifeThreatening),
        "fatal" | "death" => Some(Seriousness::Fatal),
        _ => None,
    }
}

fn get_abcd(args: &Value) -> Option<(f64, f64, f64, f64)> {
    let a = get_f64(args, "a")?;
    let b = get_f64(args, "b")?;
    let c = get_f64(args, "c")?;
    let d = get_f64(args, "d")?;
    Some((a, b, c, d))
}

fn parse_data_points(args: &Value) -> Option<Vec<ReportingDataPoint>> {
    let arr = args.get("data").and_then(|v| v.as_array())?;
    let points: Vec<_> = arr
        .iter()
        .filter_map(|d| {
            let time = d.get("time").and_then(|v| v.as_f64())?;
            let rate = d.get("rate").and_then(|v| v.as_f64())?;
            Some(ReportingDataPoint::new(time, rate))
        })
        .collect();
    if points.is_empty() { None } else { Some(points) }
}

fn handle_reactive(args: &Value) -> Value {
    let (a, b, c, d) = match get_abcd(args) {
        Some(v) => v,
        None => return err("missing required parameters: a, b, c, d (2x2 contingency table)"),
    };

    let counts = ReportingCounts::new(a, b, c, d);
    let strength = nexcore_preemptive_pv::reactive::signal_strength(&counts);
    let chi2 = nexcore_preemptive_pv::reactive::chi_squared(&counts);
    let threshold = get_f64(args, "threshold").unwrap_or(2.0);
    let is_signal = nexcore_preemptive_pv::reactive::is_signal(&counts, threshold);
    let chi2_sig = nexcore_preemptive_pv::reactive::chi_squared_significant(&counts);

    ok(json!({
        "tier": 1, "tier_name": "Reactive",
        "signal_strength": strength, "is_signal": is_signal, "threshold": threshold,
        "chi_squared": chi2, "chi_squared_significant": chi2_sig,
        "chi_squared_critical": nexcore_preemptive_pv::reactive::CHI2_CRITICAL_005,
        "counts": { "a": a, "b": b, "c": c, "d": d, "total": counts.total(), "expected": counts.expected() },
    }))
}

fn handle_predictive(args: &Value) -> Value {
    let (a, b, c, d) = match get_abcd(args) {
        Some(v) => v,
        None => return err("missing required parameters: a, b, c, d"),
    };
    let seriousness = get_str(args, "seriousness").unwrap_or("non_serious");
    let s = match parse_seriousness(seriousness) {
        Some(s) => s,
        None => return err(&format!("unknown seriousness: {seriousness}")),
    };

    let counts = ReportingCounts::new(a, b, c, d);
    let strength = nexcore_preemptive_pv::reactive::signal_strength(&counts).unwrap_or(0.0);
    let omega = nexcore_preemptive_pv::severity::omega(s);
    let weighted = strength * omega;

    ok(json!({
        "tier": 2, "tier_name": "Predictive",
        "prr": strength, "omega": omega, "weighted_prr": weighted,
        "seriousness": seriousness,
        "interpretation": if weighted > 2.0 { "Signal amplified by severity" } else { "Below predictive threshold" },
    }))
}

fn handle_gibbs(args: &Value) -> Value {
    let prr = match get_f64(args, "prr") {
        Some(v) => v,
        None => return err("missing required parameter: prr"),
    };
    let n = match get_f64(args, "n") {
        Some(v) => v,
        None => return err("missing required parameter: n"),
    };
    let seriousness = get_str(args, "seriousness").unwrap_or("non_serious");
    let s = match parse_seriousness(seriousness) {
        Some(s) => s,
        None => return err(&format!("unknown seriousness: {seriousness}")),
    };
    let temperature = get_f64(args, "temperature").unwrap_or(1.0);

    let omega = nexcore_preemptive_pv::severity::omega(s);
    let delta_h = if prr > 0.0 { -(prr.ln()) } else { 0.0 };
    let delta_s = if n > 0.0 { n.ln() * omega } else { 0.0 };

    let params = GibbsParams::new(delta_h, temperature, delta_s);
    let dg = nexcore_preemptive_pv::gibbs::delta_g(&params);
    let favorable = nexcore_preemptive_pv::gibbs::is_favorable(&params);
    let score = nexcore_preemptive_pv::gibbs::feasibility_score(&params);

    let energy_class = if dg < -10.0 {
        "highly_spontaneous"
    } else if dg < 0.0 {
        "spontaneous"
    } else if dg < 10.0 {
        "borderline"
    } else {
        "non_spontaneous"
    };

    ok(json!({
        "delta_g": dg, "spontaneous": favorable,
        "feasibility_score": score, "energy_class": energy_class,
        "interpretation": if favorable {
            "Signal emergence thermodynamically favorable"
        } else {
            "Signal emergence thermodynamically unfavorable"
        },
        "params": { "prr": prr, "n": n, "seriousness": seriousness, "temperature": temperature },
    }))
}

fn handle_evaluate(args: &Value) -> Value {
    let (a, b, c, d) = match get_abcd(args) {
        Some(v) => v,
        None => return err("missing required parameters: a, b, c, d"),
    };
    let seriousness = get_str(args, "seriousness").unwrap_or("non_serious");
    let s = match parse_seriousness(seriousness) {
        Some(s) => s,
        None => return err(&format!("unknown seriousness: {seriousness}")),
    };
    let temperature = get_f64(args, "temperature").unwrap_or(1.0);

    let counts = ReportingCounts::new(a, b, c, d);
    let prr = nexcore_preemptive_pv::reactive::signal_strength(&counts).unwrap_or(0.0);
    let chi2 = nexcore_preemptive_pv::reactive::chi_squared(&counts);
    let chi2_sig = nexcore_preemptive_pv::reactive::chi_squared_significant(&counts);
    let is_reactive = nexcore_preemptive_pv::reactive::is_signal(&counts, 2.0);

    let omega = nexcore_preemptive_pv::severity::omega(s);
    let weighted_prr = prr * omega;

    let delta_h = if prr > 0.0 { -(prr.ln()) } else { 0.0 };
    let delta_s = if counts.total() > 0.0 { counts.total().ln() * omega } else { 0.0 };
    let gibbs = GibbsParams::new(delta_h, temperature, delta_s);
    let dg = nexcore_preemptive_pv::gibbs::delta_g(&gibbs);
    let favorable = nexcore_preemptive_pv::gibbs::is_favorable(&gibbs);

    let tier = if favorable && weighted_prr > 2.0 {
        "preemptive"
    } else if weighted_prr > 2.0 {
        "predictive"
    } else if is_reactive {
        "reactive"
    } else {
        "none"
    };

    let recommendation = match tier {
        "preemptive" => "Immediate investigation — thermodynamically favorable + severity-amplified signal",
        "predictive" => "Enhanced monitoring — severity-weighted signal exceeds threshold",
        "reactive" => "Standard signal detected — routine assessment",
        _ => "No signal detected at any tier",
    };

    ok(json!({
        "tier": tier, "recommendation": recommendation,
        "reactive": {
            "prr": prr, "chi_squared": chi2,
            "chi_squared_significant": chi2_sig, "is_signal": is_reactive,
        },
        "predictive": {
            "weighted_prr": weighted_prr, "omega": omega, "seriousness": seriousness,
        },
        "preemptive": {
            "delta_g": dg, "spontaneous": favorable,
            "energy_class": if dg < 0.0 { "spontaneous" } else { "non_spontaneous" },
        },
    }))
}

fn handle_trajectory(args: &Value) -> Value {
    let points = match parse_data_points(args) {
        Some(p) if p.len() >= 2 => p,
        _ => return err("need at least 2 data points in 'data' array [{time, rate}, ...]"),
    };
    let n_hill = get_f64(args, "n_hill")
        .unwrap_or(nexcore_preemptive_pv::trajectory::DEFAULT_HILL_COEFFICIENT);

    let alpha = nexcore_preemptive_pv::trajectory::DEFAULT_ALPHA;
    let k_half = nexcore_preemptive_pv::trajectory::DEFAULT_K_HALF;
    let gamma_raw = nexcore_preemptive_pv::trajectory::gamma(&points, alpha);
    let gamma_amp = nexcore_preemptive_pv::trajectory::gamma_amplified(&points);
    let hill_applied = nexcore_preemptive_pv::trajectory::hill_amplify(gamma_raw, n_hill, k_half);

    ok(json!({
        "gamma_raw": gamma_raw, "gamma_amplified": gamma_amp,
        "hill_applied": hill_applied, "data_points": points.len(),
        "accelerating": gamma_amp > 0.0,
        "params": { "alpha": alpha, "hill_n": n_hill, "hill_k_half": k_half },
    }))
}

fn handle_severity(args: &Value) -> Value {
    let seriousness = match get_str(args, "seriousness") {
        Some(s) => s,
        None => return err("missing required parameter: seriousness"),
    };
    match parse_seriousness(seriousness) {
        Some(s) => {
            let omega = nexcore_preemptive_pv::severity::omega(s);
            let omega_norm = nexcore_preemptive_pv::severity::omega_normalized(s);
            ok(json!({
                "seriousness": seriousness, "omega": omega, "omega_normalized": omega_norm,
                "severity_score": s.severity_score(), "irreversibility_factor": s.irreversibility_factor(),
                "label": format!("{s:?}"),
                "formula": "Omega = S * (1 + irreversibility_factor)",
            }))
        }
        None => err(&format!(
            "unknown seriousness: {seriousness}. Use: non_serious, hospitalization, disability, life_threatening, fatal"
        )),
    }
}

fn handle_noise(args: &Value) -> Value {
    let observed = match get_f64(args, "observed") {
        Some(v) => v,
        None => return err("missing required parameter: observed"),
    };
    let background = match get_f64(args, "background") {
        Some(v) => v,
        None => return err("missing required parameter: background"),
    };
    let alpha = get_f64(args, "alpha").unwrap_or(0.05);

    let params = NoiseParams::new(observed, background);
    let eta = nexcore_preemptive_pv::noise::eta(&params);
    let retention = nexcore_preemptive_pv::noise::signal_retention(&params);
    let organic = nexcore_preemptive_pv::noise::is_organic(&params);

    let corrected = observed - background;
    let above_noise = corrected > (alpha * background);

    ok(json!({
        "eta": eta, "signal_retention": retention, "is_organic": organic,
        "corrected_signal": corrected, "above_noise": above_noise,
        "interpretation": if organic {
            "Reporting appears organic (eta < 0.5)"
        } else {
            "Reporting appears stimulated — signal may be noise-inflated"
        },
    }))
}

fn handle_intervention(args: &Value) -> Value {
    let signal_strength = match get_f64(args, "signal_strength") {
        Some(v) => v,
        None => return err("missing required parameter: signal_strength"),
    };
    let intervention_strength = match get_f64(args, "intervention_strength") {
        Some(v) => v,
        None => return err("missing required parameter: intervention_strength"),
    };
    let ki = get_f64(args, "ki").unwrap_or(nexcore_preemptive_pv::intervention::DEFAULT_K_I);
    let k_m = nexcore_preemptive_pv::intervention::DEFAULT_K_M;

    let result = nexcore_preemptive_pv::intervention::intervention_effect(
        signal_strength,
        1.0,
        intervention_strength,
        k_m,
        ki,
    );

    ok(json!({
        "inhibited_rate": result.inhibited_rate,
        "original_rate": result.original_rate,
        "reduction_fraction": result.reduction_fraction,
        "reduction_pct": result.reduction_percentage,
        "effective": result.reduction_fraction > 0.1,
        "params": { "signal_strength": signal_strength, "intervention_strength": intervention_strength, "ki": ki },
    }))
}

fn handle_required_strength(args: &Value) -> Value {
    let signal_strength = match get_f64(args, "signal_strength") {
        Some(v) => v,
        None => return err("missing required parameter: signal_strength"),
    };
    let target_reduction = get_f64(args, "target_reduction").unwrap_or(0.5);
    let ki = get_f64(args, "ki").unwrap_or(nexcore_preemptive_pv::intervention::DEFAULT_K_I);
    let k_m = nexcore_preemptive_pv::intervention::DEFAULT_K_M;

    match nexcore_preemptive_pv::intervention::required_intervention_strength(
        signal_strength, 1.0, target_reduction, k_m, ki,
    ) {
        Some(strength) => ok(json!({
            "required_strength": strength,
            "target_reduction_fraction": target_reduction,
            "target_reduction_pct": target_reduction * 100.0,
            "achievable": true,
            "equivalent_intervention": if strength < 5.0 { "Below DHPC" }
                else if strength < 15.0 { "DHPC-level" }
                else if strength < 50.0 { "REMS-level" }
                else { "Withdrawal-level" },
        })),
        None => ok(json!({
            "achievable": false,
            "target_reduction_fraction": target_reduction,
            "message": "Cannot achieve target reduction with competitive inhibition model",
        })),
    }
}

fn handle_omega_table() -> Value {
    let table = nexcore_preemptive_pv::severity::omega_table();
    ok(json!({
        "omega_weights": table.iter().map(|(s, omega)| json!({
            "seriousness": format!("{s:?}"),
            "omega": omega,
            "omega_normalized": nexcore_preemptive_pv::severity::omega_normalized(*s),
            "severity_score": s.severity_score(),
            "irreversibility_factor": s.irreversibility_factor(),
        })).collect::<Vec<_>>(),
        "formula": "Omega = S * (1 + irreversibility_factor)",
    }))
}
