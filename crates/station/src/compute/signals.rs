//! Signal detection computation tools — PRR, ROR, IC, EBGM, disproportionality.
//!
//! All methods use the standard 2×2 contingency table:
//!
//! ```text
//!              Event+    Event-    Total
//!    Drug+       a         b       a+b
//!    Drug-       c         d       c+d
//! ```

use serde_json::{Value, json};

pub fn handle(bare_name: &str, args: &Value) -> Option<Value> {
    match bare_name {
        "prr" | "compute-prr" => Some(prr(args)),
        "ror" | "compute-ror" => Some(ror(args)),
        "ic" | "compute-ic" => Some(ic(args)),
        "ebgm" | "compute-ebgm" => Some(ebgm(args)),
        "disproportionality-table" | "compute-disproportionality-table" => Some(disproportionality_table(args)),
        "signal-strength" | "compute-signal-strength" => Some(signal_strength(args)),
        "reporting-rate" | "compute-reporting-rate" => Some(reporting_rate(args)),
        "signal-half-life" | "compute-signal-half-life" => Some(signal_half_life(args)),
        "signal-trend" | "compute-signal-trend" => Some(signal_trend(args)),
        "expectedness" | "compute-expectedness" => Some(expectedness(args)),
        "time-to-onset" | "compute-time-to-onset" => Some(time_to_onset(args)),
        "batch-signals" | "compute-batch-signals" => Some(batch_signals(args)),
        _ => None,
    }
}

fn get_f64(args: &Value, key: &str) -> Option<f64> {
    args.get(key).and_then(|v| v.as_f64())
}

fn err(msg: &str) -> Value {
    json!({"status": "error", "message": msg})
}

fn extract_2x2(args: &Value) -> Result<(f64, f64, f64, f64), Value> {
    let a = get_f64(args, "a").ok_or_else(|| err("Missing 'a'"))?;
    let b = get_f64(args, "b").ok_or_else(|| err("Missing 'b'"))?;
    let c = get_f64(args, "c").ok_or_else(|| err("Missing 'c'"))?;
    let d = get_f64(args, "d").ok_or_else(|| err("Missing 'd'"))?;
    if a < 0.0 || b < 0.0 || c < 0.0 || d < 0.0 {
        return Err(err("All cell counts must be non-negative"));
    }
    Ok((a, b, c, d))
}

/// PRR = [a/(a+b)] / [c/(c+d)]  (Evans et al., 2001)
fn prr(args: &Value) -> Value {
    let (a, b, c, d) = match extract_2x2(args) {
        Ok(v) => v,
        Err(e) => return e,
    };

    let n = a + b + c + d;
    if (a + b) == 0.0 || (c + d) == 0.0 || c == 0.0 {
        return json!({"status": "ok", "method": "PRR", "prr": null, "signal": "insufficient_data",
            "contingency_table": {"a": a, "b": b, "c": c, "d": d, "N": n}});
    }

    let drug_rate = a / (a + b);
    let bg_rate = c / (c + d);
    let prr = drug_rate / bg_rate;

    let (ci_lower, ci_upper) = if prr > 0.0 && a > 0.0 {
        let ln_prr = prr.ln();
        let se = (1.0 / a - 1.0 / (a + b) + 1.0 / c - 1.0 / (c + d)).sqrt();
        ((ln_prr - 1.96 * se).exp(), (ln_prr + 1.96 * se).exp())
    } else {
        (0.0, f64::INFINITY)
    };

    // Chi-square for signal threshold
    let e_a = (a + b) * (a + c) / n;
    let chi2 = if e_a > 0.0 { (a - e_a).powi(2) / e_a } else { 0.0 };

    let signal = prr >= 2.0 && chi2 >= 4.0 && a >= 3.0;

    json!({
        "status": "ok",
        "method": "PRR",
        "prr": prr,
        "ci_95_lower": ci_lower,
        "ci_95_upper": ci_upper,
        "drug_reporting_rate": drug_rate,
        "background_rate": bg_rate,
        "chi_square": chi2,
        "case_count": a,
        "signal": signal,
        "signal_criteria": {
            "prr_gte_2": prr >= 2.0,
            "chi2_gte_4": chi2 >= 4.0,
            "n_gte_3": a >= 3.0
        },
        "contingency_table": {"a": a, "b": b, "c": c, "d": d, "N": n},
        "reference": "Evans SJW et al. (2001) Pharmacoepidemiology and Drug Safety"
    })
}

