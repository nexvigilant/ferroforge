#!/usr/bin/env python3
"""
Guardian PV Engine Proxy — complete pharmacovigilance lifecycle processing.

Implements ICH E2A/E2B(R3)/E2C(R2)/E2D(R1)/E2F, CIOMS I-VIII, FDA 21 CFR 312.32/314.80.
Pure computation — no external API calls, no database dependencies.

Source logic: domains/guardian/apps/pvdsl-engine/src/functions/
  - causality.py (Naranjo, WHO-UMC)
  - regulatory.py (expedited reporting, PSUR/DSUR intervals)
  - classification.py (seriousness, severity, expectedness)
  - icsr.py (minimum data validation)

Usage:
    echo '{"tool": "assess-naranjo", "args": {...}}' | python3 guardian_engine_proxy.py
"""

import json
import sys
from datetime import date, datetime, timedelta
import calendar

# ─── Naranjo Algorithm ───────────────────────────────────────────────────────

NARANJO_MATRIX = {
    "q1_previous_reports":      {"yes": 1,  "no": 0,  "unknown": 0},
    "q2_temporal_relationship":  {"yes": 2,  "no": -1, "unknown": 0},
    "q3_dechallenge":           {"yes": 1,  "no": 0,  "unknown": 0},
    "q4_rechallenge":           {"yes": 2,  "no": -1, "unknown": 0},
    "q5_alternative_causes":    {"yes": -1, "no": 2,  "unknown": 0},
    "q6_placebo_response":      {"yes": -1, "no": 1,  "unknown": 0},
    "q7_drug_concentration":    {"yes": 1,  "no": 0,  "unknown": 0},
    "q8_dose_response":         {"yes": 1,  "no": 0,  "unknown": 0},
    "q9_previous_experience":   {"yes": 1,  "no": 0,  "unknown": 0},
    "q10_objective_evidence":   {"yes": 1,  "no": 0,  "unknown": 0},
}

NARANJO_DESCRIPTIONS = {
    "q1_previous_reports": "Previous conclusive reports on this reaction",
    "q2_temporal_relationship": "Event appeared after suspected drug was given",
    "q3_dechallenge": "ADR improved when drug was discontinued",
    "q4_rechallenge": "ADR reappeared when drug was readministered",
    "q5_alternative_causes": "Alternative causes could explain the reaction",
    "q6_placebo_response": "Reaction appeared when placebo was given",
    "q7_drug_concentration": "Drug detected in blood in toxic concentration",
    "q8_dose_response": "Reaction more severe with increased dose",
    "q9_previous_experience": "Patient had similar reaction before",
    "q10_objective_evidence": "ADR confirmed by objective evidence",
}


def assess_naranjo(args: dict) -> dict:
    total = 0
    questions = {}
    for qid, matrix in NARANJO_MATRIX.items():
        answer = str(args.get(qid, "unknown")).lower().strip()
        if answer not in ("yes", "no", "unknown"):
            answer = "unknown"
        score = matrix[answer]
        total += score
        questions[qid] = {
            "answer": answer,
            "score": score,
            "description": NARANJO_DESCRIPTIONS[qid],
        }

    if total >= 9:
        category = "Definite"
    elif total >= 5:
        category = "Probable"
    elif total >= 1:
        category = "Possible"
    else:
        category = "Doubtful"

    result = {
        "algorithm": "naranjo",
        "score": total,
        "max_possible": 13,
        "min_possible": -4,
        "category": category,
        "is_adr": total >= 1,
        "questions": questions,
        "reference": "Naranjo et al. (1981) Clin Pharmacol Ther 30:239-245",
        "interpretation": {
            "definite": ">=9",
            "probable": "5-8",
            "possible": "1-4",
            "doubtful": "<=0",
        },
    }
    drug = args.get("drug")
    event = args.get("event")
    if drug:
        result["drug"] = drug
    if event:
        result["event"] = event
    return result


# ─── WHO-UMC Causality ───────────────────────────────────────────────────────

