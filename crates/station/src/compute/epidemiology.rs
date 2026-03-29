//! Epidemiology computation tools — measures of association, impact, and survival.
//!
//! All tools take a 2×2 contingency table (a, b, c, d) or domain-specific params.
//!
//! ```text
//!              Event+    Event-    Total
//!    Drug+       a         b       a+b
//!    Drug-       c         d       c+d
//!    Total      a+c       b+d       N
//! ```

use serde_json::{Value, json};

/// Try to handle an epidemiology tool. Returns `Some(json)` if matched.
pub fn handle(bare_name: &str, args: &Value) -> Option<Value> {
    match bare_name {
        "relative-risk" => Some(relative_risk(args)),
        "odds-ratio" => Some(odds_ratio(args)),
        "attributable-risk" => Some(attributable_risk(args)),
        "nnt-nnh" => Some(nnt_nnh(args)),
        "attributable-fraction" => Some(attributable_fraction(args)),
        "population-attributable-fraction" => Some(population_af(args)),
        "incidence-rate" => Some(incidence_rate(args)),
        "prevalence" => Some(prevalence(args)),
        "kaplan-meier" => Some(kaplan_meier(args)),
        "smr" => Some(smr(args)),
        "mantel-haenszel" => Some(mantel_haenszel(args)),
        "chi-square" => Some(chi_square(args)),
        "power-analysis" => Some(power_analysis(args)),
        "epi-pv-mappings" => Some(epi_pv_mappings()),
        _ => None,
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn get_f64(args: &Value, key: &str) -> Option<f64> {
    args.get(key).and_then(|v| v.as_f64())
}

fn get_f64_or(args: &Value, key: &str, default: f64) -> f64 {
    get_f64(args, key).unwrap_or(default)
}

fn err(msg: &str) -> Value {
    json!({"status": "error", "message": msg})
}

fn extract_2x2(args: &Value) -> Result<(f64, f64, f64, f64), Value> {
    let a = get_f64(args, "a").ok_or_else(|| err("Missing parameter 'a'"))?;
    let b = get_f64(args, "b").ok_or_else(|| err("Missing parameter 'b'"))?;
    let c = get_f64(args, "c").ok_or_else(|| err("Missing parameter 'c'"))?;
    let d = get_f64(args, "d").ok_or_else(|| err("Missing parameter 'd'"))?;
    if a < 0.0 || b < 0.0 || c < 0.0 || d < 0.0 {
        return Err(err("All cell counts must be non-negative"));
    }
    Ok((a, b, c, d))
}

/// Chi-square survival function approximation (upper tail P(X > x) for df degrees).
fn chi_square_p(x: f64, df: usize) -> f64 {
    if x <= 0.0 || df == 0 {
        return 1.0;
    }
    // Regularized incomplete gamma function approximation via Wilson-Hilferty
    let k = df as f64;
    let z = ((x / k).powf(1.0 / 3.0) - (1.0 - 2.0 / (9.0 * k))) / (2.0 / (9.0 * k)).sqrt();
    // Standard normal survival function
    0.5 * erfc(z / std::f64::consts::SQRT_2)
}

/// Complementary error function approximation (Abramowitz & Stegun 7.1.26).
fn erfc(x: f64) -> f64 {
    let t = 1.0 / (1.0 + 0.3275911 * x.abs());
    let poly = t
        * (0.254829592
            + t * (-0.284496736
                + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))));
    let result = poly * (-x * x).exp();
    if x >= 0.0 { result } else { 2.0 - result }
}

// ---------------------------------------------------------------------------
// Tools
// ---------------------------------------------------------------------------

/// RR = [a/(a+b)] / [c/(c+d)]
fn relative_risk(args: &Value) -> Value {
    let (a, b, c, d) = match extract_2x2(args) {
        Ok(v) => v,
        Err(e) => return e,
    };

    let risk_exposed = a / (a + b);
    let risk_unexposed = c / (c + d);

    if risk_unexposed == 0.0 {
        return err("Unexposed risk is zero, RR undefined");
    }

    let rr = risk_exposed / risk_unexposed;
    let ln_rr = rr.ln();
    let se = (1.0 / a - 1.0 / (a + b) + 1.0 / c - 1.0 / (c + d)).sqrt();
    let ci_lower = (ln_rr - 1.96 * se).exp();
    let ci_upper = (ln_rr + 1.96 * se).exp();

    let interpretation = if ci_lower > 1.0 {
        "Statistically significant increased risk"
    } else if ci_upper < 1.0 {
        "Statistically significant decreased risk (protective)"
    } else {
        "Not statistically significant (CI includes 1.0)"
    };

    json!({
        "status": "ok",
        "method": "relative_risk",
        "relative_risk": rr,
        "risk_exposed": risk_exposed,
        "risk_unexposed": risk_unexposed,
        "ci_95_lower": ci_lower,
        "ci_95_upper": ci_upper,
        "interpretation": interpretation,
        "pv_mapping": {
            "pv_equivalent": "PRR (Proportional Reporting Ratio)",
            "confidence": 0.95
        }
    })
}

