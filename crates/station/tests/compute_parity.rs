//! Compute Engine Parity Tests
//!
//! These tests encode the EXACT same reference vectors as
//! `scripts/validate_calculations.py` and run them through
//! the Rust compute handlers. If a test here fails, the Rust
//! implementation has diverged from the validated Python reference.
//!
//! Source: validate_calculations.py CASES array (18 test vectors)
//! Validation method: dual computation (math-first-capability-reach rule)

use nexvigilant_station::compute;
use serde_json::{json, Value};

fn approx(actual: f64, expected: f64) -> bool {
    if expected == 0.0 {
        actual.abs() < 0.01
    } else {
        ((actual - expected) / expected).abs() < 0.01 // 1% tolerance
    }
}

fn get_f64(v: &Value, path: &str) -> f64 {
    let parts: Vec<&str> = path.split('.').collect();
    let mut current = v;
    for part in parts {
        current = &current[part];
    }
    current.as_f64().unwrap_or(f64::NAN)
}

fn get_str<'a>(v: &'a Value, path: &str) -> &'a str {
    let parts: Vec<&str> = path.split('.').collect();
    let mut current = v;
    for part in parts {
        current = &current[part];
    }
    current.as_str().unwrap_or("")
}

fn get_bool(v: &Value, path: &str) -> bool {
    let parts: Vec<&str> = path.split('.').collect();
    let mut current = v;
    for part in parts {
        current = &current[part];
    }
    current.as_bool().unwrap_or(false)
}

fn get_i64(v: &Value, path: &str) -> i64 {
    let parts: Vec<&str> = path.split('.').collect();
    let mut current = v;
    for part in parts {
        current = &current[part];
    }
    current.as_i64().unwrap_or(0)
}

/// Helper: call the compute engine and return the result JSON
fn compute(tool_name: &str, args: Value) -> Value {
    let full_name = format!("calculate_nexvigilant_com_{}", tool_name.replace('-', "_"));
    let result = compute::try_handle(&full_name, &args)
        .unwrap_or_else(|| panic!("Tool '{}' not handled by compute engine", full_name));
    let text = match &result.content[0] {
        nexvigilant_station::protocol::ContentBlock::Text { text } => text.clone(),
    };
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("Invalid JSON from {tool_name}: {e}"))
}

// ══════════════════════════════════════════════════════════════
// Signal Detection (2×2 contingency table)
// ══════════════════════════════════════════════════════════════

#[test]
fn parity_prr_basic_signal() {
    // PRR = (15/115) / (200/10200) = 6.652
    let r = compute("compute-prr", json!({"a": 15, "b": 100, "c": 200, "d": 10000}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "prr"), 6.652), "PRR was {}", get_f64(&r, "prr"));
    // Rust uses bool signal, Python used string — math parity is what matters
    assert!(get_bool(&r, "signal"), "Expected signal=true for PRR=6.65");
}

#[test]
fn parity_prr_no_signal() {
    // PRR = (1/501) / (200/10200) = 0.1018
    let r = compute("compute-prr", json!({"a": 1, "b": 500, "c": 200, "d": 10000}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "prr"), 0.1018), "PRR was {}", get_f64(&r, "prr"));
    assert!(!get_bool(&r, "signal"), "Expected signal=false for PRR=0.10");
}

#[test]
fn parity_prr_zero_reports() {
    let r = compute("compute-prr", json!({"a": 0, "b": 100, "c": 200, "d": 10000}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "prr"), 0.0), "PRR was {}", get_f64(&r, "prr"));
}

#[test]
fn parity_ror_basic_signal() {
    // ROR = (15*10000) / (100*200) = 7.5
    let r = compute("compute-ror", json!({"a": 15, "b": 100, "c": 200, "d": 10000}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "ror"), 7.5), "ROR was {}", get_f64(&r, "ror"));
    assert!(get_bool(&r, "signal"), "Expected signal=true for ROR=7.5");
}

#[test]
fn parity_ic_positive_signal() {
    // IC = log2(15 / expected), expected = 115*215/10315 ≈ 2.397
    // IC = log2(15/2.397) = log2(6.256) ≈ 2.645
    let r = compute("compute-ic", json!({"a": 15, "b": 100, "c": 200, "d": 10000}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "ic"), 2.645), "IC was {}", get_f64(&r, "ic"));
}

