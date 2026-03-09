//! Vigilance & Harm Taxonomy computation tools.
//!
//! Tools:
//!   - `safety-margin`  — weighted composite distance from signal thresholds (Guardian-AV d(s))
//!   - `risk-score`     — 0-10 Guardian-AV risk score for a drug-event pair
//!   - `harm-types`     — static A-H harm taxonomy (Theory of Vigilance §9)
//!   - `harm-classify`  — classify harm type from three binary attributes
//!   - `map-to-tov`     — map safety level (1-8) to Theory of Vigilance level

use serde_json::{Value, json};

pub fn handle(bare_name: &str, args: &Value) -> Option<Value> {
    match bare_name {
        "safety-margin" => Some(safety_margin(args)),
        "risk-score" => Some(risk_score(args)),
        "harm-types" => Some(harm_types(args)),
        "harm-classify" => Some(harm_classify(args)),
        "map-to-tov" => Some(map_to_tov(args)),
        _ => None,
    }
}

fn get_f64(args: &Value, key: &str) -> Option<f64> {
    args.get(key).and_then(|v| v.as_f64())
}

fn get_u64(args: &Value, key: &str) -> Option<u64> {
    args.get(key).and_then(|v| v.as_u64())
}

fn err(msg: &str) -> Value {
    json!({"status": "error", "message": msg})
}

/// Safety margin d(s) — weighted composite distance from signal thresholds.
///
/// Each metric is normalized to its detection threshold so that d > 0 means
/// the metric has crossed its threshold, d = 0 means exactly at threshold,
/// and d < 0 means below threshold.
fn safety_margin(args: &Value) -> Value {
    let prr = match get_f64(args, "prr") {
        Some(v) => v,
        None => return err("Missing 'prr'"),
    };
    let ror_lower = match get_f64(args, "ror_lower") {
        Some(v) => v,
        None => return err("Missing 'ror_lower'"),
    };
    let ic025 = match get_f64(args, "ic025") {
        Some(v) => v,
        None => return err("Missing 'ic025'"),
    };
    let eb05 = match get_f64(args, "eb05") {
        Some(v) => v,
        None => return err("Missing 'eb05'"),
    };
    let n = match get_u64(args, "n") {
        Some(v) => v,
        None => return err("Missing 'n'"),
    };

    // Normalize each metric: distance from its threshold
    let prr_dist = (prr - 2.0) / 2.0;
    let ror_dist = (ror_lower - 1.0) / 1.0;
    let ic_dist = ic025 / 1.0;
    let eb_dist = (eb05 - 1.0) / 1.0;
    let n_factor = (n as f64).ln() / 10.0_f64.ln();

    // Weighted composite distance
    let d = 0.3 * prr_dist + 0.25 * ror_dist + 0.2 * ic_dist + 0.15 * eb_dist + 0.1 * n_factor;

    let interpretation = if d > 1.0 {
        "Far above threshold — clear signal"
    } else if d > 0.5 {
        "Moderately above threshold — probable signal"
    } else if d > 0.0 {
        "Near threshold — borderline signal"
    } else if d > -0.5 {
        "Below threshold — unlikely signal"
    } else {
        "Far below threshold — no signal"
    };

    let action = if d > 0.5 {
        "Initiate causality assessment"
    } else if d > 0.0 {
        "Enhanced monitoring recommended"
    } else {
        "Routine surveillance"
    };

    json!({
        "status": "ok",
        "method": "safety-margin",
        "d": d,
        "interpretation": interpretation,
        "action": action,
        "components": {
            "prr_dist": prr_dist,
            "ror_dist": ror_dist,
            "ic_dist": ic_dist,
            "eb_dist": eb_dist,
            "n_factor": n_factor,
            "weights": {
                "prr": 0.30,
                "ror_lower": 0.25,
                "ic025": 0.20,
                "eb05": 0.15,
                "n": 0.10
            }
        },
        "inputs": {
            "prr": prr,
            "ror_lower": ror_lower,
            "ic025": ic025,
            "eb05": eb05,
            "n": n
        },
        "reference": "NexVigilant Guardian-AV safety distance function d(s)"
    })
}