/// OR = (a×d) / (b×c)
fn odds_ratio(args: &Value) -> Value {
    let (a, b, c, d) = match extract_2x2(args) {
        Ok(v) => v,
        Err(e) => return e,
    };

    if b * c == 0.0 {
        return err("b×c is zero, OR undefined");
    }

    let or = (a * d) / (b * c);
    let ln_or = or.ln();
    let se = (1.0 / a + 1.0 / b + 1.0 / c + 1.0 / d).sqrt();
    let ci_lower = (ln_or - 1.96 * se).exp();
    let ci_upper = (ln_or + 1.96 * se).exp();

    let interpretation = if ci_lower > 1.0 {
        "Statistically significant positive association"
    } else if ci_upper < 1.0 {
        "Statistically significant negative association (protective)"
    } else {
        "Not statistically significant (CI includes 1.0)"
    };

    json!({
        "status": "ok",
        "method": "odds_ratio",
        "odds_ratio": or,
        "ci_95_lower": ci_lower,
        "ci_95_upper": ci_upper,
        "interpretation": interpretation,
        "pv_mapping": {
            "pv_equivalent": "ROR (Reporting Odds Ratio)",
            "confidence": 0.98
        }
    })
}

/// AR = Ie - Io = a/(a+b) - c/(c+d)
fn attributable_risk(args: &Value) -> Value {
    let (a, b, c, d) = match extract_2x2(args) {
        Ok(v) => v,
        Err(e) => return e,
    };

    let re = a / (a + b);
    let ru = c / (c + d);
    let ar = re - ru;
    let se = (re * (1.0 - re) / (a + b) + ru * (1.0 - ru) / (c + d)).sqrt();

    json!({
        "status": "ok",
        "method": "attributable_risk",
        "attributable_risk": ar,
        "risk_exposed": re,
        "risk_unexposed": ru,
        "ci_95_lower": ar - 1.96 * se,
        "ci_95_upper": ar + 1.96 * se,
        "interpretation": if ar > 0.0 { "Excess risk attributable to exposure" }
            else if ar < 0.0 { "Exposure is protective" }
            else { "No difference" }
    })
}

/// NNT = 1/ARR, NNH = 1/ARI
fn nnt_nnh(args: &Value) -> Value {
    let (a, b, c, d) = match extract_2x2(args) {
        Ok(v) => v,
        Err(e) => return e,
    };

    let re = a / (a + b);
    let ru = c / (c + d);
    let ar = re - ru;

    if ar.abs() < 1e-15 {
        return err("Attributable risk is zero, NNT/NNH undefined");
    }

    let value = (1.0 / ar).abs();
    let metric = if ar < 0.0 { "NNT" } else { "NNH" };

    json!({
        "status": "ok",
        "method": "nnt_nnh",
        "metric": metric,
        "value": value,
        "attributable_risk": ar,
        "description": if ar < 0.0 {
            format!("Treat {value:.1} patients to prevent 1 case")
        } else {
            format!("For every {value:.1} exposed, 1 additional harm")
        }
    })
}

/// AF = (RR-1)/RR
fn attributable_fraction(args: &Value) -> Value {
    let (a, b, c, d) = match extract_2x2(args) {
        Ok(v) => v,
        Err(e) => return e,
    };

    let ru = c / (c + d);
    if ru == 0.0 {
        return err("Unexposed risk is zero, AF undefined");
    }
    let rr = (a / (a + b)) / ru;
    if rr == 0.0 {
        return err("RR is zero, AF undefined");
    }
    let af = (rr - 1.0) / rr;

    json!({
        "status": "ok",
        "method": "attributable_fraction",
        "attributable_fraction": af,
        "relative_risk": rr,
        "percent": af * 100.0,
        "interpretation": if af > 0.0 {
            format!("{:.1}% of disease among exposed attributable to exposure", af * 100.0)
        } else {
            format!("Exposure prevents {:.1}% of disease", af.abs() * 100.0)
        }
    })
}

