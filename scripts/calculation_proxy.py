#!/usr/bin/env python3
"""
NexVigilant Calculation Station Proxy — Pure PV Computation Engine

All computation, no network calls. Implements signal detection (PRR/ROR/IC/EBGM),
causality assessment (Naranjo, WHO-UMC), seriousness classification (ICH E2A),
benefit-risk analysis, and supporting calculations.

Usage:
    echo '{"tool": "compute-prr", "arguments": {"a": 15, "b": 100, "c": 300, "d": 50000}}' | python3 calculation_proxy.py
"""

import json
import math
import sys


# ---------------------------------------------------------------------------
# Signal Detection (2x2 contingency table methods)
# ---------------------------------------------------------------------------
#
#              Event+    Event-    Total
#    Drug+       a         b       a+b
#    Drug-       c         d       c+d
#    Total      a+c       b+d       N

def _validate_2x2(args: dict) -> tuple:
    """Extract and validate 2x2 table values. Returns (a, b, c, d) or raises."""
    a = int(args.get("a", 0))
    b = int(args.get("b", 0))
    c = int(args.get("c", 0))
    d = int(args.get("d", 0))
    if a < 0 or b < 0 or c < 0 or d < 0:
        raise ValueError("All cell counts must be non-negative")
    if a + b + c + d == 0:
        raise ValueError("Table cannot be all zeros")
    return a, b, c, d


def compute_prr(args: dict) -> dict:
    """Proportional Reporting Ratio (Evans et al., 2001)."""
    try:
        a, b, c, d = _validate_2x2(args)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    n = a + b + c + d
    result = {"status": "ok", "method": "PRR", "contingency_table": {"a": a, "b": b, "c": c, "d": d, "N": n}}

    if (a + b) == 0 or (c + d) == 0 or c == 0:
        result["prr"] = None
        result["signal"] = "insufficient_data"
        return result

    drug_rate = a / (a + b)
    background_rate = c / (c + d)
    prr = drug_rate / background_rate if background_rate > 0 else 0.0

    # 95% CI: exp(ln(PRR) ± 1.96 * sqrt(1/a - 1/(a+b) + 1/c - 1/(c+d)))
    if prr > 0 and a > 0:
        se = math.sqrt(1/a - 1/(a+b) + 1/c - 1/(c+d))
        ln_prr = math.log(prr)
        ci_lower = math.exp(ln_prr - 1.96 * se)
        ci_upper = math.exp(ln_prr + 1.96 * se)
    else:
        ci_lower = ci_upper = 0.0

    # Chi-squared (Yates-corrected)
    denom = (a+b) * (c+d) * (a+c) * (b+d)
    chi2 = n * (abs(a*d - b*c) - n/2)**2 / denom if denom > 0 else 0.0

    # Signal: PRR >= 2, chi2 >= 4, N >= 3 (Evans criteria)
    signal = "no_signal"
    if prr >= 2.0 and chi2 >= 4.0 and a >= 3:
        signal = "signal_detected"
    elif ci_lower > 1.0:
        signal = "possible_signal"

    result.update({
        "prr": round(prr, 4),
        "ci_lower": round(ci_lower, 4),
        "ci_upper": round(ci_upper, 4),
        "chi_squared": round(chi2, 4),
        "signal": signal,
        "criteria": "Evans (2001): PRR >= 2.0, chi2 >= 4.0, N >= 3",
    })
    return result


def compute_ror(args: dict) -> dict:
    """Reporting Odds Ratio."""
    try:
        a, b, c, d = _validate_2x2(args)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    n = a + b + c + d
    result = {"status": "ok", "method": "ROR", "contingency_table": {"a": a, "b": b, "c": c, "d": d, "N": n}}

    if b == 0 or c == 0:
        result["ror"] = None
        result["signal"] = "insufficient_data"
        return result

    ror = (a * d) / (b * c)

    if ror > 0 and a > 0 and d > 0:
        se = math.sqrt(1/a + 1/b + 1/c + 1/d)
        ln_ror = math.log(ror)
        ci_lower = math.exp(ln_ror - 1.96 * se)
        ci_upper = math.exp(ln_ror + 1.96 * se)
    else:
        ci_lower = ci_upper = 0.0

    signal = "no_signal"
    if ror > 1.0 and ci_lower > 1.0:
        signal = "signal_detected"
    elif ror > 1.0:
        signal = "possible_signal"

    result.update({
        "ror": round(ror, 4),
        "ci_lower": round(ci_lower, 4),
        "ci_upper": round(ci_upper, 4),
        "signal": signal,
        "criteria": "ROR > 1 with lower 95% CI > 1 indicates signal",
    })
    return result