/// Guardian-AV risk score: composite 0-10 score for a drug-event pair.
fn risk_score(args: &Value) -> Value {
    let drug = args.get("drug").and_then(|v| v.as_str()).unwrap_or("").to_owned();
    let event = args.get("event").and_then(|v| v.as_str()).unwrap_or("").to_owned();

    let prr = match get_f64(args, "prr") {
        Some(v) => v,
        None => return err("Missing 'prr'"),
    };
    let ror_lower = match get_f64(args, "ror_lower") {
        Some(v) => v,
        None => return err("Missing 'ror_lower'"),
    };
    let ic025 = match get_f64(args, "ic025") {
        Some(v) => v,
        None => return err("Missing 'ic025'"),
    };
    let eb05 = match get_f64(args, "eb05") {
        Some(v) => v,
        None => return err("Missing 'eb05'"),
    };
    let n = match get_u64(args, "n") {
        Some(v) => v,
        None => return err("Missing 'n'"),
    };

    // Component scores (0-10 each)
    let signal_score = (prr * 2.0).min(10.0);
    let confidence_score = if ror_lower > 1.0 { (ror_lower * 3.0).min(10.0) } else { 0.0 };
    let information_score = if ic025 > 0.0 { (ic025 * 5.0).min(10.0) } else { 0.0 };
    let bayesian_score = if eb05 > 1.0 { (eb05 * 3.0).min(10.0) } else { 0.0 };
    let volume_score = ((n as f64).ln() * 2.0).min(10.0);

    // Weighted composite
    let score = 0.25 * signal_score
        + 0.20 * confidence_score
        + 0.20 * information_score
        + 0.20 * bayesian_score
        + 0.15 * volume_score;

    let level = if score >= 8.0 {
        "critical"
    } else if score >= 6.0 {
        "high"
    } else if score >= 4.0 {
        "moderate"
    } else if score >= 2.0 {
        "low"
    } else {
        "minimal"
    };

    json!({
        "status": "ok",
        "method": "risk-score",
        "drug": drug,
        "event": event,
        "score": score,
        "level": level,
        "components": {
            "signal_score": signal_score,
            "confidence_score": confidence_score,
            "information_score": information_score,
            "bayesian_score": bayesian_score,
            "volume_score": volume_score,
            "weights": {
                "signal (prr)": 0.25,
                "confidence (ror_lower)": 0.20,
                "information (ic025)": 0.20,
                "bayesian (eb05)": 0.20,
                "volume (n)": 0.15
            }
        },
        "inputs": {
            "prr": prr,
            "ror_lower": ror_lower,
            "ic025": ic025,
            "eb05": eb05,
            "n": n
        },
        "reference": "NexVigilant Guardian-AV risk scoring framework"
    })
}