/// PAF = Pe(RR-1) / [1 + Pe(RR-1)]
fn population_af(args: &Value) -> Value {
    let (a, b, c, d) = match extract_2x2(args) {
        Ok(v) => v,
        Err(e) => return e,
    };

    let total = a + b + c + d;
    let pe = (a + b) / total;
    let ru = c / (c + d);
    if ru == 0.0 {
        return err("Unexposed risk is zero, PAF undefined");
    }
    let rr = (a / (a + b)) / ru;
    let paf = pe * (rr - 1.0) / (1.0 + pe * (rr - 1.0));

    json!({
        "status": "ok",
        "method": "population_attributable_fraction",
        "paf": paf,
        "prevalence_of_exposure": pe,
        "relative_risk": rr,
        "percent": paf * 100.0
    })
}

/// IR = events / person-time × multiplier
fn incidence_rate(args: &Value) -> Value {
    let events = match get_f64(args, "events") {
        Some(v) => v,
        None => return err("Missing 'events'"),
    };
    let pt = match get_f64(args, "person_time") {
        Some(v) if v > 0.0 => v,
        _ => return err("Missing or non-positive 'person_time'"),
    };
    let mult = get_f64_or(args, "multiplier", 1000.0);

    let rate = events / pt * mult;

    // Garwood CI approximation
    let ci_lower = if events > 0.0 {
        let z = 1.96;
        let l = events * (1.0 - 1.0 / (9.0 * events) - z / (3.0 * events.sqrt())).powi(3);
        (l.max(0.0) / pt) * mult
    } else {
        0.0
    };
    let ci_upper = {
        let ep = events + 1.0;
        let z = 1.96;
        (ep * (1.0 - 1.0 / (9.0 * ep) + z / (3.0 * ep.sqrt())).powi(3) / pt) * mult
    };

    json!({
        "status": "ok",
        "method": "incidence_rate",
        "incidence_rate": rate,
        "events": events,
        "person_time": pt,
        "multiplier": mult,
        "ci_95_lower": ci_lower,
        "ci_95_upper": ci_upper,
        "unit": format!("per {} person-time", mult)
    })
}

/// P = cases / population × multiplier
fn prevalence(args: &Value) -> Value {
    let cases = match get_f64(args, "cases") {
        Some(v) => v,
        None => return err("Missing 'cases'"),
    };
    let pop = match get_f64(args, "population") {
        Some(v) if v > 0.0 => v,
        _ => return err("Missing or non-positive 'population'"),
    };
    let mult = get_f64_or(args, "multiplier", 100.0);

    let p = cases / pop;
    let scaled = p * mult;

    // Wilson score CI
    let z = 1.96;
    let z2 = z * z;
    let denom = 1.0 + z2 / pop;
    let center = (p + z2 / (2.0 * pop)) / denom;
    let margin = z * (p * (1.0 - p) / pop + z2 / (4.0 * pop * pop)).sqrt() / denom;

    json!({
        "status": "ok",
        "method": "prevalence",
        "prevalence": scaled,
        "proportion": p,
        "cases": cases,
        "population": pop,
        "multiplier": mult,
        "ci_95_lower": (center - margin) * mult,
        "ci_95_upper": (center + margin) * mult,
        "unit": if mult == 100.0 { "percent".to_string() } else { format!("per {mult}") }
    })
}