def compute_ic(args: dict) -> dict:
    """Information Component / BCPNN (WHO-UMC Bayesian method)."""
    try:
        a, b, c, d = _validate_2x2(args)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    n = a + b + c + d
    result = {"status": "ok", "method": "IC_BCPNN", "contingency_table": {"a": a, "b": b, "c": c, "d": d, "N": n}}

    if a == 0 or (a + b) == 0 or (a + c) == 0:
        result["ic"] = None
        result["signal"] = "insufficient_data"
        return result

    observed = a / n
    expected = ((a + b) / n) * ((a + c) / n)

    if expected <= 0:
        result["ic"] = None
        result["signal"] = "insufficient_data"
        return result

    ic = math.log2(observed / expected)
    # SE(IC) = sqrt(1/a + 1/(a+b) + 1/(a+c) - 1/N) / ln(2)
    se = math.sqrt(1/a + 1/(a+b) + 1/(a+c) - 1/n) / math.log(2)
    ic025 = ic - 1.96 * se
    ic975 = ic + 1.96 * se

    signal = "no_signal"
    if ic025 > 0:
        signal = "signal_detected"
    elif ic > 0:
        signal = "possible_signal"

    result.update({
        "ic": round(ic, 4),
        "ic025": round(ic025, 4),
        "ic975": round(ic975, 4),
        "signal": signal,
        "criteria": "IC > 0 with IC025 > 0 indicates signal (WHO-UMC BCPNN)",
    })
    return result


def compute_ebgm(args: dict) -> dict:
    """Empirical Bayesian Geometric Mean (FDA GPS method).

    Simplified EBGM using a single-component prior. Full Multi-item Gamma
    Poisson Shrinker uses mixture priors fitted to the full database — this
    approximation is suitable for individual drug-event pair assessment.
    """
    try:
        a, b, c, d = _validate_2x2(args)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    n = a + b + c + d
    result = {"status": "ok", "method": "EBGM_GPS", "contingency_table": {"a": a, "b": b, "c": c, "d": d, "N": n}}

    if (a + b) == 0 or (a + c) == 0 or n == 0:
        result["ebgm"] = None
        result["signal"] = "insufficient_data"
        return result

    expected = ((a + b) * (a + c)) / n

    if expected <= 0:
        result["ebgm"] = None
        result["signal"] = "insufficient_data"
        return result

    # EBGM ≈ (a + 0.5) / (expected + 0.5)  (shrinkage estimator)
    ebgm = (a + 0.5) / (expected + 0.5)

    # EB05 (lower bound) — approximate via log-normal
    if a > 0:
        ln_ebgm = math.log(ebgm)
        se_ln = 1.0 / math.sqrt(a + 0.5)
        eb05 = math.exp(ln_ebgm - 1.645 * se_ln)
        eb95 = math.exp(ln_ebgm + 1.645 * se_ln)
    else:
        eb05 = eb95 = 0.0

    signal = "no_signal"
    if ebgm >= 2.0 and eb05 >= 1.0:
        signal = "signal_detected"
    elif ebgm >= 2.0:
        signal = "possible_signal"

    result.update({
        "ebgm": round(ebgm, 4),
        "eb05": round(eb05, 4),
        "eb95": round(eb95, 4),
        "expected": round(expected, 4),
        "observed": a,
        "signal": signal,
        "criteria": "EBGM >= 2 with EB05 >= 1 indicates signal (FDA GPS)",
        "note": "Simplified single-prior EBGM. Full GPS uses mixture priors.",
    })
    return result


def compute_disproportionality_table(args: dict) -> dict:
    """Compute all four measures simultaneously."""
    try:
        a, b, c, d = _validate_2x2(args)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    table_args = {"a": a, "b": b, "c": c, "d": d}
    prr = compute_prr(table_args)
    ror = compute_ror(table_args)
    ic = compute_ic(table_args)
    ebgm = compute_ebgm(table_args)

    # Consensus signal: majority vote across 4 methods
    signals = [
        prr.get("signal", "no_signal"),
        ror.get("signal", "no_signal"),
        ic.get("signal", "no_signal"),
        ebgm.get("signal", "no_signal"),
    ]
    detected_count = signals.count("signal_detected")
    possible_count = signals.count("possible_signal")

    if detected_count >= 3:
        consensus = "strong_signal"
    elif detected_count >= 2:
        consensus = "signal_detected"
    elif detected_count >= 1 or possible_count >= 2:
        consensus = "possible_signal"
    else:
        consensus = "no_signal"

    return {
        "status": "ok",
        "method": "all_four_measures",
        "contingency_table": {"a": a, "b": b, "c": c, "d": d, "N": a + b + c + d},
        "prr": {"value": prr.get("prr"), "ci_lower": prr.get("ci_lower"), "signal": prr.get("signal")},
        "ror": {"value": ror.get("ror"), "ci_lower": ror.get("ci_lower"), "signal": ror.get("signal")},
        "ic": {"value": ic.get("ic"), "ic025": ic.get("ic025"), "signal": ic.get("signal")},
        "ebgm": {"value": ebgm.get("ebgm"), "eb05": ebgm.get("eb05"), "signal": ebgm.get("signal")},
        "consensus_signal": consensus,
        "signals_detected": detected_count,
        "signals_possible": possible_count,
    }