def assess_who_umc(args: dict) -> dict:
    time_rel = _bool(args.get("time_relationship", False))
    dechal = _bool(args.get("dechallenge", False))
    rechal = _bool(args.get("rechallenge", False))
    alt_ruled_out = _bool(args.get("alternative_causes", False))
    known = _bool(args.get("known_response", False))

    criteria_met = []
    if time_rel:
        criteria_met.append("plausible_time_relationship")
    if dechal:
        criteria_met.append("positive_dechallenge")
    if rechal:
        criteria_met.append("positive_rechallenge")
    if alt_ruled_out:
        criteria_met.append("alternative_causes_ruled_out")
    if known:
        criteria_met.append("known_response_pattern")

    # WHO-UMC decision logic
    if time_rel and dechal and rechal and alt_ruled_out:
        category = "Certain"
        desc = "Event with reasonable time relationship, positive dechallenge AND rechallenge, alternative causes ruled out."
    elif time_rel and dechal and alt_ruled_out and not rechal:
        category = "Probable/Likely"
        desc = "Event with reasonable time relationship, positive dechallenge, alternative causes ruled out. Rechallenge not performed or unknown."
    elif time_rel and (known or dechal):
        category = "Possible"
        desc = "Event with reasonable time relationship. Known response pattern or positive dechallenge, but alternative causes not fully excluded."
    elif not time_rel:
        category = "Unlikely"
        desc = "Time relationship makes causal connection improbable. Other causes more likely."
    elif time_rel and not dechal and not alt_ruled_out:
        category = "Conditional/Unclassified"
        desc = "Event requires more data for proper assessment. Temporal relationship exists but insufficient evidence."
    else:
        category = "Unassessable/Unclassifiable"
        desc = "Report insufficient or contradictory. Cannot be supplemented or verified."

    result = {
        "algorithm": "who_umc",
        "category": category,
        "description": desc,
        "criteria_met": criteria_met,
        "criteria_count": len(criteria_met),
        "reference": "WHO-UMC Causality Assessment System",
        "categories_scale": [
            "Certain", "Probable/Likely", "Possible",
            "Unlikely", "Conditional/Unclassified", "Unassessable/Unclassifiable",
        ],
    }
    drug = args.get("drug")
    event = args.get("event")
    if drug:
        result["drug"] = drug
    if event:
        result["event"] = event
    return result


# ─── Seriousness Classification (ICH E2A) ────────────────────────────────────

SERIOUSNESS_CRITERIA = {
    "death": "Results in death",
    "life_threatening": "Life-threatening at time of event",
    "hospitalization": "Requires inpatient hospitalization or prolongation of existing hospitalization",
    "disability": "Results in persistent or significant disability/incapacity",
    "congenital_anomaly": "Congenital anomaly/birth defect",
    "medically_significant": "Other medically important condition requiring intervention",
}

SERIOUSNESS_KEYWORDS = {
    "death": {"death", "died", "fatal", "deceased", "mortality", "lethal"},
    "life_threatening": {"life-threatening", "life threatening", "cardiac arrest", "respiratory arrest", "anaphylactic shock"},
    "hospitalization": {"hospitalization", "hospitalisation", "hospitalized", "admitted", "inpatient", "icu", "intensive care", "emergency room"},
    "disability": {"disability", "incapacity", "permanent damage", "paralysis", "blindness", "deafness"},
    "congenital_anomaly": {"congenital", "birth defect", "teratogenic", "malformation"},
    "medically_significant": {"medically significant", "medically important", "requires intervention"},
}


def classify_seriousness(args: dict) -> dict:
    criteria_met = []
    desc = str(args.get("event_description", "")).lower()

    checks = [
        ("death", "resulted_in_death"),
        ("life_threatening", "life_threatening"),
        ("hospitalization", "hospitalization"),
        ("disability", "disability"),
        ("congenital_anomaly", "congenital_anomaly"),
        ("medically_significant", "medically_significant"),
    ]

    for criterion, param in checks:
        explicit = args.get(param)
        if _bool(explicit):
            criteria_met.append(criterion)
        elif explicit is None and desc:
            # NLP fallback: check keywords in description
            keywords = SERIOUSNESS_KEYWORDS.get(criterion, set())
            if any(kw in desc for kw in keywords):
                criteria_met.append(criterion)

    is_serious = len(criteria_met) > 0

    # Determine highest criterion (death > life-threatening > hospitalization > ...)
    hierarchy = ["death", "life_threatening", "hospitalization", "disability", "congenital_anomaly", "medically_significant"]
    highest = next((c for c in hierarchy if c in criteria_met), None)

    return {
        "is_serious": is_serious,
        "criteria_met": [{"criterion": c, "description": SERIOUSNESS_CRITERIA[c]} for c in criteria_met],
        "criteria_count": len(criteria_met),
        "highest_criterion": highest,
        "severity_note": "CRITICAL: Serious (regulatory) != Severe (intensity). ICH E2A/CIOMS IV.",
        "reference": "ICH E2A (1994), CIOMS IV (1998)",
    }


# ─── Expedited Reporting (ICH E2D) ───────────────────────────────────────────

