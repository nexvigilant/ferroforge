//! Causality assessment tools — Naranjo, WHO-UMC, RUCAM, seriousness.

use serde_json::{Value, json};

pub fn handle(bare_name: &str, args: &Value) -> Option<Value> {
    match bare_name {
        "naranjo-causality" | "assess-naranjo-causality" => Some(naranjo(args)),
        "who-umc-causality" | "assess-who-umc-causality" => Some(who_umc(args)),
        "classify-seriousness" => Some(classify_seriousness(args)),
        "case-completeness" | "score-case-completeness" => Some(case_completeness(args)),
        "number-needed-harm" | "compute-number-needed-harm" => Some(number_needed_harm(args)),
        "assess-rucam" => Some(rucam(args)),
        "assess-severity" => Some(hartwig_siegel(args)),
        _ => None,
    }
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

/// Get a value from args, trying multiple key aliases.
fn get_any<'a>(args: &'a Value, keys: &[&str]) -> Option<&'a Value> {
    keys.iter().find_map(|k| args.get(*k).filter(|v| !v.is_null()))
}

/// Parse a yes/no/unknown answer from either bool or string input.
/// Accepts: true/"yes"/"true" → "yes", false/"no"/"false" → "no", anything else → "unknown"
fn parse_answer(v: &Value) -> &str {
    if let Some(b) = v.as_bool() {
        return if b { "yes" } else { "no" };
    }
    if let Some(s) = v.as_str() {
        return match s {
            "yes" | "true" => "yes",
            "no" | "false" => "no",
            "not_done" | "unknown" | "" => "unknown",
            other => other, // Pass through for edge cases
        };
    }
    "unknown"
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

    // Each question has: (aliases[], display_text, yes_score, no_score, unknown_score)
    // Aliases cover both Rust-native and Python proxy parameter names
    let questions: [(&[&str], &str, i64, i64, i64); 10] = [
        (&["previous_reports"],                                     "Previous conclusive reports of this reaction?", 1, 0, 0),
        (&["ae_after_drug", "after_drug"],                          "Did the AE appear after the drug was administered?", 2, -1, 0),
        (&["improved_on_discontinuation", "improved_on_withdrawal"],"Did the AE improve when the drug was discontinued?", 1, 0, 0),
        (&["reappeared_on_readministration", "reappeared_on_rechallenge"], "Did the AE reappear on re-administration?", 2, -1, 0),
        (&["alternative_causes"],                                   "Are there alternative causes that could explain the AE?", -1, 2, 0),
        (&["reaction_with_placebo", "placebo_reaction"],            "Did the reaction appear when a placebo was given?", -1, 1, 0),
        (&["toxic_concentrations", "drug_detected"],                "Was the drug detected in blood at toxic concentrations?", 1, 0, 0),
        (&["dose_response", "dose_related"],                        "Was the reaction more severe with higher dose or less severe with lower dose?", 1, 0, 0),
        (&["similar_reaction_before", "previous_exposure"],         "Did the patient have a similar reaction to the same or similar drugs previously?", 1, 0, 0),
        (&["objective_evidence"],                                   "Was the reaction confirmed by any objective evidence?", 1, 0, 0),
    ];

    let mut total_score = 0_i64;
    let mut details = Vec::new();

    for (i, (aliases, question, yes_score, no_score, unk_score)) in questions.iter().enumerate() {
        let raw_value = get_any(args, aliases);
        let answer = raw_value.map_or("unknown", parse_answer);
        let score = match answer {
            "yes" => *yes_score,
            "no" => *no_score,
            _ => *unk_score,
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
        "score": total_score,
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
    // Accept both Rust-native and Python proxy parameter names, and both bool/string
    let temporal = get_any(args, &["temporal_relationship"])
        .map_or("unknown", parse_answer);
    let dechallenge = get_any(args, &["dechallenge", "dechallenge_positive"])
        .map_or("unknown", parse_answer);
    let rechallenge = get_any(args, &["rechallenge", "rechallenge_positive"])
        .map_or("unknown", parse_answer);
    let alternative = get_any(args, &["alternative_causes", "alternative_explanation"])
        .map_or("unknown", parse_answer);
    let known_response = get_any(args, &["known_response_pattern", "known_response"])
        .is_some_and(|v| v.as_bool().unwrap_or(parse_answer(v) == "yes"));
    let plausible = get_any(args, &["pharmacologically_plausible", "sufficient_information"])
        .is_some_and(|v| v.as_bool().unwrap_or(parse_answer(v) == "yes"));

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
    // Accept both short names (Rust-native) and full ICH E2A names (Python proxy)
    let death = get_any(args, &["death", "resulted_in_death"])
        .and_then(|v| v.as_bool()).unwrap_or(false);
    let life_threatening = get_any(args, &["life_threatening"])
        .and_then(|v| v.as_bool()).unwrap_or(false);
    let hospitalization = get_any(args, &["hospitalization", "required_hospitalization"])
        .and_then(|v| v.as_bool()).unwrap_or(false);
    let disability = get_any(args, &["disability", "resulted_in_disability"])
        .and_then(|v| v.as_bool()).unwrap_or(false);
    let congenital = get_any(args, &["congenital_anomaly"])
        .and_then(|v| v.as_bool()).unwrap_or(false);
    let medically_important = get_any(args, &["medically_important"])
        .and_then(|v| v.as_bool()).unwrap_or(false);

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

/// RUCAM — Roussel Uclaf Causality Assessment Method for drug-induced liver injury.
/// 7 criteria scored individually, total determines causality category.
fn rucam(args: &Value) -> Value {
    // 1. Time to onset (challenge): +1 to +2
    let onset = get_str(args, "time_to_onset").unwrap_or("unknown");
    let onset_score = match onset {
        "suggestive" => 2,      // 5-90 days (hepatocellular), 5-90 days (cholestatic)
        "compatible" => 1,      // <5 or >90 days
        "against" => -1,        // <3 days after start for rechallenge
        _ => 0,
    };

    // 2. Course after cessation (dechallenge)
    let dechallenge = get_str(args, "dechallenge").unwrap_or("unknown");
    let dechallenge_score = match dechallenge {
        "highly_suggestive" => 3,   // ALT decrease ≥50% in 8 days
        "suggestive" => 2,          // ALT decrease ≥50% in 30 days
        "inconclusive" => 0,
        "against" => -2,            // No improvement or worsening
        _ => 0,
    };

    // 3. Risk factors
    let alcohol = get_bool(args, "alcohol_use").unwrap_or(false);
    let age_over_55 = get_bool(args, "age_over_55").unwrap_or(false);
    let risk_score: i64 = if alcohol { 1 } else { 0 } + if age_over_55 { 1 } else { 0 };

    // 4. Concomitant drugs
    let concomitant = get_str(args, "concomitant_drugs").unwrap_or("unknown");
    let concomitant_score = match concomitant {
        "none" => 0,
        "present_no_info" => -1,
        "known_hepatotoxin" => -2,
        "proven_role" => -3,
        _ => -1,
    };

    // 5. Non-drug causes excluded
    let nondrug = get_str(args, "nondrug_causes").unwrap_or("unknown");
    let nondrug_score = match nondrug {
        "all_excluded" => 2,         // All 6 causes ruled out
        "most_excluded" => 1,        // 4-5 causes ruled out
        "partially_excluded" => 0,
        "possible" => -1,
        "probable" => -3,
        _ => 0,
    };

    // 6. Previous hepatotoxicity known
    let known_hepatotox = get_bool(args, "known_hepatotoxicity").unwrap_or(false);
    let known_score: i64 = if known_hepatotox { 2 } else { 0 };

    // 7. Rechallenge
    let rechallenge = get_str(args, "rechallenge").unwrap_or("not_done");
    let rechallenge_score = match rechallenge {
        "positive" => 3,            // ALT doubles on re-exposure
        "compatible" => 1,
        "negative" => -2,
        "not_done" => 0,
        _ => 0,
    };

    let total = onset_score + dechallenge_score + risk_score
        + concomitant_score + nondrug_score + known_score + rechallenge_score;

    let category = match total {
        9.. => "highly_probable",
        6..=8 => "probable",
        3..=5 => "possible",
        1..=2 => "unlikely",
        _ => "excluded",
    };

    json!({
        "status": "ok",
        "method": "rucam",
        "total_score": total,
        "max_possible": 14,
        "category": category,
        "interpretation": match category {
            "highly_probable" => "Highly probable DILI (score ≥ 9)",
            "probable" => "Probable DILI (score 6-8)",
            "possible" => "Possible DILI (score 3-5)",
            "unlikely" => "Unlikely DILI (score 1-2)",
            _ => "DILI excluded (score ≤ 0)",
        },
        "components": {
            "time_to_onset": {"score": onset_score, "input": onset},
            "dechallenge": {"score": dechallenge_score, "input": dechallenge},
            "risk_factors": {"score": risk_score, "alcohol": alcohol, "age_over_55": age_over_55},
            "concomitant_drugs": {"score": concomitant_score, "input": concomitant},
            "nondrug_causes": {"score": nondrug_score, "input": nondrug},
            "known_hepatotoxicity": {"score": known_score, "known": known_hepatotox},
            "rechallenge": {"score": rechallenge_score, "input": rechallenge},
        },
        "reference": "Danan G, Teschke R (2019) Drug-Induced Liver Injury: RUCAM Update. Int J Mol Sci"
    })
}

/// Hartwig-Siegel ADR severity scale (levels 1-7).
fn hartwig_siegel(args: &Value) -> Value {
    let required_treatment = get_bool(args, "required_treatment").unwrap_or(false);
    let treatment_change = get_bool(args, "treatment_change").unwrap_or(false);
    let hospitalization = get_bool(args, "hospitalization").unwrap_or(false);
    let prolonged_hospital = get_bool(args, "prolonged_hospitalization").unwrap_or(false);
    let permanent_disability = get_bool(args, "permanent_disability").unwrap_or(false);
    let icu_admission = get_bool(args, "icu_admission").unwrap_or(false);
    let death = get_bool(args, "death").unwrap_or(false);

    let (level, severity, description) = if death {
        ("7", "fatal", "The ADR was directly or indirectly responsible for the patient's death")
    } else if permanent_disability {
        ("6", "severe", "The ADR caused permanent disability or long-lasting impairment")
    } else if icu_admission {
        ("5", "severe", "The ADR required ICU admission and/or intensive medical intervention")
    } else if prolonged_hospital || hospitalization {
        if prolonged_hospital {
            ("4b", "moderate", "The ADR prolonged the patient's hospital stay")
        } else {
            ("4a", "moderate", "The ADR required hospital admission")
        }
    } else if treatment_change {
        ("3", "moderate", "The ADR required a change in drug therapy (dose change, addition, or discontinuation)")
    } else if required_treatment {
        ("2", "mild", "The ADR required treatment or intervention but no change in drug therapy")
    } else {
        ("1", "mild", "The ADR required no change in treatment or additional intervention")
    };

    json!({
        "status": "ok",
        "method": "hartwig_siegel",
        "level": level,
        "severity": severity,
        "description": description,
        "inputs": {
            "required_treatment": required_treatment,
            "treatment_change": treatment_change,
            "hospitalization": hospitalization,
            "prolonged_hospitalization": prolonged_hospital,
            "permanent_disability": permanent_disability,
            "icu_admission": icu_admission,
            "death": death,
        },
        "reference": "Hartwig SC, Siegel J, Schneider PJ (1992) Drug Intelligence and Clinical Pharmacy"
    })
}