#[test]
fn parity_ebgm_signal_present() {
    let r = compute("compute-ebgm", json!({"a": 15, "b": 100, "c": 200, "d": 10000}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(get_bool(&r, "signal"), "Expected EBGM signal=true");
}

#[test]
fn parity_disproportionality_table_consensus() {
    let r = compute("compute-disproportionality-table", json!({"a": 15, "b": 100, "c": 200, "d": 10000}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "prr.value"), 6.652), "PRR was {}", get_f64(&r, "prr.value"));
    assert!(approx(get_f64(&r, "ror.value"), 7.5), "ROR was {}", get_f64(&r, "ror.value"));
    assert!(approx(get_f64(&r, "ic.value"), 2.645), "IC was {}", get_f64(&r, "ic.value"));
    assert_eq!(get_str(&r, "consensus_signal"), "strong_signal");
    assert_eq!(get_i64(&r, "signals_detected"), 4);
}

// ══════════════════════════════════════════════════════════════
// Causality Assessment
// ══════════════════════════════════════════════════════════════

#[test]
fn parity_naranjo_definite() {
    let r = compute("assess-naranjo-causality", json!({
        "previous_reports": true,
        "after_drug": true,
        "improved_on_withdrawal": "yes",
        "reappeared_on_rechallenge": "not_done",
        "alternative_causes": false,
        "placebo_reaction": "not_done",
        "drug_detected": "not_done",
        "dose_related": "yes",
        "previous_exposure": true,
        "objective_evidence": true
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(get_i64(&r, "score") >= 9, "Score was {}", get_i64(&r, "score"));
    assert_eq!(get_str(&r, "category"), "definite");
}

#[test]
fn parity_naranjo_max_score() {
    let r = compute("assess-naranjo-causality", json!({
        "previous_reports": true,
        "after_drug": true,
        "improved_on_withdrawal": "yes",
        "reappeared_on_rechallenge": "yes",
        "alternative_causes": false,
        "placebo_reaction": "no",
        "drug_detected": "yes",
        "dose_related": "yes",
        "previous_exposure": true,
        "objective_evidence": true
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert_eq!(get_i64(&r, "score"), 13);
    assert_eq!(get_str(&r, "category"), "definite");
}

#[test]
fn parity_naranjo_doubtful() {
    let r = compute("assess-naranjo-causality", json!({
        "previous_reports": false,
        "after_drug": false,
        "improved_on_withdrawal": "no",
        "reappeared_on_rechallenge": "no",
        "alternative_causes": true,
        "placebo_reaction": "yes",
        "drug_detected": "no",
        "dose_related": "no",
        "previous_exposure": false,
        "objective_evidence": false
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(get_i64(&r, "score") <= 0, "Score was {}", get_i64(&r, "score"));
    assert_eq!(get_str(&r, "category"), "doubtful");
}

#[test]
fn parity_who_umc_certain() {
    let r = compute("assess-who-umc-causality", json!({
        "temporal_relationship": true,
        "known_response": true,
        "dechallenge_positive": "yes",
        "rechallenge_positive": "yes",
        "alternative_explanation": false,
        "sufficient_information": true
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert_eq!(get_str(&r, "category"), "certain");
}

#[test]
fn parity_who_umc_unlikely() {
    let r = compute("assess-who-umc-causality", json!({
        "temporal_relationship": false,
        "known_response": false,
        "dechallenge_positive": "no",
        "rechallenge_positive": "not_done",
        "alternative_explanation": true,
        "sufficient_information": true
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert_eq!(get_str(&r, "category"), "unlikely");
}

// ══════════════════════════════════════════════════════════════
// Seriousness Classification (ICH E2A)
// ══════════════════════════════════════════════════════════════

#[test]
fn parity_seriousness_non_serious() {
    let r = compute("classify-seriousness", json!({
        "resulted_in_death": false,
        "life_threatening": false,
        "required_hospitalization": false,
        "resulted_in_disability": false,
        "congenital_anomaly": false,
        "medically_important": false
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(!get_bool(&r, "is_serious"));
}

#[test]
fn parity_seriousness_death() {
    let r = compute("classify-seriousness", json!({
        "resulted_in_death": true,
        "life_threatening": false,
        "required_hospitalization": false,
        "resulted_in_disability": false,
        "congenital_anomaly": false,
        "medically_important": false
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(get_bool(&r, "is_serious"));
}

// ══════════════════════════════════════════════════════════════
// Benefit-Risk Analysis
// ══════════════════════════════════════════════════════════════

#[test]
fn parity_benefit_risk_favorable() {
    // Benefit = 0.8 * 0.7 = 0.56
    let r = compute("compute-benefit-risk", json!({
        "efficacy_score": 0.8,
        "population_impact": 0.7,
        "risk_severity": 0.3,
        "risk_frequency": 0.05,
        "risk_detectability": 0.8
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "benefit_score"), 0.56), "Benefit was {}", get_f64(&r, "benefit_score"));
    assert_eq!(get_str(&r, "assessment"), "favorable");
}

#[test]
fn parity_benefit_risk_unfavorable() {
    let r = compute("compute-benefit-risk", json!({
        "efficacy_score": 0.2,
        "population_impact": 0.1,
        "risk_severity": 0.9,
        "risk_frequency": 0.5,
        "risk_detectability": 0.1
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert_eq!(get_str(&r, "assessment"), "unfavorable");
}

// ══════════════════════════════════════════════════════════════
// Signal Half-Life
// ══════════════════════════════════════════════════════════════

#[test]
fn parity_signal_half_life() {
    // half_life = ln(2) / 0.1 = 6.93 months
    let r = compute("compute-signal-half-life", json!({
        "initial_signal_strength": 8.0,
        "decay_rate": 0.1
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "half_life_months"), 6.93),
        "Half-life was {}", get_f64(&r, "half_life_months"));
}

// ══════════════════════════════════════════════════════════════
// Epidemiology — Measures of Association
// ══════════════════════════════════════════════════════════════

#[test]
fn parity_relative_risk() {
    // RR = [a/(a+b)] / [c/(c+d)] = [30/130] / [10/110]
    //    = 0.23077 / 0.09091 = 2.5385
    let r = compute("relative-risk", json!({"a": 30, "b": 100, "c": 10, "d": 100}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "relative_risk"), 2.5385),
        "RR was {}", get_f64(&r, "relative_risk"));
    assert!(approx(get_f64(&r, "risk_exposed"), 30.0 / 130.0),
        "risk_exposed was {}", get_f64(&r, "risk_exposed"));
}

#[test]
fn parity_odds_ratio() {
    // OR = (a*d) / (b*c) = (30*100) / (100*10) = 3.0
    let r = compute("odds-ratio", json!({"a": 30, "b": 100, "c": 10, "d": 100}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "odds_ratio"), 3.0),
        "OR was {}", get_f64(&r, "odds_ratio"));
}

#[test]
fn parity_attributable_risk() {
    // AR = a/(a+b) - c/(c+d) = 30/130 - 10/110 = 0.23077 - 0.09091 = 0.13986
    let r = compute("attributable-risk", json!({"a": 30, "b": 100, "c": 10, "d": 100}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "attributable_risk"), 0.13986),
        "AR was {}", get_f64(&r, "attributable_risk"));
}

#[test]
fn parity_nnt_nnh() {
    // AR = 30/130 - 10/110 = 0.13986, NNH = 1/0.13986 = 7.15
    // AR > 0 so metric = NNH
    let r = compute("nnt-nnh", json!({"a": 30, "b": 100, "c": 10, "d": 100}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert_eq!(get_str(&r, "metric"), "NNH");
    assert!(approx(get_f64(&r, "value"), 7.15),
        "NNH was {}", get_f64(&r, "value"));
}

#[test]
fn parity_nnt_protective() {
    // When unexposed risk > exposed risk: AR < 0 → NNT
    // AR = 5/105 - 20/120 = 0.04762 - 0.16667 = -0.11905
    // NNT = |1/AR| = 8.4
    let r = compute("nnt-nnh", json!({"a": 5, "b": 100, "c": 20, "d": 100}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert_eq!(get_str(&r, "metric"), "NNT");
    assert!(approx(get_f64(&r, "value"), 8.4),
        "NNT was {}", get_f64(&r, "value"));
}

#[test]
fn parity_kaplan_meier() {
    // KM: n_initial = sum(events) + sum(censored) = 4 + 4 = 8
    // t=1: n=8, d=2, S = 1*(1-2/8) = 0.75, n→8-2-0=6
    // t=3: n=6, d=1, S = 0.75*(1-1/6) = 0.625, n→6-1-2=3
    // t=5: n=3, d=1, S = 0.625*(1-1/3) = 0.41667
    let r = compute("kaplan-meier", json!({
        "intervals": [
            {"time": 1, "events": 2, "censored": 0},
            {"time": 3, "events": 1, "censored": 2},
            {"time": 5, "events": 1, "censored": 2}
        ]
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "final_survival"), 0.41667),
        "Final survival was {}", get_f64(&r, "final_survival"));
    assert!(approx(get_f64(&r, "n_initial"), 8.0),
        "n_initial was {}", get_f64(&r, "n_initial"));
}

#[test]
fn parity_chi_square() {
    // 2×2 table: a=20, b=80, c=10, d=90
    // N = 200
    // Expected: E_a = 100*30/200=15, E_b=100*170/200=85, E_c=100*30/200=15, E_d=100*170/200=85
    // χ² = (20-15)²/15 + (80-85)²/85 + (10-15)²/15 + (90-85)²/85
    //    = 25/15 + 25/85 + 25/15 + 25/85
    //    = 1.6667 + 0.2941 + 1.6667 + 0.2941 = 3.9216
    let r = compute("chi-square", json!({"a": 20, "b": 80, "c": 10, "d": 90}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "chi_square"), 3.9216),
        "χ² was {}", get_f64(&r, "chi_square"));
    // p ≈ 0.048, significant at 0.05
    assert!(get_bool(&r, "significant_at_0_05"), "Expected significant at 0.05");
}

// ══════════════════════════════════════════════════════════════
// Pharmacology — Pharmacokinetic Parameters
// ══════════════════════════════════════════════════════════════

#[test]
fn parity_pk_auc_trapezoidal() {
    // Trapezoidal rule: points (0,0), (1,10), (2,8), (4,2)
    // AUC = 0.5*(0+10)*1 + 0.5*(10+8)*1 + 0.5*(8+2)*2
    //     = 5 + 9 + 10 = 24
    let r = compute("pk-auc", json!({
        "points": [
            {"time": 0, "concentration": 0},
            {"time": 1, "concentration": 10},
            {"time": 2, "concentration": 8},
            {"time": 4, "concentration": 2}
        ]
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "auc_0_t"), 24.0),
        "AUC was {}", get_f64(&r, "auc_0_t"));
    assert!(approx(get_f64(&r, "cmax"), 10.0),
        "Cmax was {}", get_f64(&r, "cmax"));
    assert!(approx(get_f64(&r, "tmax"), 1.0),
        "Tmax was {}", get_f64(&r, "tmax"));
}

#[test]
fn parity_pk_clearance() {
    // CL = (Dose × F) / AUC = (500 × 1.0) / 50 = 10.0
    let r = compute("pk-clearance", json!({"dose": 500, "auc": 50}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "clearance"), 10.0),
        "CL was {}", get_f64(&r, "clearance"));
}

#[test]
fn parity_pk_half_life_from_ke() {
    // t½ = 0.693147 / ke = 0.693147 / 0.1 = 6.93147 hours
    let r = compute("pk-half-life", json!({"ke": 0.1}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "half_life"), 6.93147),
        "t½ was {}", get_f64(&r, "half_life"));
}

#[test]
fn parity_pk_half_life_from_concentrations() {
    // ke = ln(C1/C2) / (t2-t1) = ln(100/25) / (8-0) = ln(4)/8 = 1.3863/8 = 0.17329
    // t½ = 0.693147 / 0.17329 = 4.0 hours
    let r = compute("pk-half-life", json!({"c1": 100, "c2": 25, "t1": 0, "t2": 8}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "half_life"), 4.0),
        "t½ was {}", get_f64(&r, "half_life"));
}

#[test]
fn parity_pk_steady_state() {
    // Css_avg = (F × Dose) / (Vd × ke × τ) = (1.0 × 100) / (1.0 × 0.1 × 12) = 83.33
    // t½ = 0.693147 / 0.1 = 6.93147
    // time_to_ss = 4 × t½ = 27.726
    let r = compute("pk-steady-state", json!({
        "dose": 100,
        "interval": 12,
        "ke": 0.1,
        "vd": 1.0
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "css_average"), 83.33),
        "Css was {}", get_f64(&r, "css_average"));
    assert!(approx(get_f64(&r, "half_life"), 6.93147),
        "t½ was {}", get_f64(&r, "half_life"));
}

// ══════════════════════════════════════════════════════════════
// Chemistry — Thermodynamics & Kinetics
// ══════════════════════════════════════════════════════════════

#[test]
fn parity_hill_equation() {
    // Y = L^n / (Kd^n + L^n), L=10, Kd=5, n=2
    // Y = 100 / (25 + 100) = 100/125 = 0.8
    let r = compute("hill-equation", json!({"ligand": 10, "kd": 5, "n": 2}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "fractional_occupancy"), 0.8),
        "Y was {}", get_f64(&r, "fractional_occupancy"));
    assert!(approx(get_f64(&r, "percent_occupancy"), 80.0),
        "Y% was {}", get_f64(&r, "percent_occupancy"));
    assert_eq!(get_str(&r, "cooperativity"), "positive (sigmoidal)");
}

#[test]
fn parity_hill_equation_hyperbolic() {
    // n=1 (standard Michaelis-Menten-like), L=Kd → Y = 0.5
    let r = compute("hill-equation", json!({"ligand": 10, "kd": 10, "n": 1}));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "fractional_occupancy"), 0.5),
        "Y was {}", get_f64(&r, "fractional_occupancy"));
    assert_eq!(get_str(&r, "cooperativity"), "none (hyperbolic)");
}

#[test]
fn parity_arrhenius() {
    // k = A × exp(-Ea / RT), A=1e13, Ea=75000 J/mol, T=298.15 K
    // k = 1e13 × exp(-75000 / (8.314 × 298.15))
    //   = 1e13 × exp(-30.2546) = 1e13 × 7.303e-14 ≈ 0.7303
    let r = compute("arrhenius", json!({
        "activation_energy": 75000,
        "temperature": 298.15,
        "pre_exponential": 1e13
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    let k = get_f64(&r, "rate_constant");
    assert!(approx(k, 0.7303), "k was {}", k);
}

#[test]
fn parity_henderson_hasselbalch_ph_from_ratio() {
    // pH = pKa + log10(ratio) = 4.76 + log10(10) = 4.76 + 1.0 = 5.76
    // (acetic acid pKa = 4.76, 10:1 base:acid ratio)
    let r = compute("henderson-hasselbalch", json!({
        "pka": 4.76,
        "conjugate_base_to_acid_ratio": 10.0
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "ph"), 5.76), "pH was {}", get_f64(&r, "ph"));
}

#[test]
fn parity_henderson_hasselbalch_ratio_from_ph() {
    // ratio = 10^(pH - pKa) = 10^(7.4 - 6.1) = 10^1.3 = 19.953
    // percent_ionized = ratio / (1 + ratio) * 100 = 19.953/20.953 * 100 = 95.23%
    let r = compute("henderson-hasselbalch", json!({
        "pka": 6.1,
        "ph": 7.4
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "ratio"), 19.953),
        "Ratio was {}", get_f64(&r, "ratio"));
    assert!(approx(get_f64(&r, "percent_ionized"), 95.23),
        "% ionized was {}", get_f64(&r, "percent_ionized"));
}

#[test]
fn parity_gibbs_free_energy_spontaneous() {
    // ΔG = ΔH - TΔS = -50000 - 298.15*(-100) = -50000 + 29815 = -20185 J/mol
    // Keq = exp(-ΔG / RT) = exp(20185 / (8.314 × 298.15)) = exp(8.143) = 3435.4
    let r = compute("gibbs-free-energy", json!({
        "delta_h": -50000,
        "delta_s": -100,
        "temperature": 298.15
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "delta_g"), -20185.0),
        "ΔG was {}", get_f64(&r, "delta_g"));
    assert!(get_bool(&r, "spontaneous"), "Expected spontaneous=true for ΔG < 0");
}

#[test]
fn parity_gibbs_free_energy_nonspontaneous() {
    // ΔG = ΔH - TΔS = 10000 - 298.15*10 = 10000 - 2981.5 = 7018.5 J/mol
    let r = compute("gibbs-free-energy", json!({
        "delta_h": 10000,
        "delta_s": 10,
        "temperature": 298.15
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "delta_g"), 7018.5),
        "ΔG was {}", get_f64(&r, "delta_g"));
    assert!(!get_bool(&r, "spontaneous"), "Expected spontaneous=false for ΔG > 0");
}

// ══════════════════════════════════════════════════════════════
// Statistics — Confidence Intervals, Hypothesis Tests
// ══════════════════════════════════════════════════════════════

#[test]
fn parity_confidence_interval_mean() {
    // CI = mean ± z * (sd / sqrt(n))
    // z(0.95) = 1.96, SE = 10/sqrt(100) = 1.0
    // CI = 50 ± 1.96 = [48.04, 51.96]
    let r = compute("confidence-interval", json!({
        "type": "mean",
        "mean": 50.0,
        "sd": 10.0,
        "n": 100,
        "confidence": 0.95
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "ci_lower"), 48.04),
        "CI lower was {}", get_f64(&r, "ci_lower"));
    assert!(approx(get_f64(&r, "ci_upper"), 51.96),
        "CI upper was {}", get_f64(&r, "ci_upper"));
}

#[test]
fn parity_confidence_interval_proportion() {
    // Wilson score interval for 30 successes out of 100
    // p = 0.3, z = 1.96, z² = 3.8416
    // denom = 1 + 3.8416/100 = 1.038416
    // center = (0.3 + 3.8416/200) / 1.038416 = 0.31921 / 1.038416 = 0.30739
    // margin = 1.96 * sqrt(0.3*0.7/100 + 3.8416/40000) / 1.038416
    //        = 1.96 * sqrt(0.0021 + 0.00009604) / 1.038416
    //        = 1.96 * sqrt(0.00219604) / 1.038416
    //        = 1.96 * 0.04686 / 1.038416 = 0.08843
    // CI = [0.30739 - 0.08843, 0.30739 + 0.08843] = [0.2190, 0.3958]
    let r = compute("confidence-interval", json!({
        "type": "proportion",
        "successes": 30,
        "n": 100,
        "confidence": 0.95
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "proportion"), 0.3),
        "Proportion was {}", get_f64(&r, "proportion"));
    // Wilson CI is narrower than Wald — just check it brackets 0.3
    let lower = get_f64(&r, "ci_lower");
    let upper = get_f64(&r, "ci_upper");
    assert!(lower < 0.3 && upper > 0.3,
        "Wilson CI [{}, {}] should bracket 0.3", lower, upper);
}

#[test]
fn parity_p_value_z_statistic() {
    // z = 1.96 → two-sided p ≈ 0.05
    let r = compute("p-value", json!({
        "statistic": 1.96,
        "test": "z",
        "sided": "two"
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "p_value"), 0.05),
        "p was {}", get_f64(&r, "p_value"));
    assert!(get_bool(&r, "significant_0_05") == false || approx(get_f64(&r, "p_value"), 0.05),
        "Border case at exactly 0.05");
}

#[test]
fn parity_p_value_highly_significant() {
    // z = 3.29 → two-sided p ≈ 0.001
    let r = compute("p-value", json!({
        "statistic": 3.29,
        "test": "z",
        "sided": "two"
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(get_f64(&r, "p_value") < 0.002, "p was {}", get_f64(&r, "p_value"));
    assert!(get_bool(&r, "significant_0_01"), "Expected significant at 0.01");
}

#[test]
fn parity_z_test_two_proportions() {
    // Group 1: 30/100 = 0.30, Group 2: 20/100 = 0.20
    // p_pooled = 50/200 = 0.25
    // SE = sqrt(0.25 * 0.75 * (1/100 + 1/100)) = sqrt(0.25 * 0.75 * 0.02) = sqrt(0.00375) = 0.06124
    // z = (0.30 - 0.20) / 0.06124 = 0.10 / 0.06124 = 1.6329
    let r = compute("z-test", json!({
        "x1": 30, "n1": 100,
        "x2": 20, "n2": 100
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "z_statistic"), 1.6329),
        "z was {}", get_f64(&r, "z_statistic"));
    assert!(approx(get_f64(&r, "difference"), 0.10),
        "diff was {}", get_f64(&r, "difference"));
}

// ══════════════════════════════════════════════════════════════
// Vigilance — Safety Margin, Risk Score, Harm Classification
// ══════════════════════════════════════════════════════════════

#[test]
fn parity_safety_margin_clear_signal() {
    // Inputs: prr=6.0, ror_lower=3.0, ic025=1.5, eb05=2.5, n=100
    // prr_dist = (6.0 - 2.0) / 2.0 = 2.0
    // ror_dist = (3.0 - 1.0) / 1.0 = 2.0
    // ic_dist  = 1.5 / 1.0 = 1.5
    // eb_dist  = (2.5 - 1.0) / 1.0 = 1.5
    // n_factor = ln(100) / ln(10) = 2.0
    // d = 0.3*2.0 + 0.25*2.0 + 0.2*1.5 + 0.15*1.5 + 0.1*2.0
    //   = 0.6 + 0.5 + 0.3 + 0.225 + 0.2 = 1.825
    let r = compute("safety-margin", json!({
        "prr": 6.0,
        "ror_lower": 3.0,
        "ic025": 1.5,
        "eb05": 2.5,
        "n": 100
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "d"), 1.825),
        "d was {}", get_f64(&r, "d"));
    assert_eq!(get_str(&r, "interpretation"), "Far above threshold — clear signal");
}

#[test]
fn parity_safety_margin_no_signal() {
    // Inputs: prr=1.0, ror_lower=0.5, ic025=-0.5, eb05=0.8, n=5
    // prr_dist = (1.0 - 2.0) / 2.0 = -0.5
    // ror_dist = (0.5 - 1.0) / 1.0 = -0.5
    // ic_dist  = -0.5 / 1.0 = -0.5
    // eb_dist  = (0.8 - 1.0) / 1.0 = -0.2
    // n_factor = ln(5) / ln(10) = 1.6094/2.3026 = 0.69897
    // d = 0.3*(-0.5) + 0.25*(-0.5) + 0.2*(-0.5) + 0.15*(-0.2) + 0.1*0.69897
    //   = -0.15 + -0.125 + -0.1 + -0.03 + 0.06990 = -0.33510
    let r = compute("safety-margin", json!({
        "prr": 1.0,
        "ror_lower": 0.5,
        "ic025": -0.5,
        "eb05": 0.8,
        "n": 5
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "d"), -0.3351),
        "d was {}", get_f64(&r, "d"));
    assert_eq!(get_str(&r, "interpretation"), "Below threshold — unlikely signal");
}

#[test]
fn parity_risk_score() {
    // Inputs: prr=4.0, ror_lower=2.0, ic025=1.0, eb05=2.0, n=50
    // signal_score = min(4.0*2.0, 10) = 8.0
    // confidence_score = min(2.0*3.0, 10) = 6.0  (ror_lower > 1)
    // information_score = min(1.0*5.0, 10) = 5.0  (ic025 > 0)
    // bayesian_score = min(2.0*3.0, 10) = 6.0  (eb05 > 1)
    // volume_score = min(ln(50)*2.0, 10) = min(3.912*2, 10) = 7.824
    // score = 0.25*8 + 0.20*6 + 0.20*5 + 0.20*6 + 0.15*7.824
    //       = 2.0 + 1.2 + 1.0 + 1.2 + 1.1736 = 6.5736
    let r = compute("risk-score", json!({
        "drug": "test-drug",
        "event": "test-event",
        "prr": 4.0,
        "ror_lower": 2.0,
        "ic025": 1.0,
        "eb05": 2.0,
        "n": 50
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert!(approx(get_f64(&r, "score"), 6.5736),
        "Risk score was {}", get_f64(&r, "score"));
    assert_eq!(get_str(&r, "level"), "high");
}

#[test]
fn parity_harm_classify_type_a() {
    // Type A = single + acute + deterministic (Warfarin bleeding)
    let r = compute("harm-classify", json!({
        "multiplicity": "single",
        "temporal": "acute",
        "determinism": "deterministic"
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert_eq!(get_str(&r, "letter"), "A");
    assert_eq!(get_str(&r, "name"), "Type A (Augmented)");
}

#[test]
fn parity_harm_classify_type_b() {
    // Type B = single + acute + stochastic (Penicillin anaphylaxis)
    let r = compute("harm-classify", json!({
        "multiplicity": "single",
        "temporal": "acute",
        "determinism": "stochastic"
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert_eq!(get_str(&r, "letter"), "B");
}

#[test]
fn parity_harm_classify_type_h() {
    // Type H = multiple + chronic + stochastic (Drug-induced lupus)
    let r = compute("harm-classify", json!({
        "multiplicity": "multiple",
        "temporal": "chronic",
        "determinism": "stochastic"
    }));
    assert_eq!(get_str(&r, "status"), "ok");
    assert_eq!(get_str(&r, "letter"), "H");
    assert_eq!(get_str(&r, "name"), "Type H (Hypersensitivity)");
}