DEADLINES = {
    "fda":  {"7_day": 7, "15_day": 15, "90_day": 90},
    "ema":  {"15_day": 15, "90_day": 90},
    "pmda": {"15_day": 15, "90_day": 90},
    "hc":   {"15_day": 15, "90_day": 90},
    "ich":  {"15_day": 15, "90_day": 90},
    "tga":  {"15_day": 15, "90_day": 90},
    "mhra": {"15_day": 15, "90_day": 90},
    "nmpa": {"15_day": 15, "90_day": 90},
}


def determine_expedited_reporting(args: dict) -> dict:
    is_serious = _bool(args.get("is_serious", False))
    is_unexpected = _bool(args.get("is_unexpected", False))
    is_fatal = _bool(args.get("is_fatal", False))
    is_life_threatening = _bool(args.get("is_life_threatening", False))
    is_dme = _bool(args.get("is_dme", False))
    region = str(args.get("region", "ich")).lower()
    context = str(args.get("context", "post_marketing")).lower()
    is_study_endpoint = _bool(args.get("is_study_endpoint", False))

    criteria_met = []

    if is_study_endpoint:
        return _report_result("non_expedited", 0, False,
            "Study endpoint - exempt from expedited reporting per ICH E2A", [], region, context)

    if is_dme:
        return _report_result("alert_report", 15, True,
            "Designated Medical Event (CIOMS VIII) - expedited reporting required regardless of expectedness",
            ["designated_medical_event"], region, context)

    if not is_serious:
        return _report_result("non_expedited", 0, False,
            "Non-serious event - not subject to expedited reporting", [], region, context)

    criteria_met.append("serious")

    if context == "clinical_trial" and (is_fatal or is_life_threatening) and is_unexpected:
        criteria_met.extend(["fatal_or_life_threatening", "unexpected"])
        if region == "fda":
            return _report_result("7_day", 7, True,
                "IND Safety Report: Fatal/life-threatening unexpected SUSAR requires 7-day alert (FDA 21 CFR 312.32)",
                criteria_met, region, context)
        return _report_result("15_day", 15, True,
            "SUSAR: Fatal/life-threatening unexpected requires 15-day expedited report",
            criteria_met, region, context)

    if is_unexpected:
        criteria_met.append("unexpected")
        if is_fatal:
            criteria_met.append("fatal")
        if is_life_threatening:
            criteria_met.append("life_threatening")
        return _report_result("15_day", 15, True,
            "Serious unexpected adverse reaction - 15-day expedited reporting required (ICH E2D)",
            criteria_met, region, context)

    criteria_met.append("expected")
    return _report_result("90_day", 90, False,
        "Serious expected adverse reaction - include in periodic safety report",
        criteria_met, region, context)


def _report_result(rtype, days, expedited, rationale, criteria, region, context):
    return {
        "report_type": rtype,
        "deadline_days": days,
        "is_expedited": expedited,
        "rationale": rationale,
        "criteria_met": criteria,
        "region": region,
        "context": context,
        "reference": "ICH E2A (1994), ICH E2D(R1) (2025), FDA 21 CFR 312.32/314.80",
    }


# ─── Submission Deadline ──────────────────────────────────────────────────────

def calculate_submission_deadline(args: dict) -> dict:
    awareness = _parse_date(args.get("awareness_date", ""))
    if not awareness:
        return {"error": "awareness_date required in YYYY-MM-DD format"}

    rtype = str(args.get("report_type", "15_day")).lower()
    region = str(args.get("region", "ich")).lower()

    regional = DEADLINES.get(region, DEADLINES["ich"])
    cal_days = regional.get(rtype, 0)

    if cal_days == 0:
        return {
            "awareness_date": awareness.isoformat(),
            "deadline_date": awareness.isoformat(),
            "calendar_days": 0,
            "report_type": rtype,
            "region": region,
            "note": "Non-expedited or unknown report type - no deadline applies",
        }

    deadline = awareness + timedelta(days=cal_days)
    today = date.today()
    is_overdue = today > deadline
    days_remaining = (deadline - today).days if not is_overdue else 0

    return {
        "awareness_date": awareness.isoformat(),
        "deadline_date": deadline.isoformat(),
        "calendar_days": cal_days,
        "report_type": rtype,
        "region": region,
        "is_overdue": is_overdue,
        "days_remaining": days_remaining if not is_overdue else None,
        "days_overdue": abs((deadline - today).days) if is_overdue else 0,
        "reference": "ICH E2D(R1): Day 0 = date minimum information received",
    }