# ---------------------------------------------------------------------------
# Causality Assessment
# ---------------------------------------------------------------------------

def assess_naranjo_causality(args: dict) -> dict:
    """Naranjo Adverse Drug Reaction Probability Scale (Naranjo et al., 1981)."""
    score = 0

    # Q1: Previous conclusive reports? (+1 yes, 0 no)
    if args.get("previous_reports"):
        score += 1

    # Q2: Event appeared after drug? (+2 yes, -1 no)
    if args.get("after_drug"):
        score += 2
    else:
        score -= 1

    # Q3: Improved on withdrawal? (+1 yes, 0 no/not_withdrawn)
    withdrawal = str(args.get("improved_on_withdrawal", "")).lower()
    if withdrawal == "yes":
        score += 1

    # Q4: Reappeared on rechallenge? (+2 yes, -1 no, 0 not_done)
    rechallenge = str(args.get("reappeared_on_rechallenge", "")).lower()
    if rechallenge == "yes":
        score += 2
    elif rechallenge == "no":
        score -= 1

    # Q5: Alternative causes? (-1 yes, +2 no)
    if args.get("alternative_causes"):
        score -= 1
    else:
        score += 2

    # Q6: Placebo reaction? (-1 yes, +1 no, 0 not_done)
    placebo = str(args.get("placebo_reaction", "")).lower()
    if placebo == "yes":
        score -= 1
    elif placebo == "no":
        score += 1

    # Q7: Drug in toxic concentrations? (+1 yes, 0 no/not_done)
    drug_detected = str(args.get("drug_detected", "")).lower()
    if drug_detected == "yes":
        score += 1

    # Q8: Dose-related? (+1 yes, 0 no/not_done)
    dose_related = str(args.get("dose_related", "")).lower()
    if dose_related == "yes":
        score += 1

    # Q9: Previous exposure reaction? (+1 yes, 0 no)
    if args.get("previous_exposure"):
        score += 1

    # Q10: Objective evidence? (+1 yes, 0 no)
    if args.get("objective_evidence"):
        score += 1

    # Categorize
    if score >= 9:
        category = "definite"
    elif score >= 5:
        category = "probable"
    elif score >= 1:
        category = "possible"
    else:
        category = "doubtful"

    return {
        "status": "ok",
        "method": "Naranjo_ADR_Probability_Scale",
        "score": score,
        "max_score": 13,
        "category": category,
        "interpretation": f"Score {score}/13 = {category.upper()} adverse drug reaction",
        "reference": "Naranjo CA et al. Clin Pharmacol Ther. 1981;30(2):239-245",
        "scale": {
            "definite": ">=9",
            "probable": "5-8",
            "possible": "1-4",
            "doubtful": "<=0",
        },
    }


def assess_who_umc_causality(args: dict) -> dict:
    """WHO-UMC Causality Assessment System."""
    temporal = args.get("temporal_relationship", False)
    known = args.get("known_response", False)
    dechallenge = str(args.get("dechallenge_positive", "")).lower()
    rechallenge = str(args.get("rechallenge_positive", "")).lower()
    alternative = args.get("alternative_explanation", False)
    sufficient = args.get("sufficient_information", True)

    if not sufficient:
        return {
            "status": "ok",
            "method": "WHO-UMC_Causality",
            "category": "unassessable",
            "description": "Insufficient or contradictory information",
        }

    # Certain: temporal + known + dechallenge + rechallenge + no alternative
    if (temporal and known and dechallenge == "yes"
            and rechallenge == "yes" and not alternative):
        category = "certain"
        description = "Event with reasonable time, known response, confirmed by dechallenge AND rechallenge, no alternative explanation"

    # Probable/Likely: temporal + known + dechallenge + no alternative (no rechallenge required)
    elif (temporal and known and dechallenge == "yes" and not alternative):
        category = "probable"
        description = "Event with reasonable time, known response, confirmed by dechallenge, no alternative explanation"

    # Possible: temporal + known but alternative possible or dechallenge unclear
    elif temporal and known:
        category = "possible"
        description = "Event with reasonable time, known response, but alternative explanation possible or dechallenge unclear"

    # Unlikely: temporal relationship improbable or response not known
    elif not temporal or not known:
        category = "unlikely"
        description = "Temporal relationship improbable and/or response not known for the drug"

    else:
        category = "conditional"
        description = "More data needed for proper assessment"

    return {
        "status": "ok",
        "method": "WHO-UMC_Causality",
        "category": category,
        "description": description,
        "criteria_met": {
            "temporal_relationship": temporal,
            "known_response": known,
            "dechallenge_positive": dechallenge,
            "rechallenge_positive": rechallenge,
            "alternative_explanation": alternative,
            "sufficient_information": sufficient,
        },
        "reference": "WHO-UMC Causality Assessment System",
        "scale": {
            "certain": "All criteria met including rechallenge",
            "probable": "Reasonable time, known response, dechallenge positive, no alternative",
            "possible": "Reasonable time, known response, but alternative possible",
            "unlikely": "Improbable temporal relationship or unknown response",
            "conditional": "More data needed",
            "unassessable": "Insufficient information",
        },
    }