/// ROR = (a×d) / (b×c)
fn ror(args: &Value) -> Value {
    let (a, b, c, d) = match extract_2x2(args) {
        Ok(v) => v,
        Err(e) => return e,
    };

    if b * c == 0.0 {
        return err("b×c is zero, ROR undefined");
    }

    let ror = (a * d) / (b * c);
    let ln_ror = ror.ln();
    let se = (1.0 / a + 1.0 / b + 1.0 / c + 1.0 / d).sqrt();
    let ci_lower = (ln_ror - 1.96 * se).exp();
    let ci_upper = (ln_ror + 1.96 * se).exp();

    let signal = ci_lower > 1.0;

    json!({
        "status": "ok",
        "method": "ROR",
        "ror": ror,
        "ci_95_lower": ci_lower,
        "ci_95_upper": ci_upper,
        "signal": signal,
        "signal_criterion": "Lower 95% CI > 1.0",
        "contingency_table": {"a": a, "b": b, "c": c, "d": d, "N": a+b+c+d},
        "reference": "Rothman KJ et al., case-control method adapted for spontaneous reports"
    })
}

/// IC = log2(a/E) where E = (a+b)(a+c)/N  (Bate et al., 1998)
fn ic(args: &Value) -> Value {
    let (a, b, c, d) = match extract_2x2(args) {
        Ok(v) => v,
        Err(e) => return e,
    };

    let n = a + b + c + d;
    let expected = (a + b) * (a + c) / n;

    if expected <= 0.0 {
        return err("Expected count is zero, IC undefined");
    }

    let ic = (a / expected).log2();

    // IC with credibility interval (Bayesian shrinkage approximation)
    // Using Norén et al. (2006) approach
    let gamma = 0.5; // shrinkage prior
    let a_shrunk = a + gamma;
    let e_shrunk = expected + gamma;
    let ic_shrunk = (a_shrunk / e_shrunk).log2();
    let var_ic = 1.0 / (a_shrunk * 2.0_f64.ln().powi(2));
    let se_ic = var_ic.sqrt();
    let ic025 = ic_shrunk - 1.96 * se_ic;
    let ic975 = ic_shrunk + 1.96 * se_ic;

    let signal = ic025 > 0.0;

    json!({
        "status": "ok",
        "method": "IC (Information Component)",
        "ic": ic,
        "ic_shrunk": ic_shrunk,
        "ic_025": ic025,
        "ic_975": ic975,
        "observed": a,
        "expected": expected,
        "signal": signal,
        "signal_criterion": "IC025 > 0 (lower credibility interval)",
        "contingency_table": {"a": a, "b": b, "c": c, "d": d, "N": n},
        "reference": "Bate A et al. (1998), WHO-UMC; Norén GN et al. (2006)"
    })
}

