//! Epidemiology — Rust-native handler for NexVigilant Station.
//!
//! Routes `epidemiology_nexvigilant_com_*` tool calls.
//! Pure computation — no external crate deps, all formulas inline.

use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

/// Try to handle an epidemiology tool call. Returns `None` to fall through.
pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("epidemiology_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "relative-risk" => handle_relative_risk(args),
        "odds-ratio" => handle_odds_ratio(args),
        "attributable-risk" => handle_attributable_risk(args),
        "nnt-nnh" => handle_nnt_nnh(args),
        "attributable-fraction" => handle_attributable_fraction(args),
        "population-af" => handle_population_af(args),
        "incidence-rate" => handle_incidence_rate(args),
        "prevalence" => handle_prevalence(args),
        "kaplan-meier" => handle_kaplan_meier(args),
        "smr" => handle_smr(args),
        "pv-mappings" => handle_pv_mappings(),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (epidemiology)");

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

fn get_abcd(args: &Value) -> Option<(f64, f64, f64, f64)> {
    let a = get_f64(args, "a")?;
    let b = get_f64(args, "b")?;
    let c = get_f64(args, "c")?;
    let d = get_f64(args, "d")?;
    if a < 0.0 || b < 0.0 || c < 0.0 || d < 0.0 {
        return None;
    }
    Some((a, b, c, d))
}

// ── 2x2 table tools ────────────────────────────────────────────────────

fn handle_relative_risk(args: &Value) -> Value {
    let (a, b, c, d) = match get_abcd(args) {
        Some(v) => v,
        None => return err("missing or negative a, b, c, d"),
    };
    let risk_exp = a / (a + b);
    let risk_unexp = c / (c + d);
    if risk_unexp == 0.0 {
        return err("unexposed risk is zero, RR undefined");
    }
    let rr = risk_exp / risk_unexp;
    let ln_rr = rr.ln();
    let se = (1.0 / a - 1.0 / (a + b) + 1.0 / c - 1.0 / (c + d)).sqrt();
    let ci_lo = (ln_rr - 1.96 * se).exp();
    let ci_hi = (ln_rr + 1.96 * se).exp();
    let interp = if ci_lo > 1.0 {
        "Significant increased risk"
    } else if ci_hi < 1.0 {
        "Significant decreased risk (protective)"
    } else {
        "Not significant (CI includes 1.0)"
    };

    ok(json!({
        "relative_risk": rr, "risk_exposed": risk_exp, "risk_unexposed": risk_unexp,
        "ci_95_lower": ci_lo, "ci_95_upper": ci_hi, "interpretation": interp,
        "pv_equivalent": "PRR",
    }))
}

fn handle_odds_ratio(args: &Value) -> Value {
    let (a, b, c, d) = match get_abcd(args) {
        Some(v) => v,
        None => return err("missing or negative a, b, c, d"),
    };
    if b * c == 0.0 {
        return err("b*c is zero, OR undefined");
    }
    let or = (a * d) / (b * c);
    let ln_or = or.ln();
    let se = (1.0 / a + 1.0 / b + 1.0 / c + 1.0 / d).sqrt();
    let ci_lo = (ln_or - 1.96 * se).exp();
    let ci_hi = (ln_or + 1.96 * se).exp();
    let interp = if ci_lo > 1.0 {
        "Significant positive association"
    } else if ci_hi < 1.0 {
        "Significant negative association (protective)"
    } else {
        "Not significant (CI includes 1.0)"
    };

    ok(json!({
        "odds_ratio": or, "ci_95_lower": ci_lo, "ci_95_upper": ci_hi,
        "interpretation": interp, "pv_equivalent": "ROR",
    }))
}

fn handle_attributable_risk(args: &Value) -> Value {
    let (a, b, c, d) = match get_abcd(args) {
        Some(v) => v,
        None => return err("missing or negative a, b, c, d"),
    };
    let re = a / (a + b);
    let ru = c / (c + d);
    let ar = re - ru;
    let se = (re * (1.0 - re) / (a + b) + ru * (1.0 - ru) / (c + d)).sqrt();

    ok(json!({
        "attributable_risk": ar, "risk_exposed": re, "risk_unexposed": ru,
        "ci_95_lower": ar - 1.96 * se, "ci_95_upper": ar + 1.96 * se,
        "interpretation": if ar > 0.0 { "Excess risk from exposure" }
            else if ar < 0.0 { "Exposure is protective" }
            else { "No difference" },
    }))
}

fn handle_nnt_nnh(args: &Value) -> Value {
    let (a, b, c, d) = match get_abcd(args) {
        Some(v) => v,
        None => return err("missing or negative a, b, c, d"),
    };
    let ar = a / (a + b) - c / (c + d);
    if ar.abs() < 1e-15 {
        return err("AR is zero, NNT/NNH undefined");
    }
    let value = (1.0 / ar).abs();
    let metric = if ar < 0.0 { "NNT" } else { "NNH" };
    let desc = if ar < 0.0 {
        format!("Treat {value:.1} patients to prevent 1 case")
    } else {
        format!("For every {value:.1} exposed, 1 additional harm")
    };

    ok(json!({ "metric": metric, "value": value, "attributable_risk": ar, "description": desc }))
}

fn handle_attributable_fraction(args: &Value) -> Value {
    let (a, b, c, d) = match get_abcd(args) {
        Some(v) => v,
        None => return err("missing or negative a, b, c, d"),
    };
    let ru = c / (c + d);
    if ru == 0.0 {
        return err("unexposed risk is zero, AF undefined");
    }
    let rr = (a / (a + b)) / ru;
    if rr == 0.0 {
        return err("RR is zero, AF undefined");
    }
    let af = (rr - 1.0) / rr;

    ok(json!({
        "attributable_fraction": af, "relative_risk": rr,
        "interpretation": if af > 0.0 {
            format!("{:.1}% of disease among exposed attributable to exposure", af * 100.0)
        } else {
            format!("Exposure prevents {:.1}% of disease", af.abs() * 100.0)
        },
    }))
}

fn handle_population_af(args: &Value) -> Value {
    let (a, b, c, d) = match get_abcd(args) {
        Some(v) => v,
        None => return err("missing or negative a, b, c, d"),
    };
    let total = a + b + c + d;
    let pe = (a + b) / total;
    let ru = c / (c + d);
    if ru == 0.0 {
        return err("unexposed risk is zero, PAF undefined");
    }
    let rr = (a / (a + b)) / ru;
    let paf = pe * (rr - 1.0) / (1.0 + pe * (rr - 1.0));

    ok(json!({
        "population_attributable_fraction": paf, "prevalence_of_exposure": pe,
        "relative_risk": rr,
        "interpretation": format!("{:.1}% of population disease attributable to exposure", paf * 100.0),
    }))
}

// ── Rate/proportion tools ──────────────────────────────────────────────

fn handle_incidence_rate(args: &Value) -> Value {
    let events = match get_f64(args, "events") {
        Some(v) => v,
        None => return err("missing parameter: events"),
    };
    let pt = match get_f64(args, "person_time") {
        Some(v) if v > 0.0 => v,
        _ => return err("person_time must be positive"),
    };
    let mult = get_f64(args, "multiplier").unwrap_or(1000.0);

    let rate = (events / pt) * mult;
    // Poisson CI (Garwood approximation)
    let z = 1.96;
    let ci_lo = if events > 0.0 {
        let l = events * (1.0 - 1.0 / (9.0 * events) - z / (3.0 * events.sqrt())).powi(3);
        (l.max(0.0) / pt) * mult
    } else {
        0.0
    };
    let ci_hi = {
        let ep = events + 1.0;
        (ep * (1.0 - 1.0 / (9.0 * ep) + z / (3.0 * ep.sqrt())).powi(3) / pt) * mult
    };

    ok(json!({
        "incidence_rate": rate, "events": events, "person_time": pt,
        "multiplier": mult, "ci_95_lower": ci_lo, "ci_95_upper": ci_hi,
        "unit": format!("per {mult} person-time"),
    }))
}

fn handle_prevalence(args: &Value) -> Value {
    let cases = match get_f64(args, "cases") {
        Some(v) => v,
        None => return err("missing parameter: cases"),
    };
    let pop = match get_f64(args, "population") {
        Some(v) if v > 0.0 => v,
        _ => return err("population must be positive"),
    };
    let mult = get_f64(args, "multiplier").unwrap_or(100.0);

    let p = cases / pop;
    let prev = p * mult;
    // Wilson CI
    let z = 1.96;
    let z2 = z * z;
    let denom = 1.0 + z2 / pop;
    let center = (p + z2 / (2.0 * pop)) / denom;
    let margin = z * (p * (1.0 - p) / pop + z2 / (4.0 * pop * pop)).sqrt() / denom;

    ok(json!({
        "prevalence": prev, "proportion": p, "cases": cases, "population": pop,
        "multiplier": mult,
        "ci_95_lower": (center - margin) * mult, "ci_95_upper": (center + margin) * mult,
        "unit": if mult == 100.0 { "percent".to_string() } else { format!("per {mult}") },
    }))
}

// ── Survival & SMR ─────────────────────────────────────────────────────

fn handle_kaplan_meier(args: &Value) -> Value {
    let intervals = match args.get("intervals").and_then(|v| v.as_array()) {
        Some(a) if !a.is_empty() => a,
        _ => return err("need non-empty 'intervals' array [{time, events, censored}, ...]"),
    };

    // Sort by time
    let mut sorted: Vec<_> = intervals.iter().filter_map(|iv| {
        let time = iv.get("time").and_then(|v| v.as_f64())?;
        let events = iv.get("events").and_then(|v| v.as_u64()).unwrap_or(0) as f64;
        let censored = iv.get("censored").and_then(|v| v.as_u64()).unwrap_or(0) as f64;
        Some((time, events, censored))
    }).collect();
    sorted.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));

    let total_events: f64 = sorted.iter().map(|i| i.1).sum();
    let total_censored: f64 = sorted.iter().map(|i| i.2).sum();
    let mut n_at_risk = total_events + total_censored;
    let mut survival = 1.0_f64;
    let mut greenwood_sum = 0.0_f64;
    let mut table = Vec::new();

    for (time, d, c) in &sorted {
        if n_at_risk <= 0.0 { break; }
        let hazard = d / n_at_risk;
        survival *= 1.0 - hazard;

        let gw_term = if n_at_risk > *d { d / (n_at_risk * (n_at_risk - d)) } else { 0.0 };
        greenwood_sum += gw_term;
        let se = survival * greenwood_sum.sqrt();
        let ci_lo = (survival - 1.96 * se).max(0.0);
        let ci_hi = (survival + 1.96 * se).min(1.0);

        table.push(json!({
            "time": time, "n_at_risk": n_at_risk, "events": *d as u64,
            "censored": *c as u64, "hazard": hazard,
            "survival": survival, "se": se,
            "ci_95_lower": ci_lo, "ci_95_upper": ci_hi,
        }));
        n_at_risk -= d + c;
    }

    let median = table.iter()
        .find(|t| t["survival"].as_f64().unwrap_or(1.0) <= 0.5)
        .and_then(|t| t["time"].as_f64());

    ok(json!({
        "survival_table": table, "n_initial": (total_events + total_censored) as u64,
        "total_events": total_events as u64, "total_censored": total_censored as u64,
        "final_survival": survival, "median_survival": median,
    }))
}