/// Kaplan-Meier product-limit survival estimator: S(t) = Π[1 - d_i/n_i]
fn kaplan_meier(args: &Value) -> Value {
    let intervals = match args.get("intervals").and_then(|v| v.as_array()) {
        Some(a) if !a.is_empty() => a,
        _ => return err("Missing or empty 'intervals' array"),
    };

    // Parse and sort by time
    let mut data: Vec<(f64, f64, f64)> = intervals
        .iter()
        .filter_map(|v| {
            let t = v.get("time").and_then(|x| x.as_f64())?;
            let e = v.get("events").and_then(|x| x.as_f64()).unwrap_or(0.0);
            let c = v.get("censored").and_then(|x| x.as_f64()).unwrap_or(0.0);
            Some((t, e, c))
        })
        .collect();
    data.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));

    let total_events: f64 = data.iter().map(|(_, e, _)| e).sum();
    let total_censored: f64 = data.iter().map(|(_, _, c)| c).sum();
    let n_initial = total_events + total_censored;
    let mut n_at_risk = n_initial;
    let mut survival = 1.0_f64;
    let mut gw_sum = 0.0_f64;
    let mut table = Vec::new();

    for (time, events, censored) in &data {
        if n_at_risk <= 0.0 {
            break;
        }
        let d = *events;
        let hazard = d / n_at_risk;
        survival *= 1.0 - hazard;

        let gw_term = if n_at_risk > d { d / (n_at_risk * (n_at_risk - d)) } else { 0.0 };
        gw_sum += gw_term;
        let se = if survival > 0.0 { survival * gw_sum.sqrt() } else { 0.0 };

        table.push(json!({
            "time": time,
            "n_at_risk": n_at_risk,
            "events": events,
            "censored": censored,
            "hazard": hazard,
            "survival": survival,
            "se": se,
            "ci_95_lower": (survival - 1.96 * se).max(0.0),
            "ci_95_upper": (survival + 1.96 * se).min(1.0),
        }));

        n_at_risk -= d + censored;
    }

    let median = table
        .iter()
        .find(|t| t["survival"].as_f64().unwrap_or(1.0) <= 0.5)
        .and_then(|t| t["time"].as_f64());

    json!({
        "status": "ok",
        "method": "kaplan_meier",
        "survival_table": table,
        "n_initial": n_initial,
        "total_events": total_events,
        "total_censored": total_censored,
        "final_survival": survival,
        "median_survival": median
    })
}

/// SMR = observed / expected
fn smr(args: &Value) -> Value {
    let observed = match get_f64(args, "observed") {
        Some(v) => v,
        None => return err("Missing 'observed'"),
    };
    let expected = match get_f64(args, "expected") {
        Some(v) if v > 0.0 => v,
        _ => return err("Missing or non-positive 'expected'"),
    };

    let ratio = observed / expected;

    // Byar's CI
    let ci_lower = if observed > 0.0 {
        let l = observed
            * (1.0 - 1.0 / (9.0 * observed) - 1.96 / (3.0 * observed.sqrt())).powi(3)
            / expected;
        l.max(0.0)
    } else {
        0.0
    };
    let ci_upper = {
        let u = observed + 1.0;
        u * (1.0 - 1.0 / (9.0 * u) + 1.96 / (3.0 * u.sqrt())).powi(3) / expected
    };

    json!({
        "status": "ok",
        "method": "smr",
        "smr": ratio,
        "observed": observed,
        "expected": expected,
        "ci_95_lower": ci_lower,
        "ci_95_upper": ci_upper,
        "interpretation": if ci_lower > 1.0 { "Significantly more than expected" }
            else if ci_upper < 1.0 { "Significantly fewer than expected" }
            else { "Not significantly different from expected" }
    })
}