/// EBGM = a/E with empirical Bayesian geometric mean (DuMouchel, 1999)
fn ebgm(args: &Value) -> Value {
    let (a, b, c, d) = match extract_2x2(args) {
        Ok(v) => v,
        Err(e) => return e,
    };

    let n = a + b + c + d;
    let expected = (a + b) * (a + c) / n;

    if expected <= 0.0 {
        return err("Expected count is zero, EBGM undefined");
    }

    let rr = a / expected;

    // Two-component mixture model approximation
    // Parameters from DuMouchel (1999) defaults
    let alpha1 = 0.2;
    let beta1 = 0.1;
    let alpha2 = 2.0;
    let beta2 = 4.0;
    let p_mix = 0.1; // mixing parameter

    // Posterior using gamma-Poisson conjugacy
    let post_alpha1 = alpha1 + a;
    let post_beta1 = beta1 + expected;
    let post_alpha2 = alpha2 + a;
    let post_beta2 = beta2 + expected;

    // Weights (simplified — full requires marginal likelihood)
    let w1 = p_mix;
    let w2 = 1.0 - p_mix;

    // EBGM = geometric mean of posterior
    let log_ebgm = w1 * (digamma(post_alpha1) - post_beta1.ln())
        + w2 * (digamma(post_alpha2) - post_beta2.ln());
    let ebgm = log_ebgm.exp();

    // EB05 and EB95 (5th and 95th percentiles of posterior)
    // Approximation using gamma quantiles
    let eb05 = gamma_quantile(0.05, post_alpha2, post_beta2);
    let eb95 = gamma_quantile(0.95, post_alpha1, post_beta1);

    let signal = eb05 > 1.0;

    json!({
        "status": "ok",
        "method": "EBGM (Empirical Bayesian Geometric Mean)",
        "ebgm": ebgm,
        "eb05": eb05,
        "eb95": eb95,
        "rr": rr,
        "observed": a,
        "expected": expected,
        "signal": signal,
        "signal_criterion": "EB05 > 1.0 (5th percentile of posterior)",
        "contingency_table": {"a": a, "b": b, "c": c, "d": d, "N": n},
        "reference": "DuMouchel W (1999) Am Stat"
    })
}

/// Digamma approximation (Bernardo 1976).
fn digamma(x: f64) -> f64 {
    if x <= 0.0 { return f64::NEG_INFINITY; }
    let mut result = 0.0;
    let mut val = x;
    // Shift to large argument
    while val < 6.0 {
        result -= 1.0 / val;
        val += 1.0;
    }
    // Asymptotic expansion
    result += val.ln() - 1.0 / (2.0 * val);
    let inv2 = 1.0 / (val * val);
    result -= inv2 * (1.0 / 12.0 - inv2 * (1.0 / 120.0 - inv2 / 252.0));
    result
}

/// Gamma distribution quantile approximation (Wilson-Hilferty).
fn gamma_quantile(p: f64, alpha: f64, beta: f64) -> f64 {
    if alpha <= 0.0 || beta <= 0.0 { return 0.0; }
    // Wilson-Hilferty normal approximation to gamma quantile
    let z = z_quantile(p);
    let term = 1.0 - 2.0 / (9.0 * alpha) + z * (2.0 / (9.0 * alpha)).sqrt();
    let x = alpha * term.powi(3).max(0.0);
    x / beta
}