fn handle_smr(args: &Value) -> Value {
    let observed = match get_f64(args, "observed") {
        Some(v) => v,
        None => return err("missing parameter: observed"),
    };
    let expected = match get_f64(args, "expected") {
        Some(v) if v > 0.0 => v,
        _ => return err("expected must be positive"),
    };

    let smr = observed / expected;
    // Byar CI
    let ci_lo = if observed > 0.0 {
        let l = observed * (1.0 - 1.0 / (9.0 * observed) - 1.96 / (3.0 * observed.sqrt())).powi(3) / expected;
        l.max(0.0)
    } else {
        0.0
    };
    let ci_hi = {
        let u = observed + 1.0;
        u * (1.0 - 1.0 / (9.0 * u) + 1.96 / (3.0 * u.sqrt())).powi(3) / expected
    };
    let interp = if ci_lo > 1.0 {
        "Significantly more events than expected"
    } else if ci_hi < 1.0 {
        "Significantly fewer events than expected"
    } else {
        "Not significantly different from expected"
    };

    ok(json!({
        "smr": smr, "observed": observed, "expected": expected,
        "ci_95_lower": ci_lo, "ci_95_upper": ci_hi,
        "interpretation": interp, "pv_equivalent": "O/E ratio (EBGM)",
    }))
}

