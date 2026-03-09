//! Causality assessment tools — Naranjo, WHO-UMC, RUCAM, seriousness.

use serde_json::{Value, json};

pub fn handle(bare_name: &str, args: &Value) -> Option<Value> {
    match bare_name {
        "naranjo-causality" => Some(naranjo(args)),
        "who-umc-causality" => Some(who_umc(args)),
        "classify-seriousness" => Some(classify_seriousness(args)),
        "case-completeness" => Some(case_completeness(args)),
        "number-needed-harm" => Some(number_needed_harm(args)),
        _ => None,
    }
}

fn get_i64(args: &Value, key: &str) -> Option<i64> {
    args.get(key).and_then(|v| v.as_i64())
}

fn get_str<'a>(args: &'a Value, key: &str) -> Option<&'a str> {
    args.get(key).and_then(|v| v.as_str())
}

fn get_bool(args: &Value, key: &str) -> Option<bool> {
    args.get(key).and_then(|v| v.as_bool())
}

fn get_f64(args: &Value, key: &str) -> Option<f64> {
    args.get(key).and_then(|v| v.as_f64())
}

fn err(msg: &str) -> Value {
    json!({"status": "error", "message": msg})
}

/// Naranjo Adverse Drug Reaction Probability Scale.
/// 10 questions, each scored +2/+1/0/-1.
fn naranjo(args: &Value) -> Value {
    // Q1: Previous conclusive reports? (+1 yes, 0 no, 0 unknown)
    // Q2: AE after drug administered? (+2 yes, -1 no, 0 unknown)
    // Q3: Improved after discontinuation? (+1 yes, 0 no, 0 unknown)
    // Q4: Reappeared on re-administration? (+2 yes, -1 no, 0 unknown)
    // Q5: Alternative causes? (-1 yes, +2 no, 0 unknown)
    // Q6: Reaction with placebo? (-1 yes, +1 no, 0 unknown)
    // Q7: Drug detected in toxic concentrations? (+1 yes, 0 no, 0 unknown)
    // Q8: Dose-response relationship? (+1 yes, 0 no, 0 unknown)
    // Q9: Patient had similar reaction previously? (+1 yes, 0 no, 0 unknown)
    // Q10: Confirmed by objective evidence? (+1 yes, 0 no, 0 unknown)

    let questions = [
        ("previous_reports", "Previous conclusive reports of this reaction?"),
        ("ae_after_drug", "Did the AE appear after the drug was administered?"),
        ("improved_on_discontinuation", "Did the AE improve when the drug was discontinued?"),
        ("reappeared_on_readministration", "Did the AE reappear on re-administration?"),
        ("alternative_causes", "Are there alternative causes that could explain the AE?"),
        ("reaction_with_placebo", "Did the reaction appear when a placebo was given?"),
        ("toxic_concentrations", "Was the drug detected in blood at toxic concentrations?"),
        ("dose_response", "Was the reaction more severe with higher dose or less severe with lower dose?"),
        ("similar_reaction_before", "Did the patient have a similar reaction to the same or similar drugs previously?"),
        ("objective_evidence", "Was the reaction confirmed by any objective evidence?"),
    ];

    let score_map: [(i64, i64, i64); 10] = [
        (1, 0, 0),    // Q1
        (2, -1, 0),   // Q2
        (1, 0, 0),    // Q3
        (2, -1, 0),   // Q4
        (-1, 2, 0),   // Q5
        (-1, 1, 0),   // Q6
        (1, 0, 0),    // Q7
        (1, 0, 0),    // Q8
        (1, 0, 0),    // Q9
        (1, 0, 0),    // Q10
    ];

    let mut total_score = 0_i64;
    let mut details = Vec::new();

    for (i, (key, question)) in questions.iter().enumerate() {
        let answer = get_str(args, key).unwrap_or("unknown");
        let (yes_score, no_score, unk_score) = score_map[i];
        let score = match answer {
            "yes" => yes_score,
            "no" => no_score,
            _ => unk_score,
        };
        total_score += score;
        details.push(json!({
            "question": i + 1,
            "text": question,
            "answer": answer,
            "score": score,
        }));
    }

    let category = match total_score {
        9.. => "definite",
        5..=8 => "probable",
        1..=4 => "possible",
        _ => "doubtful",
    };

    json!({
        "status": "ok",
        "method": "naranjo",
        "total_score": total_score,
        "max_possible": 13,
        "category": category,
        "interpretation": match category {
            "definite" => "Definite ADR (score ≥ 9)",
            "probable" => "Probable ADR (score 5-8)",
            "possible" => "Possible ADR (score 1-4)",
            _ => "Doubtful ADR (score ≤ 0)",
        },
        "details": details,
        "reference": "Naranjo CA et al. (1981) Clin Pharmacol Ther 30:239-45"
    })
}