# ─── PSUR/PBRER Interval (ICH E2C) ──────────────────────────────────────────

def calculate_psur_interval(args: dict) -> dict:
    ibd = _parse_date(args.get("international_birth_date", ""))
    if not ibd:
        return {"error": "international_birth_date required in YYYY-MM-DD format"}

    current = _parse_date(args.get("current_date")) or date.today()
    years = (current - ibd).days // 365

    if years < 2:
        interval = 6
    elif years < 5:
        interval = 12
    else:
        interval = 36

    months_since = (current.year - ibd.year) * 12 + (current.month - ibd.month)
    period_num = max(1, (months_since // interval) + 1)
    period_start = _add_months(ibd, (period_num - 1) * interval)
    period_end = _add_months(period_start, interval) - timedelta(days=1)
    submission = period_end + timedelta(days=90)

    return {
        "report_type": "PBRER",
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "submission_deadline": submission.isoformat(),
        "interval_months": interval,
        "period_number": period_num,
        "years_since_approval": years,
        "reference": "ICH E2C(R2): Years 1-2 = 6mo, Years 3-5 = 12mo, Year 6+ = 36mo",
    }


# ─── DSUR Cutoff (ICH E2F) ───────────────────────────────────────────────────

def calculate_dsur_cutoff(args: dict) -> dict:
    dibd = _parse_date(args.get("development_ibd", ""))
    if not dibd:
        return {"error": "development_ibd required in YYYY-MM-DD format"}

    current = _parse_date(args.get("current_date")) or date.today()
    years = (current - dibd).days // 365
    period_num = years + 1
    period_start = _add_months(dibd, (period_num - 1) * 12)
    period_end = _add_months(period_start, 12) - timedelta(days=1)
    submission = period_end + timedelta(days=60)

    return {
        "report_type": "DSUR",
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "data_lock_point": period_end.isoformat(),
        "submission_deadline": submission.isoformat(),
        "interval_months": 12,
        "period_number": period_num,
        "reference": "ICH E2F: Annual DSUR, data lock on DIBD anniversary, submit within 60 days",
    }


# ─── ICSR Minimum Validation (ICH E2B) ───────────────────────────────────────

def validate_icsr_minimum(args: dict) -> dict:
    elements = {
        "identifiable_reporter": False,
        "identifiable_patient": False,
        "suspect_product": False,
        "suspect_reaction": False,
    }

    # Reporter: name OR initials OR qualification OR address
    if any(args.get(k) for k in ("reporter_name", "reporter_country")):
        elements["identifiable_reporter"] = True

    # Patient: initials OR age OR sex OR DOB
    if any(args.get(k) for k in ("patient_initials", "patient_age", "patient_sex")):
        elements["identifiable_patient"] = True

    # Suspect product
    if args.get("suspect_drug"):
        elements["suspect_product"] = True

    # Suspect reaction
    if args.get("adverse_event"):
        elements["suspect_reaction"] = True

    present = [k for k, v in elements.items() if v]
    missing = [k for k, v in elements.items() if not v]
    score = len(present) / 4.0

    if len(present) == 4:
        status = "valid"
    elif len(present) >= 2:
        status = "incomplete"
    else:
        status = "invalid"

    result = {
        "status": status,
        "is_valid": status == "valid",
        "elements_present": present,
        "elements_missing": missing,
        "completeness_score": round(score, 2),
        "minimum_elements_required": 4,
        "reference": "ICH E2B(R3), CIOMS I: 4-element minimum for valid ICSR",
    }

    if args.get("event_date"):
        result["event_date_provided"] = True

    return result


# ─── Deadline Compliance Check ────────────────────────────────────────────────

def check_deadline_compliance(args: dict) -> dict:
    awareness = _parse_date(args.get("awareness_date", ""))
    submission = _parse_date(args.get("submission_date", ""))
    if not awareness or not submission:
        return {"error": "Both awareness_date and submission_date required (YYYY-MM-DD)"}

    rtype = str(args.get("report_type", "15_day")).lower()
    region = str(args.get("region", "ich")).lower()

    regional = DEADLINES.get(region, DEADLINES["ich"])
    cal_days = regional.get(rtype, 0)
    deadline = awareness + timedelta(days=cal_days)
    days_used = (submission - awareness).days
    days_over = max(0, days_used - cal_days)

    return {
        "compliant": submission <= deadline,
        "awareness_date": awareness.isoformat(),
        "deadline_date": deadline.isoformat(),
        "submission_date": submission.isoformat(),
        "days_allowed": cal_days,
        "days_used": days_used,
        "days_over": days_over,
        "report_type": rtype,
        "region": region,
    }


# ─── Capabilities ────────────────────────────────────────────────────────────

def list_capabilities(_args: dict) -> dict:
    return {
        "engine": "Guardian PV Engine",
        "version": "1.0.0",
        "namespaces": {
            "causality": {
                "functions": ["assess-naranjo", "assess-who-umc"],
                "description": "Causality assessment algorithms for drug-event pairs",
                "references": ["Naranjo et al. 1981", "WHO-UMC Guidelines"],
            },
            "classification": {
                "functions": ["classify-seriousness"],
                "description": "ICH E2A seriousness criteria classification",
                "references": ["ICH E2A (1994)", "CIOMS IV (1998)"],
            },
            "regulatory": {
                "functions": [
                    "determine-expedited-reporting",
                    "calculate-submission-deadline",
                    "calculate-psur-interval",
                    "calculate-dsur-cutoff",
                    "check-deadline-compliance",
                ],
                "description": "Expedited reporting, deadlines, periodic report intervals",
                "references": ["ICH E2A", "ICH E2C(R2)", "ICH E2D(R1)", "ICH E2F", "FDA 21 CFR 312.32/314.80"],
            },
            "icsr": {
                "functions": ["validate-icsr-minimum"],
                "description": "ICSR minimum data validation (4-element rule)",
                "references": ["ICH E2B(R3)", "CIOMS I"],
            },
        },
        "total_functions": 10,
        "regulatory_references": [
            "ICH E2A: Clinical Safety Data Management (1994)",
            "ICH E2B(R3): ICSR Specification (2014)",
            "ICH E2C(R2): Periodic Benefit-Risk Evaluation Report (2012)",
            "ICH E2D(R1): Post-Approval Safety Data Management (2025)",
            "ICH E2F: Development Safety Update Report (2010)",
            "CIOMS I-VIII: International Reporting Standards",
            "FDA 21 CFR 312.32: IND Safety Reporting",
            "FDA 21 CFR 314.80: Post-Marketing Reporting",
            "Naranjo et al. (1981) Clin Pharmacol Ther 30:239-245",
            "Danan & Benichou (1993) RUCAM Scale",
            "WHO-UMC Causality Assessment System",
        ],
    }


# ─── Dispatch ─────────────────────────────────────────────────────────────────

HANDLERS = {
    "assess-naranjo": assess_naranjo,
    "assess-who-umc": assess_who_umc,
    "classify-seriousness": classify_seriousness,
    "determine-expedited-reporting": determine_expedited_reporting,
    "calculate-submission-deadline": calculate_submission_deadline,
    "calculate-psur-interval": calculate_psur_interval,
    "calculate-dsur-cutoff": calculate_dsur_cutoff,
    "validate-icsr-minimum": validate_icsr_minimum,
    "check-deadline-compliance": check_deadline_compliance,
    "list-capabilities": list_capabilities,
}


def _bool(val) -> bool:
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    return str(val).lower() in ("true", "yes", "1", "y")


def _parse_date(val) -> date | None:
    if not val:
        return None
    if isinstance(val, date):
        return val
    try:
        return datetime.fromisoformat(str(val)).date()
    except (ValueError, TypeError):
        return None


def _add_months(src: date, months: int) -> date:
    month = src.month - 1 + months
    year = src.year + month // 12
    month = month % 12 + 1
    day = min(src.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        json.dump({"error": "No input provided"}, sys.stdout)
        return

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        json.dump({"error": f"Invalid JSON: {exc}"}, sys.stdout)
        return

    tool = envelope.get("tool", "")
    args = envelope.get("args") or envelope.get("arguments") or {}

    # Strip domain prefix if present (Rust binary preserves hyphens, dispatch.py converts to underscores)
    for prefix in ("pv_engine_nexvigilant_com_", "pv-engine_nexvigilant_com_", "guardian_nexvigilant_com_"):
        if tool.startswith(prefix):
            tool = tool[len(prefix):]
            break

    # Normalize underscores to hyphens for tool lookup
    tool_normalized = tool.replace("_", "-")

    handler = HANDLERS.get(tool_normalized) or HANDLERS.get(tool)
    if not handler:
        json.dump({
            "error": f"Unknown tool: {tool}",
            "available": list(HANDLERS.keys()),
        }, sys.stdout)
        return

    try:
        result = handler(args)
        json.dump(result, sys.stdout, default=str)
    except Exception as exc:
        json.dump({"error": str(exc), "tool": tool}, sys.stdout)


if __name__ == "__main__":
    main()