/// Standard normal quantile (Beasley-Springer-Moro).
fn z_quantile(p: f64) -> f64 {
    if p <= 0.0 { return f64::NEG_INFINITY; }
    if p >= 1.0 { return f64::INFINITY; }
    let a = [
        -3.969683028665376e+01, 2.209460984245205e+02,
        -2.759285104469687e+02, 1.383577518672690e+02,
        -3.066479806614716e+01, 2.506628277459239e+00,
    ];
    let b = [
        -5.447609879822406e+01, 1.615858368580409e+02,
        -1.556989798598866e+02, 6.680131188771972e+01,
        -1.328068155288572e+01,
    ];
    let c = [
        -7.784894002430293e-03, -3.223964580411365e-01,
        -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00,
    ];
    let d = [
        7.784695709041462e-03, 3.224671290700398e-01,
        2.445134137142996e+00, 3.754408661907416e+00,
    ];
    let p_low = 0.02425;
    let p_high = 1.0 - p_low;
    if p < p_low {
        let q = (-2.0 * p.ln()).sqrt();
        (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
        ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)
    } else if p <= p_high {
        let q = p - 0.5;
        let r = q * q;
        (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q /
        (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1.0)
    } else {
        let q = (-2.0 * (1.0 - p).ln()).sqrt();
        -((((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
        ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0))
    }
}

/// Full disproportionality table — all four methods at once.
fn disproportionality_table(args: &Value) -> Value {
    let (a, b, c, d) = match extract_2x2(args) {
        Ok(v) => v,
        Err(e) => return e,
    };

    let prr_result = prr(args);
    let ror_result = ror(args);
    let ic_result = ic(args);
    let ebgm_result = ebgm(args);

    let any_signal = [&prr_result, &ror_result, &ic_result, &ebgm_result]
        .iter()
        .any(|r| r.get("signal").and_then(|s| s.as_bool()).unwrap_or(false));

    let signal_count = [&prr_result, &ror_result, &ic_result, &ebgm_result]
        .iter()
        .filter(|r| r.get("signal").and_then(|s| s.as_bool()).unwrap_or(false))
        .count();

    json!({
        "status": "ok",
        "method": "disproportionality_table",
        "contingency_table": {"a": a, "b": b, "c": c, "d": d, "N": a+b+c+d},
        "prr": {
            "value": prr_result.get("prr"),
            "ci_lower": prr_result.get("ci_95_lower"),
            "ci_upper": prr_result.get("ci_95_upper"),
            "signal": prr_result.get("signal"),
        },
        "ror": {
            "value": ror_result.get("ror"),
            "ci_lower": ror_result.get("ci_95_lower"),
            "ci_upper": ror_result.get("ci_95_upper"),
            "signal": ror_result.get("signal"),
        },
        "ic": {
            "value": ic_result.get("ic"),
            "ic025": ic_result.get("ic_025"),
            "ic975": ic_result.get("ic_975"),
            "signal": ic_result.get("signal"),
        },
        "ebgm": {
            "value": ebgm_result.get("ebgm"),
            "eb05": ebgm_result.get("eb05"),
            "eb95": ebgm_result.get("eb95"),
            "signal": ebgm_result.get("signal"),
        },
        "any_signal": any_signal,
        "signal_count": signal_count,
        "signals_detected": signal_count,
        "consensus": if signal_count >= 3 { "strong" }
            else if signal_count >= 2 { "moderate" }
            else if signal_count >= 1 { "weak" }
            else { "none" },
        "consensus_signal": if signal_count >= 3 { "strong_signal" }
            else if signal_count >= 2 { "moderate_signal" }
            else if signal_count >= 1 { "weak_signal" }
            else { "no_signal" }
    })
}

/// Signal strength score (0-100) based on multi-method agreement.
fn signal_strength(args: &Value) -> Value {
    let table = disproportionality_table(args);
    if table.get("status").and_then(|s| s.as_str()) == Some("error") {
        return table;
    }

    let prr_val = table.pointer("/prr/value").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let ror_val = table.pointer("/ror/value").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let ic_val = table.pointer("/ic/value").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let ebgm_val = table.pointer("/ebgm/value").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let signal_count = table.get("signal_count").and_then(|v| v.as_u64()).unwrap_or(0);

    // Scoring: method agreement (40%) + magnitude (40%) + case count (20%)
    let agreement_score = signal_count as f64 * 25.0; // 0-100
    let magnitude_score = {
        let prr_s = ((prr_val - 1.0).max(0.0) / 9.0).min(1.0) * 100.0;
        let ror_s = ((ror_val - 1.0).max(0.0) / 9.0).min(1.0) * 100.0;
        let ic_s = (ic_val.max(0.0) / 3.0).min(1.0) * 100.0;
        let ebgm_s = ((ebgm_val - 1.0).max(0.0) / 4.0).min(1.0) * 100.0;
        (prr_s + ror_s + ic_s + ebgm_s) / 4.0
    };
    let a = get_f64(args, "a").unwrap_or(0.0);
    let count_score = ((a / 10.0).min(1.0)) * 100.0;

    let total = agreement_score * 0.4 + magnitude_score * 0.4 + count_score * 0.2;

    json!({
        "status": "ok",
        "method": "signal_strength",
        "score": total,
        "components": {
            "agreement": agreement_score,
            "magnitude": magnitude_score,
            "case_count": count_score,
            "weights": {"agreement": 0.4, "magnitude": 0.4, "case_count": 0.2}
        },
        "grade": if total >= 75.0 { "strong" }
            else if total >= 50.0 { "moderate" }
            else if total >= 25.0 { "weak" }
            else { "no_signal" },
        "signal_count": signal_count
    })
}

/// Reporting rate = cases / exposure × multiplier
fn reporting_rate(args: &Value) -> Value {
    let cases = match get_f64(args, "cases") {
        Some(v) => v,
        None => return err("Missing 'cases'"),
    };
    let exposure = match get_f64(args, "exposure") {
        Some(v) if v > 0.0 => v,
        _ => return err("Missing or non-positive 'exposure'"),
    };
    let mult = get_f64(args, "multiplier").unwrap_or(100000.0);

    let rate = cases / exposure * mult;

    json!({
        "status": "ok",
        "method": "reporting_rate",
        "rate": rate,
        "cases": cases,
        "exposure": exposure,
        "multiplier": mult,
        "unit": format!("per {} patient-exposures", mult)
    })
}

/// Signal half-life: time for PRR to decay by 50%.
///
/// Two input modes:
/// 1. Direct: `{initial_signal_strength, decay_rate}` → exponential decay formula
/// 2. Time-series: `{periods: [{time, prr}]}` → log-linear regression
fn signal_half_life(args: &Value) -> Value {
    // Mode 1: Direct exponential decay parameters (Python proxy compatibility)
    if let (Some(initial), Some(decay_rate)) = (
        get_f64(args, "initial_signal_strength"),
        get_f64(args, "decay_rate"),
    ) {
        if decay_rate <= 0.0 {
            return err("decay_rate must be positive");
        }
        let half_life = 0.693147 / decay_rate;
        let threshold = get_f64(args, "detection_threshold").unwrap_or(1.0);
        let months_until = if initial > threshold && decay_rate > 0.0 {
            (initial / threshold).ln() / decay_rate
        } else {
            0.0
        };
        let mut projections = serde_json::Map::new();
        for months in [6.0, 12.0, 24.0] {
            let value = initial * (-decay_rate * months).exp();
            projections.insert(
                format!("{}_months", months as u32),
                json!({"value": (value * 10000.0).round() / 10000.0, "above_threshold": value > threshold}),
            );
        }
        return json!({
            "status": "ok",
            "method": "signal_half_life",
            "half_life_months": (half_life * 100.0).round() / 100.0,
            "months_until_undetectable": (months_until * 100.0).round() / 100.0,
            "initial_signal_strength": initial,
            "decay_rate": decay_rate,
            "detection_threshold": threshold,
            "projections": projections
        });
    }

    // Mode 2: Time-series regression
    let periods = match args.get("periods").and_then(|v| v.as_array()) {
        Some(a) if a.len() >= 2 => a,
        _ => return err("Need 'initial_signal_strength' + 'decay_rate', or 'periods' array with 'time' and 'prr' fields"),
    };

    let data: Vec<(f64, f64)> = periods
        .iter()
        .filter_map(|v| {
            let t = v.get("time").and_then(|x| x.as_f64())?;
            let p = v.get("prr").and_then(|x| x.as_f64())?;
            Some((t, p))
        })
        .collect();

    if data.len() < 2 {
        return err("Need at least 2 valid data points");
    }

    // Log-linear regression: ln(PRR) = a + b*t → half-life = -ln(2)/b
    let n = data.len() as f64;
    let sum_t: f64 = data.iter().map(|(t, _)| t).sum();
    let sum_ln_p: f64 = data.iter().map(|(_, p)| p.ln()).sum();
    let sum_t2: f64 = data.iter().map(|(t, _)| t * t).sum();
    let sum_t_ln_p: f64 = data.iter().map(|(t, p)| t * p.ln()).sum();

    let denom = n * sum_t2 - sum_t * sum_t;
    if denom.abs() < 1e-15 {
        return err("Cannot fit decay model (degenerate data)");
    }

    let slope = (n * sum_t_ln_p - sum_t * sum_ln_p) / denom;

    if slope >= 0.0 {
        return json!({
            "status": "ok",
            "method": "signal_half_life",
            "half_life": null,
            "trend": "increasing_or_stable",
            "slope": slope,
            "message": "Signal is not decaying — no half-life applicable"
        });
    }

    let half_life = -0.693147 / slope;

    json!({
        "status": "ok",
        "method": "signal_half_life",
        "half_life": half_life,
        "trend": "decaying",
        "slope": slope,
        "data_points": data.len(),
        "unit": "same unit as input time"
    })
}

/// Signal trend: linear regression on time-series PRR/count data.
fn signal_trend(args: &Value) -> Value {
    let periods = match args.get("periods").and_then(|v| v.as_array()) {
        Some(a) if a.len() >= 2 => a,
        _ => return err("Need at least 2 periods"),
    };

    let data: Vec<(f64, f64)> = periods
        .iter()
        .filter_map(|v| {
            let t = v.get("time").and_then(|x| x.as_f64())?;
            let val = v.get("value").and_then(|x| x.as_f64())?;
            Some((t, val))
        })
        .collect();

    if data.len() < 2 {
        return err("Need at least 2 valid data points");
    }

    let n = data.len() as f64;
    let sum_x: f64 = data.iter().map(|(t, _)| t).sum();
    let sum_y: f64 = data.iter().map(|(_, v)| v).sum();
    let sum_xy: f64 = data.iter().map(|(t, v)| t * v).sum();
    let sum_x2: f64 = data.iter().map(|(t, _)| t * t).sum();

    let denom = n * sum_x2 - sum_x * sum_x;
    if denom.abs() < 1e-15 {
        return err("Degenerate data");
    }

    let slope = (n * sum_xy - sum_x * sum_y) / denom;
    let intercept = (sum_y - slope * sum_x) / n;

    // R-squared
    let mean_y = sum_y / n;
    let ss_tot: f64 = data.iter().map(|(_, v)| (v - mean_y).powi(2)).sum();
    let ss_res: f64 = data.iter().map(|(t, v)| (v - intercept - slope * t).powi(2)).sum();
    let r2 = if ss_tot > 0.0 { 1.0 - ss_res / ss_tot } else { 0.0 };

    let trend = if slope.abs() < 1e-6 { "stable" }
        else if slope > 0.0 { "increasing" }
        else { "decreasing" };

    json!({
        "status": "ok",
        "method": "signal_trend",
        "slope": slope,
        "intercept": intercept,
        "r_squared": r2,
        "trend": trend,
        "data_points": data.len()
    })
}

/// Expectedness classification: is this AE listed in the label?
fn expectedness(args: &Value) -> Value {
    let listed = args.get("listed_in_label").and_then(|v| v.as_bool()).unwrap_or(false);
    let listed_class = args.get("listed_in_class_label").and_then(|v| v.as_bool()).unwrap_or(false);
    let mechanistic = args.get("mechanistic_plausibility").and_then(|v| v.as_bool()).unwrap_or(false);

    let classification = if listed { "expected" }
        else if listed_class { "expected_for_class" }
        else if mechanistic { "plausible_unexpected" }
        else { "unexpected" };

    let regulatory_impact = match classification {
        "unexpected" => "Requires expedited reporting (15 calendar days for serious)",
        "expected" => "Routine periodic reporting (PSUR/PBRER)",
        "expected_for_class" => "Enhanced monitoring recommended",
        "plausible_unexpected" => "Signal evaluation recommended",
        _ => "Unknown",
    };

    json!({
        "status": "ok",
        "method": "expectedness",
        "classification": classification,
        "listed_in_label": listed,
        "listed_in_class_label": listed_class,
        "mechanistic_plausibility": mechanistic,
        "regulatory_impact": regulatory_impact,
        "reference": "ICH E2A, ICH E2D"
    })
}

/// Time-to-onset analysis: Weibull shape parameter from onset data.
fn time_to_onset(args: &Value) -> Value {
    let times = match args.get("onset_times").and_then(|v| v.as_array()) {
        Some(a) if !a.is_empty() => a,
        _ => return err("Missing or empty 'onset_times' array"),
    };

    let data: Vec<f64> = times.iter().filter_map(|v| v.as_f64()).filter(|v| *v > 0.0).collect();
    if data.is_empty() {
        return err("No valid positive onset times");
    }

    let n = data.len() as f64;
    let mean: f64 = data.iter().sum::<f64>() / n;
    let median = {
        let mut sorted = data.clone();
        sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        if sorted.len() % 2 == 0 {
            (sorted[sorted.len() / 2 - 1] + sorted[sorted.len() / 2]) / 2.0
        } else {
            sorted[sorted.len() / 2]
        }
    };
    let variance: f64 = data.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / n;
    let sd = variance.sqrt();
    let cv = if mean > 0.0 { sd / mean } else { 0.0 };

    // Weibull shape parameter estimate (method of moments)
    let shape = if cv > 0.0 { 1.0 / cv } else { 1.0 };
    // Weibull scale (approximate)
    let scale = mean;

    let pattern = if shape > 1.5 { "wear-out (increasing hazard)" }
        else if shape > 0.8 { "random (constant hazard)" }
        else { "early-onset (decreasing hazard)" };

    json!({
        "status": "ok",
        "method": "time_to_onset",
        "n": data.len(),
        "mean_days": mean,
        "median_days": median,
        "sd_days": sd,
        "cv": cv,
        "weibull_shape": shape,
        "weibull_scale": scale,
        "onset_pattern": pattern,
        "quartiles": {
            "q25": percentile(&data, 25.0),
            "q50": median,
            "q75": percentile(&data, 75.0),
        }
    })
}

fn percentile(data: &[f64], p: f64) -> f64 {
    let mut sorted = data.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let idx = (p / 100.0 * (sorted.len() - 1) as f64).round() as usize;
    sorted[idx.min(sorted.len() - 1)]
}

/// Batch signal detection: run PRR+ROR+IC+EBGM on multiple drug-event pairs at once.
fn batch_signals(args: &Value) -> Value {
    let pairs = match args.get("pairs").and_then(|v| v.as_array()) {
        Some(a) if !a.is_empty() => a,
        _ => return err("Missing or empty 'pairs' array. Each element needs a, b, c, d fields."),
    };

    if pairs.len() > 100 {
        return err("Maximum 100 pairs per batch");
    }

    let mut results = Vec::new();
    let mut signal_count = 0_usize;

    for (i, pair) in pairs.iter().enumerate() {
        let label = pair.get("label")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        let table_result = disproportionality_table(pair);
        let is_signal = table_result.get("any_signal")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);

        if is_signal {
            signal_count += 1;
        }

        results.push(json!({
            "index": i,
            "label": label,
            "any_signal": is_signal,
            "consensus": table_result.get("consensus"),
            "signal_count": table_result.get("signal_count"),
            "prr": table_result.pointer("/prr/value"),
            "ror": table_result.pointer("/ror/value"),
            "ic": table_result.pointer("/ic/value"),
            "ebgm": table_result.pointer("/ebgm/value"),
        }));
    }

    json!({
        "status": "ok",
        "method": "batch_signals",
        "total_pairs": pairs.len(),
        "signals_detected": signal_count,
        "signal_rate": signal_count as f64 / pairs.len() as f64,
        "results": results,
    })
}