# ---------------------------------------------------------------------------
# Seriousness Classification
# ---------------------------------------------------------------------------

def classify_seriousness(args: dict) -> dict:
    """ICH E2A Seriousness Classification."""
    criteria = {
        "resulted_in_death": bool(args.get("resulted_in_death", False)),
        "life_threatening": bool(args.get("life_threatening", False)),
        "required_hospitalization": bool(args.get("required_hospitalization", False)),
        "resulted_in_disability": bool(args.get("resulted_in_disability", False)),
        "congenital_anomaly": bool(args.get("congenital_anomaly", False)),
        "medically_important": bool(args.get("medically_important", False)),
    }

    met = [k for k, v in criteria.items() if v]
    is_serious = len(met) > 0

    # Determine highest severity for reporting priority
    if criteria["resulted_in_death"]:
        severity_rank = "fatal"
        reporting_timeline = "15 calendar days (expedited)"
    elif criteria["life_threatening"]:
        severity_rank = "life_threatening"
        reporting_timeline = "15 calendar days (expedited)"
    elif criteria["required_hospitalization"]:
        severity_rank = "hospitalization"
        reporting_timeline = "15 calendar days (initial), 90 days (follow-up)"
    elif is_serious:
        severity_rank = "other_serious"
        reporting_timeline = "90 calendar days (periodic)"
    else:
        severity_rank = "non_serious"
        reporting_timeline = "Periodic reporting only (PSUR/PBRER)"

    return {
        "status": "ok",
        "method": "ICH_E2A_Seriousness",
        "is_serious": is_serious,
        "criteria_met": met,
        "criteria_count": len(met),
        "severity_rank": severity_rank,
        "reporting_timeline": reporting_timeline,
        "all_criteria": criteria,
        "reference": "ICH E2A: Clinical Safety Data Management",
    }


# ---------------------------------------------------------------------------
# Benefit-Risk Analysis
# ---------------------------------------------------------------------------

def compute_benefit_risk(args: dict) -> dict:
    """NexVigilant QBR Framework — quantitative benefit-risk ratio."""
    efficacy = float(args.get("efficacy_score", 0))
    population = float(args.get("population_impact", 0))
    severity = float(args.get("risk_severity", 0))
    frequency = float(args.get("risk_frequency", 0))
    detectability = float(args.get("risk_detectability", 0.5))

    # Validate ranges
    for name, val in [("efficacy_score", efficacy), ("population_impact", population),
                       ("risk_severity", severity), ("risk_frequency", frequency),
                       ("risk_detectability", detectability)]:
        if val < 0 or val > 1:
            return {"status": "error", "message": f"{name} must be in [0.0, 1.0], got {val}"}

    benefit = efficacy * population
    # Risk adjusted for detectability — more detectable risks are more manageable
    risk = severity * frequency * (1 - detectability * 0.5)
    ratio = benefit / risk if risk > 0 else float("inf")

    if ratio >= 5.0:
        assessment = "favorable"
    elif ratio >= 2.0:
        assessment = "acceptable"
    elif ratio >= 1.0:
        assessment = "borderline"
    else:
        assessment = "unfavorable"

    return {
        "status": "ok",
        "method": "NexVigilant_QBR",
        "benefit_score": round(benefit, 4),
        "risk_score": round(risk, 4),
        "benefit_risk_ratio": round(ratio, 4) if ratio != float("inf") else "infinite",
        "assessment": assessment,
        "components": {
            "efficacy_score": efficacy,
            "population_impact": population,
            "risk_severity": severity,
            "risk_frequency": frequency,
            "risk_detectability": detectability,
        },
        "interpretation": {
            "favorable": "ratio >= 5.0",
            "acceptable": "ratio >= 2.0",
            "borderline": "ratio >= 1.0",
            "unfavorable": "ratio < 1.0",
        },
    }


# ---------------------------------------------------------------------------
# Supporting Calculations
# ---------------------------------------------------------------------------