/// Mantel-Haenszel stratified analysis with Breslow-Day homogeneity test.
fn mantel_haenszel(args: &Value) -> Value {
    let strata = match args.get("strata").and_then(|v| v.as_array()) {
        Some(a) if !a.is_empty() => a,
        _ => return err("Missing or empty 'strata' array"),
    };
    let measure = args.get("measure").and_then(|v| v.as_str()).unwrap_or("OR");

    let k = strata.len();
    let mut r_sum = 0.0_f64;
    let mut s_sum = 0.0_f64;
    let mut rbg1 = 0.0_f64;
    let mut rbg2 = 0.0_f64;
    let mut rbg3 = 0.0_f64;
    let mut per_stratum = Vec::new();

    for (i, stratum) in strata.iter().enumerate() {
        let a = get_f64(stratum, "a").unwrap_or(0.0);
        let b = get_f64(stratum, "b").unwrap_or(0.0);
        let c = get_f64(stratum, "c").unwrap_or(0.0);
        let d = get_f64(stratum, "d").unwrap_or(0.0);
        let t = a + b + c + d;
        if t <= 0.0 {
            return err("Stratum has zero total count");
        }

        let r_i = a * d / t;
        let s_i = b * c / t;
        r_sum += r_i;
        s_sum += s_i;

        let p_i = (a + d) / t;
        let q_i = (b + c) / t;
        rbg1 += p_i * r_i;
        rbg2 += p_i * s_i + q_i * r_i;
        rbg3 += q_i * s_i;

        let est = if b * c > 0.0 { (a * d) / (b * c) } else { f64::INFINITY };
        let label = stratum.get("label").and_then(|v| v.as_str()).unwrap_or("");

        per_stratum.push(json!({
            "stratum": i + 1,
            "label": label,
            "a": a, "b": b, "c": c, "d": d,
            "point_estimate": est,
        }));
    }

    if s_sum <= 0.0 {
        return err("MH denominator is zero");
    }

    let mh = r_sum / s_sum;
    let ln_mh = if mh > 0.0 { mh.ln() } else { return err("MH estimate is non-positive"); };

    let var = rbg1 / (2.0 * r_sum * r_sum) + rbg2 / (2.0 * r_sum * s_sum) + rbg3 / (2.0 * s_sum * s_sum);
    let se = var.sqrt();
    let ci_lower = (ln_mh - 1.96 * se).exp();
    let ci_upper = (ln_mh + 1.96 * se).exp();

    // Breslow-Day homogeneity
    let mut bd_chi = 0.0_f64;
    for stratum in strata {
        let a = get_f64(stratum, "a").unwrap_or(0.0);
        let b = get_f64(stratum, "b").unwrap_or(0.0);
        let c = get_f64(stratum, "c").unwrap_or(0.0);
        let d = get_f64(stratum, "d").unwrap_or(0.0);
        let t = a + b + c + d;
        let m1 = a + b;
        let n1 = a + c;

        let qa = 1.0 - mh;
        let qb = (c + d) - n1 + mh * (n1 + m1);
        let qc = -mh * n1 * m1;

        let a_hat = if qa.abs() < 1e-10 {
            if qb.abs() > 1e-10 { -qc / qb } else { a }
        } else {
            let disc = qb * qb - 4.0 * qa * qc;
            if disc < 0.0 { a } else {
                let r1 = (-qb + disc.sqrt()) / (2.0 * qa);
                let lo = (n1 + m1 - t).max(0.0);
                let hi = n1.min(m1);
                if r1 >= lo && r1 <= hi { r1 } else { (-qb - disc.sqrt()) / (2.0 * qa) }
            }
        };

        let b_hat = m1 - a_hat;
        let c_hat = n1 - a_hat;
        let d_hat = t - m1 - n1 + a_hat;

        let var_a = if a_hat > 0.0 && b_hat > 0.0 && c_hat > 0.0 && d_hat > 0.0 {
            1.0 / (1.0 / a_hat + 1.0 / b_hat + 1.0 / c_hat + 1.0 / d_hat)
        } else {
            1.0
        };

        bd_chi += (a - a_hat) * (a - a_hat) / var_a;
    }

    let bd_df = k.saturating_sub(1);
    let bd_p = chi_square_p(bd_chi, bd_df);

    json!({
        "status": "ok",
        "method": "mantel_haenszel",
        "measure": measure,
        "adjusted_estimate": mh,
        "ci_95_lower": ci_lower,
        "ci_95_upper": ci_upper,
        "homogeneity_chi_sq": bd_chi,
        "homogeneity_df": bd_df,
        "homogeneity_p_value": bd_p,
        "heterogeneity_detected": bd_p < 0.05,
        "strata_count": k,
        "per_stratum": per_stratum,
        "interpretation": if ci_lower > 1.0 { "Significant positive association after stratification" }
            else if ci_upper < 1.0 { "Significant negative association after stratification" }
            else { "Not statistically significant (CI includes 1.0)" }
    })
}

/// Pearson chi-square test of independence on a 2×2 table.
fn chi_square(args: &Value) -> Value {
    let (a, b, c, d) = match extract_2x2(args) {
        Ok(v) => v,
        Err(e) => return e,
    };

    let n = a + b + c + d;
    if n == 0.0 {
        return err("Total N is zero");
    }

    // Expected values
    let e_a = (a + b) * (a + c) / n;
    let e_b = (a + b) * (b + d) / n;
    let e_c = (c + d) * (a + c) / n;
    let e_d = (c + d) * (b + d) / n;

    let chi2 = (a - e_a).powi(2) / e_a
        + (b - e_b).powi(2) / e_b
        + (c - e_c).powi(2) / e_c
        + (d - e_d).powi(2) / e_d;

    let p = chi_square_p(chi2, 1);

    // Yates correction
    let yates = (n * ((a * d - b * c).abs() - n / 2.0).powi(2))
        / ((a + b) * (c + d) * (a + c) * (b + d));

    json!({
        "status": "ok",
        "method": "chi_square",
        "chi_square": chi2,
        "chi_square_yates": yates,
        "df": 1,
        "p_value": p,
        "p_value_yates": chi_square_p(yates, 1),
        "significant_at_0_05": p < 0.05,
        "significant_at_0_01": p < 0.01,
        "n": n
    })
}