// ── Reference ──────────────────────────────────────────────────────────

fn handle_pv_mappings() -> Value {
    ok(json!({
        "domain": "epidemiology", "target": "pharmacovigilance",
        "overall_transfer_confidence": 0.95,
        "mappings": [
            { "epi": "relative_risk", "pv": "PRR", "formula": "RR = [a/(a+b)]/[c/(c+d)]", "confidence": 0.95 },
            { "epi": "odds_ratio", "pv": "ROR", "formula": "OR = (ad)/(bc)", "confidence": 0.98 },
            { "epi": "attributable_risk", "pv": "excess_signal", "formula": "AR = Ie - Io", "confidence": 0.90 },
            { "epi": "NNT/NNH", "pv": "QBRI denominator", "formula": "1/|AR|", "confidence": 0.85 },
            { "epi": "attributable_fraction", "pv": "signal_contribution", "formula": "(RR-1)/RR", "confidence": 0.88 },
            { "epi": "population_AF", "pv": "population_signal_burden", "formula": "Pe(RR-1)/[1+Pe(RR-1)]", "confidence": 0.85 },
            { "epi": "incidence_rate", "pv": "reporting_rate", "formula": "events/person-time", "confidence": 0.92 },
            { "epi": "prevalence", "pv": "background_rate", "formula": "cases/population", "confidence": 0.90 },
            { "epi": "kaplan_meier", "pv": "TTO survival (Weibull)", "formula": "S(t)=Π[1-d/n]", "confidence": 0.82 },
            { "epi": "SMR", "pv": "O/E ratio (EBGM)", "formula": "observed/expected", "confidence": 0.93 },
        ],
    }))
}