/// WHO-UMC causality assessment system.
fn who_umc(args: &Value) -> Value {
    let temporal = get_str(args, "temporal_relationship").unwrap_or("unknown");
    let dechallenge = get_str(args, "dechallenge").unwrap_or("unknown");
    let rechallenge = get_str(args, "rechallenge").unwrap_or("unknown");
    let alternative = get_str(args, "alternative_causes").unwrap_or("unknown");
    let known_response = get_bool(args, "known_response_pattern").unwrap_or(false);
    let plausible = get_bool(args, "pharmacologically_plausible").unwrap_or(false);

    let category = if temporal == "yes" && dechallenge == "yes" && rechallenge == "yes"
        && alternative == "no" && known_response
    {
        "certain"
    } else if temporal == "yes" && dechallenge == "yes"
        && (alternative == "no" || alternative == "unlikely")
        && known_response
    {
        "probable"
    } else if temporal == "yes" && (known_response || plausible) {
        "possible"
    } else if temporal == "no" || temporal == "unknown" {
        "unlikely"
    } else if temporal == "yes" && !known_response && alternative == "yes" {
        "conditional"
    } else {
        "unassessable"
    };

    let description = match category {
        "certain" => "Event cannot be explained by disease or other drugs; response to withdrawal plausible; rechallenge positive",
        "probable" => "Reasonable time sequence; unlikely attributable to disease/other drugs; response to withdrawal clinically reasonable",
        "possible" => "Reasonable time sequence; could be explained by disease/other drugs",
        "unlikely" => "Temporal relationship improbable; other drugs/disease provide plausible explanations",
        "conditional" => "More data needed for proper assessment",
        _ => "Report suggesting an ADR which cannot be judged",
    };

    json!({
        "status": "ok",
        "method": "who_umc",
        "category": category,
        "description": description,
        "inputs": {
            "temporal_relationship": temporal,
            "dechallenge": dechallenge,
            "rechallenge": rechallenge,
            "alternative_causes": alternative,
            "known_response_pattern": known_response,
            "pharmacologically_plausible": plausible,
        },
        "reference": "WHO-UMC Causality Assessment System"
    })
}

/// ICH E2A seriousness classification.
fn classify_seriousness(args: &Value) -> Value {
    let death = get_bool(args, "death").unwrap_or(false);
    let life_threatening = get_bool(args, "life_threatening").unwrap_or(false);
    let hospitalization = get_bool(args, "hospitalization").unwrap_or(false);
    let disability = get_bool(args, "disability").unwrap_or(false);
    let congenital = get_bool(args, "congenital_anomaly").unwrap_or(false);
    let medically_important = get_bool(args, "medically_important").unwrap_or(false);

    let is_serious = death || life_threatening || hospitalization
        || disability || congenital || medically_important;

    let mut criteria_met = Vec::new();
    if death { criteria_met.push("Results in death"); }
    if life_threatening { criteria_met.push("Life-threatening"); }
    if hospitalization { criteria_met.push("Requires/prolongs hospitalization"); }
    if disability { criteria_met.push("Persistent/significant disability"); }
    if congenital { criteria_met.push("Congenital anomaly/birth defect"); }
    if medically_important { criteria_met.push("Other medically important condition"); }

    let reporting_timeline = if death || life_threatening {
        "7 calendar days initial, 15 days follow-up"
    } else if is_serious {
        "15 calendar days"
    } else {
        "Periodic reporting (PSUR/PBRER)"
    };

    json!({
        "status": "ok",
        "method": "seriousness_classification",
        "is_serious": is_serious,
        "criteria_met": criteria_met,
        "criteria_count": criteria_met.len(),
        "reporting_timeline": reporting_timeline,
        "reference": "ICH E2A: Clinical Safety Data Management"
    })
}

/// ICSR case completeness score (VigiGrade-inspired).
fn case_completeness(args: &Value) -> Value {
    let mut score = 0.0_f64;
    let mut max = 0.0_f64;
    let mut components = Vec::new();

    let fields = [
        ("patient_age", 10.0),
        ("patient_sex", 10.0),
        ("reporter_qualification", 10.0),
        ("event_description", 15.0),
        ("drug_name", 15.0),
        ("indication", 10.0),
        ("dose", 10.0),
        ("onset_date", 10.0),
        ("outcome", 5.0),
        ("country", 5.0),
    ];

    for (field, weight) in &fields {
        max += weight;
        let present = args.get(*field).map(|v| !v.is_null() && v.as_str().map(|s| !s.is_empty()).unwrap_or(true)).unwrap_or(false);
        if present {
            score += weight;
        }
        components.push(json!({
            "field": field,
            "present": present,
            "weight": weight,
        }));
    }

    let pct = if max > 0.0 { score / max * 100.0 } else { 0.0 };

    json!({
        "status": "ok",
        "method": "case_completeness",
        "score": score,
        "max_score": max,
        "percentage": pct,
        "grade": if pct >= 80.0 { "well_documented" }
            else if pct >= 50.0 { "adequately_documented" }
            else { "poorly_documented" },
        "components": components,
        "reference": "VigiGrade completeness score (adapted)"
    })
}

/// Number needed to harm (NNH) from risk data.
fn number_needed_harm(args: &Value) -> Value {
    let risk_exposed = match get_f64(args, "risk_exposed") {
        Some(v) => v,
        None => return err("Missing 'risk_exposed'"),
    };
    let risk_control = match get_f64(args, "risk_control") {
        Some(v) => v,
        None => return err("Missing 'risk_control'"),
    };

    let ard = risk_exposed - risk_control;
    if ard.abs() < 1e-15 {
        return err("Absolute risk difference is zero");
    }

    let nnh = (1.0 / ard).abs();
    let metric = if ard > 0.0 { "NNH" } else { "NNT" };

    json!({
        "status": "ok",
        "method": "number_needed_harm",
        "metric": metric,
        "value": nnh,
        "absolute_risk_difference": ard,
        "risk_exposed": risk_exposed,
        "risk_control": risk_control,
        "description": format!("1 additional {} per {:.0} patients exposed",
            if ard > 0.0 { "harm" } else { "benefit" }, nnh)
    })
}
