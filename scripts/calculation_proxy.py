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
    result = handler(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