def compute_reporting_rate(args: dict) -> dict:
    """Adverse event reporting rate per unit exposure."""
    case_count = int(args.get("case_count", 0))
    denominator = float(args.get("exposure_denominator", 0))
    unit = str(args.get("denominator_unit", "prescriptions")).lower()
    months = int(args.get("time_period_months", 0))

    if denominator <= 0:
        return {"status": "error", "message": "exposure_denominator must be positive"}
    if case_count < 0:
        return {"status": "error", "message": "case_count must be non-negative"}

    rate = case_count / denominator

    # Normalize to standard units
    if unit == "prescriptions":
        per_thousand = rate * 1000
        label = f"{round(per_thousand, 4)} per 1,000 prescriptions"
    elif unit == "patient_years":
        per_thousand = rate * 1000
        label = f"{round(per_thousand, 4)} per 1,000 patient-years"
    elif unit == "doses":
        per_million = rate * 1_000_000
        label = f"{round(per_million, 4)} per 1,000,000 doses"
    else:
        per_thousand = rate * 1000
        label = f"{round(per_thousand, 4)} per 1,000 {unit}"

    result = {
        "status": "ok",
        "method": "reporting_rate",
        "case_count": case_count,
        "exposure_denominator": denominator,
        "denominator_unit": unit,
        "rate": round(rate, 8),
        "normalized": label,
    }

    if months > 0:
        annualized = rate * (12 / months)
        result["annualized_rate"] = round(annualized, 8)
        result["time_period_months"] = months

    return result


def compute_signal_half_life(args: dict) -> dict:
    """Signal persistence using exponential decay model."""
    initial = float(args.get("initial_signal_strength", 0))
    decay_rate = float(args.get("decay_rate", 0))
    threshold = float(args.get("detection_threshold", 2.0))

    if initial <= 0:
        return {"status": "error", "message": "initial_signal_strength must be positive"}
    if decay_rate <= 0 or decay_rate >= 1:
        return {"status": "error", "message": "decay_rate must be in (0.0, 1.0)"}
    if threshold <= 0:
        return {"status": "error", "message": "detection_threshold must be positive"}

    # Half-life: t_half = ln(2) / decay_rate
    half_life = math.log(2) / decay_rate

    # Time to threshold: initial * e^(-decay_rate * t) = threshold
    # t = ln(initial / threshold) / decay_rate
    if initial > threshold:
        time_to_threshold = math.log(initial / threshold) / decay_rate
    else:
        time_to_threshold = 0.0  # Already below threshold

    # Signal at 6, 12, 24 months
    projections = {}
    for months in [6, 12, 24]:
        projected = initial * math.exp(-decay_rate * months)
        projections[f"{months}_months"] = {
            "value": round(projected, 4),
            "above_threshold": projected >= threshold,
        }

    return {
        "status": "ok",
        "method": "exponential_decay",
        "initial_signal_strength": initial,
        "decay_rate_per_month": decay_rate,
        "detection_threshold": threshold,
        "half_life_months": round(half_life, 2),
        "months_until_undetectable": round(time_to_threshold, 2),
        "projections": projections,
    }


def compute_expectedness(args: dict) -> dict:
    """Assess expectedness of an adverse event.

    This is a reference-based classification — in production, it would look up
    the drug's reference safety information. Here we return the classification
    framework and let the agent determine expectedness from available data.
    """
    event_term = str(args.get("event_term", "")).strip()
    drug_name = str(args.get("drug_name", "")).strip()
    reference = str(args.get("reference_source", "SmPC")).strip()

    if not event_term or not drug_name:
        return {"status": "error", "message": "event_term and drug_name are required"}

    return {
        "status": "ok",
        "method": "expectedness_assessment",
        "event_term": event_term,
        "drug_name": drug_name,
        "reference_source": reference,
        "classification_framework": {
            "expected_listed": "Event is listed in the reference safety information (SmPC Section 4.8, USPI, IB, or CCDS)",
            "unexpected_unlisted": "Event is NOT listed in the reference safety information",
            "class_effect": "Event is known for the pharmacological class but not listed for this specific drug",
        },
        "reporting_implications": {
            "unexpected_serious": "Requires expedited reporting within 15 calendar days (ICH E2A)",
            "expected_serious": "Reported in periodic safety reports (PSUR/PBRER)",
            "unexpected_non_serious": "Reported in periodic safety reports",
            "expected_non_serious": "Routine periodic reporting",
        },
        "note": "Automated expectedness requires access to the current RSI (Reference Safety Information). Use DailyMed or EMA tools to retrieve the current labeling for definitive classification.",
    }


# ---------------------------------------------------------------------------
# Advanced Computations
# ---------------------------------------------------------------------------