/// Return the complete A-H harm taxonomy (Theory of Vigilance §9).
///
/// The 8 types derive combinatorially from three binary attributes:
///   multiplicity  × temporal   × determinism
///   (single|multi)  (acute|chronic) (deterministic|stochastic)
/// giving 2³ = 8 unique types.
fn harm_types(_args: &Value) -> Value {
    json!({
        "status": "ok",
        "method": "harm-types",
        "taxonomy": [
            {
                "letter": "A",
                "name": "Type A (Augmented)",
                "attributes": {
                    "multiplicity": "single",
                    "temporal": "acute",
                    "determinism": "deterministic"
                },
                "description": "Dose-dependent, predictable ADRs",
                "example": "Warfarin bleeding"
            },
            {
                "letter": "B",
                "name": "Type B (Bizarre)",
                "attributes": {
                    "multiplicity": "single",
                    "temporal": "acute",
                    "determinism": "stochastic"
                },
                "description": "Idiosyncratic, unpredictable ADRs",
                "example": "Penicillin anaphylaxis"
            },
            {
                "letter": "C",
                "name": "Type C (Chronic)",
                "attributes": {
                    "multiplicity": "single",
                    "temporal": "chronic",
                    "determinism": "deterministic"
                },
                "description": "Cumulative dose-related effects",
                "example": "Corticosteroid osteoporosis"
            },
            {
                "letter": "D",
                "name": "Type D (Delayed)",
                "attributes": {
                    "multiplicity": "single",
                    "temporal": "chronic",
                    "determinism": "stochastic"
                },
                "description": "Delayed onset effects",
                "example": "DES vaginal cancer"
            },
            {
                "letter": "E",
                "name": "Type E (End-of-use)",
                "attributes": {
                    "multiplicity": "multiple",
                    "temporal": "acute",
                    "determinism": "deterministic"
                },
                "description": "Withdrawal/rebound effects",
                "example": "Opioid withdrawal"
            },
            {
                "letter": "F",
                "name": "Type F (Failure)",
                "attributes": {
                    "multiplicity": "multiple",
                    "temporal": "acute",
                    "determinism": "stochastic"
                },
                "description": "Unexpected treatment failure",
                "example": "Antibiotic resistance"
            },
            {
                "letter": "G",
                "name": "Type G (Genetic)",
                "attributes": {
                    "multiplicity": "multiple",
                    "temporal": "chronic",
                    "determinism": "deterministic"
                },
                "description": "Genetically-mediated effects",
                "example": "Thiopurine TPMT toxicity"
            },
            {
                "letter": "H",
                "name": "Type H (Hypersensitivity)",
                "attributes": {
                    "multiplicity": "multiple",
                    "temporal": "chronic",
                    "determinism": "stochastic"
                },
                "description": "Delayed immune-mediated",
                "example": "Drug-induced lupus"
            }
        ],
        "combinatorial_note": "2^3 = 8 types derived from: multiplicity (single|multiple) × temporal (acute|chronic) × determinism (deterministic|stochastic)",
        "reference": "Theory of Vigilance §9 — Harm Type Classification"
    })
}

/// Classify harm type from three binary attributes.
///
/// Attribute encoding (deterministic bit ordering):
///   multiplicity:  single=0, multiple=1
///   temporal:      acute=0,  chronic=1
///   determinism:   deterministic=0, stochastic=1
///
/// Mapping: (multiplicity, temporal, determinism) → letter
///   (single, acute,   deterministic) → A
///   (single, acute,   stochastic)    → B
///   (single, chronic, deterministic) → C
///   (single, chronic, stochastic)    → D
///   (multi,  acute,   deterministic) → E
///   (multi,  acute,   stochastic)    → F
///   (multi,  chronic, deterministic) → G
///   (multi,  chronic, stochastic)    → H
fn harm_classify(args: &Value) -> Value {
    let multiplicity = match args.get("multiplicity").and_then(|v| v.as_str()) {
        Some(v) => v.to_lowercase(),
        None => return err("Missing 'multiplicity' (single|multiple)"),
    };
    let temporal = match args.get("temporal").and_then(|v| v.as_str()) {
        Some(v) => v.to_lowercase(),
        None => return err("Missing 'temporal' (acute|chronic)"),
    };
    let determinism = match args.get("determinism").and_then(|v| v.as_str()) {
        Some(v) => v.to_lowercase(),
        None => return err("Missing 'determinism' (deterministic|stochastic)"),
    };

    // Validate inputs
    if multiplicity != "single" && multiplicity != "multiple" {
        return err("'multiplicity' must be 'single' or 'multiple'");
    }
    if temporal != "acute" && temporal != "chronic" {
        return err("'temporal' must be 'acute' or 'chronic'");
    }
    if determinism != "deterministic" && determinism != "stochastic" {
        return err("'determinism' must be 'deterministic' or 'stochastic'");
    }

    let (letter, name, description, example) = match (
        multiplicity.as_str(),
        temporal.as_str(),
        determinism.as_str(),
    ) {
        ("single",   "acute",   "deterministic") => ("A", "Type A (Augmented)",        "Dose-dependent, predictable ADRs",  "Warfarin bleeding"),
        ("single",   "acute",   "stochastic")    => ("B", "Type B (Bizarre)",           "Idiosyncratic, unpredictable ADRs", "Penicillin anaphylaxis"),
        ("single",   "chronic", "deterministic") => ("C", "Type C (Chronic)",           "Cumulative dose-related effects",   "Corticosteroid osteoporosis"),
        ("single",   "chronic", "stochastic")    => ("D", "Type D (Delayed)",           "Delayed onset effects",             "DES vaginal cancer"),
        ("multiple", "acute",   "deterministic") => ("E", "Type E (End-of-use)",        "Withdrawal/rebound effects",        "Opioid withdrawal"),
        ("multiple", "acute",   "stochastic")    => ("F", "Type F (Failure)",           "Unexpected treatment failure",      "Antibiotic resistance"),
        ("multiple", "chronic", "deterministic") => ("G", "Type G (Genetic)",           "Genetically-mediated effects",      "Thiopurine TPMT toxicity"),
        ("multiple", "chronic", "stochastic")    => ("H", "Type H (Hypersensitivity)", "Delayed immune-mediated",           "Drug-induced lupus"),
        _ => return err("Unrecognised attribute combination"),
    };

    json!({
        "status": "ok",
        "method": "harm-classify",
        "letter": letter,
        "name": name,
        "description": description,
        "example": example,
        "attributes": {
            "multiplicity": multiplicity,
            "temporal": temporal,
            "determinism": determinism
        },
        "reference": "Theory of Vigilance §9 — Harm Type Classification"
    })
}