/// Sample size / power analysis for two-proportion comparison.
fn power_analysis(args: &Value) -> Value {
    let p1 = match get_f64(args, "p1") {
        Some(v) if v > 0.0 && v < 1.0 => v,
        _ => return err("'p1' must be between 0 and 1"),
    };
    let p2 = match get_f64(args, "p2") {
        Some(v) if v > 0.0 && v < 1.0 => v,
        _ => return err("'p2' must be between 0 and 1"),
    };
    let alpha = get_f64_or(args, "alpha", 0.05);
    let power = get_f64_or(args, "power", 0.80);
    let ratio = get_f64_or(args, "ratio", 1.0);

    let z_alpha = z_quantile(1.0 - alpha / 2.0);
    let z_beta = z_quantile(power);

    let p_bar = (p1 + ratio * p2) / (1.0 + ratio);
    let num = (z_alpha * (p_bar * (1.0 - p_bar) * (1.0 + 1.0 / ratio)).sqrt()
        + z_beta * (p1 * (1.0 - p1) + p2 * (1.0 - p2) / ratio).sqrt())
        .powi(2);
    let denom = (p1 - p2).powi(2);

    if denom == 0.0 {
        return err("p1 and p2 are equal, no effect to detect");
    }

    let n1 = (num / denom).ceil();
    let n2 = (n1 * ratio).ceil();

    json!({
        "status": "ok",
        "method": "power_analysis",
        "n_group1": n1,
        "n_group2": n2,
        "n_total": n1 + n2,
        "p1": p1,
        "p2": p2,
        "effect_size": (p1 - p2).abs(),
        "alpha": alpha,
        "power": power,
        "ratio": ratio
    })
}

/// Quantile function for standard normal (rational approximation).
fn z_quantile(p: f64) -> f64 {
    if p <= 0.0 { return f64::NEG_INFINITY; }
    if p >= 1.0 { return f64::INFINITY; }
    if (p - 0.5).abs() < 1e-15 { return 0.0; }

    // Beasley-Springer-Moro approximation
    let a = [
        -3.969683028665376e+01,  2.209460984245205e+02,
        -2.759285104469687e+02,  1.383_577_518_672_69e2,
        -3.066479806614716e+01,  2.506628277459239e+00,
    ];
    let b = [
        -5.447609879822406e+01,  1.615858368580409e+02,
        -1.556989798598866e+02,  6.680131188771972e+01,
        -1.328068155288572e+01,
    ];
    let c = [
        -7.784894002430293e-03, -3.223964580411365e-01,
        -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00,  2.938163982698783e+00,
    ];
    let d = [
        7.784695709041462e-03,  3.224671290700398e-01,
        2.445134137142996e+00,  3.754408661907416e+00,
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

/// All epi → PV transfer mappings reference.
fn epi_pv_mappings() -> Value {
    json!({
        "status": "ok",
        "domain": "epidemiology",
        "target": "pharmacovigilance",
        "overall_transfer_confidence": 0.95,
        "mappings": [
            {"epi": "relative_risk", "pv": "PRR", "confidence": 0.95, "note": "Identical formula"},
            {"epi": "odds_ratio", "pv": "ROR", "confidence": 0.98, "note": "Identical formula"},
            {"epi": "attributable_risk", "pv": "excess_signal", "confidence": 0.90},
            {"epi": "NNT/NNH", "pv": "QBRI", "confidence": 0.85},
            {"epi": "attributable_fraction", "pv": "signal_contribution", "confidence": 0.88},
            {"epi": "PAF", "pv": "population_signal_burden", "confidence": 0.85},
            {"epi": "incidence_rate", "pv": "reporting_rate", "confidence": 0.92},
            {"epi": "prevalence", "pv": "background_rate", "confidence": 0.90},
            {"epi": "kaplan_meier", "pv": "Weibull TTO", "confidence": 0.82},
            {"epi": "SMR", "pv": "O/E ratio (EBGM)", "confidence": 0.93},
        ]
    })
}