def compute_time_to_onset(args: dict) -> dict:
    """Time-to-onset analysis using Weibull distribution.

    Weibull shape parameter (k) indicates onset pattern:
      k < 1: early hazard (decreasing rate — reactions cluster early)
      k = 1: constant hazard (exponential — random timing)
      k > 1: late hazard (increasing rate — accumulation/sensitization)
    """
    onset_days = args.get("onset_days", [])
    if not onset_days or not isinstance(onset_days, list):
        return {"status": "error", "message": "onset_days must be a non-empty list of positive numbers"}

    try:
        days = [float(d) for d in onset_days if float(d) > 0]
    except (ValueError, TypeError):
        return {"status": "error", "message": "onset_days must contain numeric values"}

    if len(days) < 3:
        return {"status": "error", "message": "Need at least 3 positive onset times"}

    n = len(days)
    days_sorted = sorted(days)
    median_onset = days_sorted[n // 2]
    mean_onset = sum(days) / n
    sd_onset = math.sqrt(sum((d - mean_onset) ** 2 for d in days) / (n - 1)) if n > 1 else 0.0

    # Weibull parameter estimation via method of moments
    # CV = SD/mean, and for Weibull: CV ≈ Gamma(1+2/k)/Gamma(1+1/k)^2 - 1
    cv = sd_onset / mean_onset if mean_onset > 0 else 1.0

    # Approximate k from CV using Newton-Raphson-like lookup
    if cv < 0.3:
        k_shape = 4.0  # Very regular timing
    elif cv < 0.5:
        k_shape = 2.5
    elif cv < 0.8:
        k_shape = 1.5
    elif cv < 1.0:
        k_shape = 1.0  # Exponential
    elif cv < 1.5:
        k_shape = 0.7
    else:
        k_shape = 0.5  # Early hazard

    # Scale parameter (lambda) ≈ mean / Gamma(1 + 1/k)
    lambda_scale = mean_onset / math.gamma(1 + 1 / k_shape) if k_shape > 0 else mean_onset

    if k_shape < 0.9:
        pattern = "early_hazard"
        interpretation = "Reactions cluster early after exposure — suggests direct pharmacological effect"
    elif k_shape <= 1.1:
        pattern = "constant_hazard"
        interpretation = "Random timing — consistent with idiosyncratic reactions"
    else:
        pattern = "late_hazard"
        interpretation = "Reactions increase with duration — suggests accumulation or sensitization"

    # Quartiles
    q25 = days_sorted[max(0, n // 4)]
    q75 = days_sorted[min(n - 1, 3 * n // 4)]

    return {
        "status": "ok",
        "method": "Weibull_time_to_onset",
        "n_cases": n,
        "mean_days": round(mean_onset, 1),
        "median_days": round(median_onset, 1),
        "sd_days": round(sd_onset, 1),
        "q25_days": round(q25, 1),
        "q75_days": round(q75, 1),
        "min_days": round(min(days), 1),
        "max_days": round(max(days), 1),
        "weibull_shape_k": round(k_shape, 2),
        "weibull_scale_lambda": round(lambda_scale, 1),
        "onset_pattern": pattern,
        "interpretation": interpretation,
        "reference": "Weibull distribution analysis per van Puijenbroek et al., Drug Safety 2002",
    }


def score_case_completeness(args: dict) -> dict:
    """Score ICSR completeness against E2B(R3) minimum data elements.

    Based on ICH E2B(R3) data elements required for valid ICSR submission.
    Scores presence of key fields that determine regulatory acceptability.
    """
    # E2B(R3) minimum required fields for a valid ICSR
    required_fields = {
        "patient_identifier": "Patient identifier (initials, number, or DOB)",
        "reporter_identifier": "Reporter identifier (name or initials)",
        "suspect_drug": "At least one suspect drug identified",
        "adverse_event": "At least one adverse event described",
    }

    recommended_fields = {
        "patient_age": "Patient age or age group",
        "patient_sex": "Patient sex",
        "event_onset_date": "Date of event onset",
        "drug_start_date": "Date drug therapy started",
        "drug_indication": "Indication for drug use",
        "event_outcome": "Outcome of the event",
        "reporter_country": "Country of reporter",
        "report_type": "Report type (spontaneous, study, etc.)",
        "seriousness_criteria": "Seriousness assessment",
        "causality_assessment": "Causality assessment performed",
        "action_taken": "Action taken with suspect drug",
        "rechallenge_info": "Dechallenge/rechallenge information",
    }

    # Check which fields are present
    required_present = []
    required_missing = []
    for field, desc in required_fields.items():
        val = args.get(field)
        if val and str(val).strip() and str(val).strip().lower() not in ("unknown", "none", "n/a", ""):
            required_present.append(field)
        else:
            required_missing.append({"field": field, "description": desc})

    recommended_present = []
    recommended_missing = []
    for field, desc in recommended_fields.items():
        val = args.get(field)
        if val and str(val).strip() and str(val).strip().lower() not in ("unknown", "none", "n/a", ""):
            recommended_present.append(field)
        else:
            recommended_missing.append({"field": field, "description": desc})

    req_score = len(required_present) / len(required_fields) * 100
    rec_score = len(recommended_present) / len(recommended_fields) * 100
    overall = (req_score * 0.6 + rec_score * 0.4)

    if req_score < 100:
        validity = "invalid"
        action = "Case does not meet minimum E2B requirements — cannot be submitted"
    elif overall >= 80:
        validity = "complete"
        action = "Case is well-documented and ready for submission"
    elif overall >= 50:
        validity = "acceptable"
        action = "Case meets minimum requirements but follow-up recommended"
    else:
        validity = "minimal"
        action = "Case is valid but poorly documented — request follow-up information"

    return {
        "status": "ok",
        "method": "E2B_R3_completeness",
        "overall_score": round(overall, 1),
        "required_score": round(req_score, 1),
        "recommended_score": round(rec_score, 1),
        "validity": validity,
        "action": action,
        "required_present": required_present,
        "required_missing": required_missing,
        "recommended_present": recommended_present,
        "recommended_missing": recommended_missing,
        "reference": "ICH E2B(R3): Electronic Transmission of ICSRs",
    }


def compute_number_needed_harm(args: dict) -> dict:
    """Compute Number Needed to Harm (NNH) from incidence rates.

    NNH = 1 / ARI where ARI = absolute risk increase = |risk_exposed - risk_unexposed|
    Lower NNH = more frequent harm. NNH < 100 is clinically significant.
    """
    risk_exposed = float(args.get("risk_exposed", 0))
    risk_unexposed = float(args.get("risk_unexposed", 0))

    for name, val in [("risk_exposed", risk_exposed), ("risk_unexposed", risk_unexposed)]:
        if val < 0 or val > 1:
            return {"status": "error", "message": f"{name} must be in [0.0, 1.0], got {val}"}

    ari = abs(risk_exposed - risk_unexposed)
    if ari == 0:
        return {
            "status": "ok",
            "method": "NNH",
            "nnh": None,
            "ari": 0.0,
            "interpretation": "No difference in risk — NNH is undefined (infinite)",
            "risk_exposed": risk_exposed,
            "risk_unexposed": risk_unexposed,
        }

    nnh = 1.0 / ari

    # 95% CI for NNH (approximation using Wald method)
    # SE(ARI) ≈ sqrt(p1*(1-p1)/n1 + p2*(1-p2)/n2), but without N, use wide bounds
    relative_risk = risk_exposed / risk_unexposed if risk_unexposed > 0 else float("inf")

    if nnh < 10:
        severity = "very_frequent_harm"
        interpretation = "Very frequent harm — strong safety signal"
    elif nnh < 100:
        severity = "frequent_harm"
        interpretation = "Frequent harm — clinically significant safety concern"
    elif nnh < 1000:
        severity = "infrequent_harm"
        interpretation = "Infrequent harm — may be acceptable depending on benefit"
    else:
        severity = "rare_harm"
        interpretation = "Rare harm — generally acceptable risk"

    return {
        "status": "ok",
        "method": "NNH",
        "nnh": round(nnh, 1),
        "ari": round(ari, 6),
        "ari_percent": round(ari * 100, 4),
        "relative_risk": round(relative_risk, 4) if relative_risk != float("inf") else "infinite",
        "risk_exposed": risk_exposed,
        "risk_unexposed": risk_unexposed,
        "severity": severity,
        "interpretation": interpretation,
        "reference": "Altman DG. BMJ 1998;317:1309-1312",
    }


def compute_confidence_interval(args: dict) -> dict:
    """Wilson score interval for proportions (small-sample safe).

    Standard Wald CI (p ± z*sqrt(p(1-p)/n)) fails at extremes.
    Wilson score CI remains valid even for small n and p near 0 or 1.
    """
    successes = int(args.get("successes", 0))
    total = int(args.get("total", 0))
    confidence = float(args.get("confidence_level", 0.95))

    if total <= 0:
        return {"status": "error", "message": "total must be positive"}
    if successes < 0 or successes > total:
        return {"status": "error", "message": "successes must be in [0, total]"}
    if confidence <= 0 or confidence >= 1:
        return {"status": "error", "message": "confidence_level must be in (0, 1)"}

    p = successes / total

    # Z-score for confidence level
    # Approximation for common levels
    z_scores = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}
    z = z_scores.get(confidence, 1.96)

    # Wilson score interval
    denominator = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denominator
    spread = z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / denominator

    ci_lower = max(0.0, center - spread)
    ci_upper = min(1.0, center + spread)

    # Also compute Wald interval for comparison
    if total > 0:
        wald_se = math.sqrt(p * (1 - p) / total)
        wald_lower = max(0.0, p - z * wald_se)
        wald_upper = min(1.0, p + z * wald_se)
    else:
        wald_lower = wald_upper = 0.0

    return {
        "status": "ok",
        "method": "Wilson_score_interval",
        "proportion": round(p, 6),
        "successes": successes,
        "total": total,
        "confidence_level": confidence,
        "wilson_ci_lower": round(ci_lower, 6),
        "wilson_ci_upper": round(ci_upper, 6),
        "wilson_ci_width": round(ci_upper - ci_lower, 6),
        "wald_ci_lower": round(wald_lower, 6),
        "wald_ci_upper": round(wald_upper, 6),
        "note": "Wilson score CI recommended over Wald CI for small samples or extreme proportions",
        "reference": "Wilson EB. JASA 1927;22(158):209-212",
    }


def compute_signal_trend(args: dict) -> dict:
    """Linear regression on time-series signal scores to detect trend direction.

    Input: array of {period, score} observations.
    Output: slope, direction (increasing/decreasing/stable), R-squared.
    """
    observations = args.get("observations", [])
    if not observations or not isinstance(observations, list):
        return {"status": "error", "message": "observations must be a non-empty list of {period, score} objects"}

    try:
        periods = []
        scores = []
        for obs in observations:
            if isinstance(obs, dict):
                periods.append(float(obs.get("period", 0)))
                scores.append(float(obs.get("score", 0)))
            elif isinstance(obs, (list, tuple)) and len(obs) >= 2:
                periods.append(float(obs[0]))
                scores.append(float(obs[1]))
            else:
                return {"status": "error", "message": "Each observation must be {period, score} or [period, score]"}
    except (ValueError, TypeError):
        return {"status": "error", "message": "Observations must contain numeric values"}

    n = len(periods)
    if n < 2:
        return {"status": "error", "message": "Need at least 2 observations for trend analysis"}

    # Linear regression: y = mx + b
    mean_x = sum(periods) / n
    mean_y = sum(scores) / n

    ss_xy = sum((periods[i] - mean_x) * (scores[i] - mean_y) for i in range(n))
    ss_xx = sum((periods[i] - mean_x) ** 2 for i in range(n))
    ss_yy = sum((scores[i] - mean_y) ** 2 for i in range(n))

    if ss_xx == 0:
        return {"status": "error", "message": "All periods are identical — cannot compute trend"}

    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x

    # R-squared
    r_squared = (ss_xy ** 2) / (ss_xx * ss_yy) if ss_yy > 0 else 0.0

    # Trend direction with significance threshold
    # Slope relative to mean score magnitude
    relative_slope = abs(slope) / mean_y if mean_y > 0 else abs(slope)

    if relative_slope < 0.05:
        direction = "stable"
        interpretation = "Signal strength is stable over time"
    elif slope > 0:
        direction = "increasing"
        interpretation = "Signal is strengthening — escalate monitoring"
    else:
        direction = "decreasing"
        interpretation = "Signal is weakening — may be resolving"

    # Projected values
    last_period = max(periods)
    projected_next = slope * (last_period + 1) + intercept

    return {
        "status": "ok",
        "method": "linear_regression_trend",
        "n_observations": n,
        "slope": round(slope, 4),
        "intercept": round(intercept, 4),
        "r_squared": round(r_squared, 4),
        "direction": direction,
        "interpretation": interpretation,
        "mean_score": round(mean_y, 4),
        "latest_score": round(scores[-1], 4),
        "projected_next_period": round(projected_next, 4),
        "period_range": [round(min(periods), 1), round(max(periods), 1)],
        "score_range": [round(min(scores), 4), round(max(scores), 4)],
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

TOOL_DISPATCH = {
    "compute-prr": compute_prr,
    "compute-ror": compute_ror,
    "compute-ic": compute_ic,
    "compute-ebgm": compute_ebgm,
    "compute-disproportionality-table": compute_disproportionality_table,
    "assess-naranjo-causality": assess_naranjo_causality,
    "assess-who-umc-causality": assess_who_umc_causality,
    "classify-seriousness": classify_seriousness,
    "compute-benefit-risk": compute_benefit_risk,
    "compute-reporting-rate": compute_reporting_rate,
    "compute-signal-half-life": compute_signal_half_life,
    "compute-expectedness": compute_expectedness,
    "compute-time-to-onset": compute_time_to_onset,
    "score-case-completeness": score_case_completeness,
    "compute-number-needed-harm": compute_number_needed_harm,
    "compute-confidence-interval": compute_confidence_interval,
    "compute-signal-trend": compute_signal_trend,
}


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        result = {"status": "error", "message": "No input received on stdin"}
        print(json.dumps(result))
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        result = {"status": "error", "message": f"Invalid JSON input: {exc}"}
        print(json.dumps(result))
        sys.exit(1)

    tool_name = payload.get("tool", "").strip()
    args = payload.get("arguments", payload.get("args", {}))

    if tool_name not in TOOL_DISPATCH:
        known = list(TOOL_DISPATCH.keys())
        result = {"status": "error", "message": f"Unknown tool '{tool_name}'. Known tools: {known}"}
        print(json.dumps(result))
        sys.exit(1)

    handler = TOOL_DISPATCH[tool_name]
    try:
        result = handler(args)
    except RuntimeError as exc:
        result = {"status": "error", "error": True, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        result = {
            "status": "error",
            "error": True,
            "message": f"Unexpected error in '{tool_name}': {type(exc).__name__}: {exc}",
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