/// Map a safety level (1-8) to Theory of Vigilance abstraction level.
fn map_to_tov(args: &Value) -> Value {
    let level = match args.get("level").and_then(|v| v.as_u64()) {
        Some(v) => v,
        None => return err("Missing 'level' (integer 1-8)"),
    };

    if level < 1 || level > 8 {
        return err("'level' must be an integer between 1 and 8");
    }

    let (safety_name, tov_level, tov_group, description) = match level {
        1 => ("Molecular",       "Foundational", "Foundation (1-2)", "Atomic and molecular interactions — drug receptor binding, metabolic pathways"),
        2 => ("Cellular",        "Foundational", "Foundation (1-2)", "Cell-level effects — apoptosis, toxicity, organelle dysfunction"),
        3 => ("Tissue",          "Structural",   "Structure (3-4)",  "Histopathological changes — tissue injury patterns, fibrosis, necrosis"),
        4 => ("Organ",           "Structural",   "Structure (3-4)",  "Organ-level dysfunction — hepatotoxicity, nephrotoxicity, cardiotoxicity"),
        5 => ("System",          "Functional",   "Function (5-6)",   "Multi-organ system effects — CNS, cardiovascular, immune system"),
        6 => ("Clinical",        "Functional",   "Function (5-6)",   "Patient-level presentation — signs, symptoms, clinical outcomes"),
        7 => ("Epidemiological", "Population",   "Population (7-8)", "Population-level patterns — incidence, prevalence, risk factors"),
        8 => ("Regulatory",      "Population",   "Population (7-8)", "Regulatory and public health action — labelling, withdrawal, risk management"),
        _ => unreachable!(),
    };

    json!({
        "status": "ok",
        "method": "map-to-tov",
        "level": level,
        "safety_level_name": safety_name,
        "tov_level": tov_level,
        "tov_group": tov_group,
        "description": description,
        "all_levels": [
            {"level": 1, "safety": "Molecular",       "tov": "Foundational"},
            {"level": 2, "safety": "Cellular",        "tov": "Foundational"},
            {"level": 3, "safety": "Tissue",          "tov": "Structural"},
            {"level": 4, "safety": "Organ",           "tov": "Structural"},
            {"level": 5, "safety": "System",          "tov": "Functional"},
            {"level": 6, "safety": "Clinical",        "tov": "Functional"},
            {"level": 7, "safety": "Epidemiological", "tov": "Population"},
            {"level": 8, "safety": "Regulatory",      "tov": "Population"}
        ],
        "reference": "Theory of Vigilance — 8-level safety abstraction hierarchy"
    })
}
