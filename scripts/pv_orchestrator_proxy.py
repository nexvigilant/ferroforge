#!/usr/bin/env python3
"""
PV Orchestrator Proxy — workflow routing, intent classification, findings summarization.

Maps PV objectives to Station tool sequences. Pure computation —
uses codified workflow templates, not LLM inference.

Source logic: domains/agents/pv-orchestrator/pv_orchestrator_agent.py
"""

import json
import sys
import re

# ─── Workflow Templates ──────────────────────────────────────────────────────

WORKFLOW_TEMPLATES = {
    "signal_detection": {
        "name": "Signal Detection Investigation",
        "steps": [
            {"step": 1, "action": "Resolve drug identity", "tool": "rxnav_nlm_nih_gov_get_rxcui", "params": ["drug"]},
            {"step": 2, "action": "Search FAERS adverse events", "tool": "api_fda_gov_search_adverse_events", "params": ["drug"]},
            {"step": 3, "action": "Compute PRR disproportionality", "tool": "calculate_nexvigilant_com_compute_prr", "params": ["drug", "event"]},
            {"step": 4, "action": "Compute ROR disproportionality", "tool": "calculate_nexvigilant_com_compute_ror", "params": ["drug", "event"]},
            {"step": 5, "action": "Compute IC (Information Component)", "tool": "calculate_nexvigilant_com_compute_ic", "params": ["drug", "event"]},
            {"step": 6, "action": "Compute EBGM (Empirical Bayes)", "tool": "calculate_nexvigilant_com_compute_ebgm", "params": ["drug", "event"]},
            {"step": 7, "action": "Check drug label for event", "tool": "dailymed_nlm_nih_gov_get_adverse_reactions", "params": ["drug"]},
            {"step": 8, "action": "Search PubMed safety literature", "tool": "pubmed_ncbi_nlm_nih_gov_search_signal_literature", "params": ["drug", "event"]},
        ],
    },
    "causality_assessment": {
        "name": "Causality Assessment",
        "steps": [
            {"step": 1, "action": "Resolve drug identity", "tool": "rxnav_nlm_nih_gov_get_rxcui", "params": ["drug"]},
            {"step": 2, "action": "Run Naranjo algorithm", "tool": "pv-engine_nexvigilant_com_assess_naranjo", "params": ["drug", "event", "q1-q10"]},
            {"step": 3, "action": "Run WHO-UMC assessment", "tool": "pv-engine_nexvigilant_com_assess_who_umc", "params": ["drug", "event", "criteria"]},
            {"step": 4, "action": "Classify seriousness", "tool": "pv-engine_nexvigilant_com_classify_seriousness", "params": ["event_description"]},
            {"step": 5, "action": "Determine expedited reporting", "tool": "pv-engine_nexvigilant_com_determine_expedited_reporting", "params": ["is_serious", "is_unexpected"]},
            {"step": 6, "action": "Search case reports", "tool": "pubmed_ncbi_nlm_nih_gov_search_case_reports", "params": ["drug", "event"]},
        ],
    },
    "regulatory_reporting": {
        "name": "Regulatory Reporting Workflow",
        "steps": [
            {"step": 1, "action": "Validate ICSR minimum data", "tool": "pv-engine_nexvigilant_com_validate_icsr_minimum", "params": ["reporter", "patient", "drug", "event"]},
            {"step": 2, "action": "Classify seriousness", "tool": "pv-engine_nexvigilant_com_classify_seriousness", "params": ["event_description"]},
            {"step": 3, "action": "Determine expedited reporting", "tool": "pv-engine_nexvigilant_com_determine_expedited_reporting", "params": ["is_serious", "is_unexpected", "region"]},
            {"step": 4, "action": "Calculate submission deadline", "tool": "pv-engine_nexvigilant_com_calculate_submission_deadline", "params": ["awareness_date", "report_type"]},
            {"step": 5, "action": "Check deadline compliance", "tool": "pv-engine_nexvigilant_com_check_deadline_compliance", "params": ["awareness_date", "submission_date", "report_type"]},
        ],
    },
    "benefit_risk": {
        "name": "Benefit-Risk Assessment",
        "steps": [
            {"step": 1, "action": "Resolve drug identity", "tool": "rxnav_nlm_nih_gov_get_rxcui", "params": ["drug"]},
            {"step": 2, "action": "Search clinical trials", "tool": "clinicaltrials_gov_search_trials", "params": ["drug"]},
            {"step": 3, "action": "Get FAERS safety profile", "tool": "api_fda_gov_search_adverse_events", "params": ["drug"]},
            {"step": 4, "action": "Get drug labeling", "tool": "dailymed_nlm_nih_gov_get_adverse_reactions", "params": ["drug"]},
            {"step": 5, "action": "Compute QBRI score", "tool": "benefit_risk_nexvigilant_com_compute_qbri", "params": ["benefit_effect", "risk_signal", "unmet_need"]},
        ],
    },
    "literature_review": {
        "name": "Safety Literature Review",
        "steps": [
            {"step": 1, "action": "Search PubMed for safety literature", "tool": "pubmed_ncbi_nlm_nih_gov_search_signal_literature", "params": ["drug", "event"]},
            {"step": 2, "action": "Search for case reports", "tool": "pubmed_ncbi_nlm_nih_gov_search_case_reports", "params": ["drug", "event"]},
            {"step": 3, "action": "Check ICH guidelines", "tool": "ich_org_search_guidelines", "params": ["query"]},
            {"step": 4, "action": "Check EMA safety signals", "tool": "ema_europa_eu_search_safety_signals", "params": ["drug"]},
        ],
    },
    "drug_safety_profile": {
        "name": "Complete Drug Safety Profile",
        "steps": [
            {"step": 1, "action": "Resolve drug identity", "tool": "rxnav_nlm_nih_gov_get_rxcui", "params": ["drug"]},
            {"step": 2, "action": "Get FAERS adverse events", "tool": "api_fda_gov_search_adverse_events", "params": ["drug"]},
            {"step": 3, "action": "Run signal detection on top events", "tool": "calculate_nexvigilant_com_compute_prr", "params": ["drug", "event"]},
            {"step": 4, "action": "Get drug labeling", "tool": "dailymed_nlm_nih_gov_get_adverse_reactions", "params": ["drug"]},
            {"step": 5, "action": "Get boxed warnings", "tool": "dailymed_nlm_nih_gov_get_boxed_warning", "params": ["drug"]},
            {"step": 6, "action": "Search safety literature", "tool": "pubmed_ncbi_nlm_nih_gov_search_signal_literature", "params": ["drug"]},
            {"step": 7, "action": "Search clinical trials", "tool": "clinicaltrials_gov_search_trials", "params": ["drug"]},
            {"step": 8, "action": "Check FDA approval history", "tool": "accessdata_fda_gov_search_approvals", "params": ["drug"]},
        ],
    },
}

# ─── Intent Classification ───────────────────────────────────────────────────

INTENT_KEYWORDS = {
    "signal_detection": ["signal", "detect", "prr", "ror", "disproportionality", "faers signal", "safety signal"],
    "causality_assessment": ["causality", "causal", "naranjo", "who-umc", "caused", "related to", "dechallenge", "rechallenge"],
    "regulatory_reporting": ["report", "expedited", "15-day", "7-day", "90-day", "deadline", "submission", "icsr", "e2b", "regulatory"],
    "benefit_risk": ["benefit", "risk", "qbri", "benefit-risk", "weigh", "favorable"],
    "literature_review": ["literature", "pubmed", "case report", "published", "evidence", "study"],
    "drug_safety_profile": ["safety profile", "complete profile", "drug profile", "full investigation", "overview"],
    "competitive_analysis": ["compare", "versus", "vs", "head-to-head", "competitor", "competitive"],
}


def classify_pv_intent(args: dict) -> dict:
    query = str(args.get("query", "")).lower().strip()
    if not query:
        return {"error": "query is required"}

    scores = {}
    for category, keywords in INTENT_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in query)
        if score > 0:
            scores[category] = score

    if not scores:
        category = "drug_safety_profile"
        confidence = 0.3
    else:
        category = max(scores, key=scores.get)
        confidence = min(1.0, scores[category] / 3.0)

    template = WORKFLOW_TEMPLATES.get(category, WORKFLOW_TEMPLATES["drug_safety_profile"])
    tools = [step["tool"] for step in template["steps"]]

    return {
        "query": query,
        "category": category,
        "confidence": round(confidence, 2),
        "recommended_tools": tools,
        "workflow_template": template["name"],
        "all_scores": scores if scores else {"drug_safety_profile": 0.3},
    }


# ─── Workflow Routing ─────────────────────────────────────────────────────────

def route_pv_workflow(args: dict) -> dict:
    objective = str(args.get("objective", "")).strip()
    drug = args.get("drug", "")
    event = args.get("event", "")
    context = args.get("context", "post_marketing")

    if not objective:
        return {"error": "objective is required"}

    # Classify intent to pick workflow
    intent = classify_pv_intent({"query": objective})
    category = intent["category"]
    template = WORKFLOW_TEMPLATES.get(category, WORKFLOW_TEMPLATES["drug_safety_profile"])

    steps = []
    for step in template["steps"]:
        s = dict(step)
        if drug:
            s["example_params"] = {"drug": drug}
            if event:
                s["example_params"]["event"] = event
        steps.append(s)

    return {
        "objective": objective,
        "workflow_type": category,
        "workflow_name": template["name"],
        "steps": steps,
        "estimated_tools": len(steps),
        "context": context,
        "drug": drug or None,
        "event": event or None,
        "note": "Execute each step sequentially. Pass outputs from earlier steps as inputs to later ones.",
    }


# ─── Findings Summary ────────────────────────────────────────────────────────

def summarize_pv_findings(args: dict) -> dict:
    drug = str(args.get("drug", "Unknown drug"))
    signal_data = args.get("signal_data") or {}
    causality_data = args.get("causality_data") or {}
    regulatory_data = args.get("regulatory_data") or {}
    fmt = str(args.get("format", "narrative"))

    # Signal summary
    prr = signal_data.get("prr")
    ror = signal_data.get("ror")
    ic = signal_data.get("ic")
    ebgm = signal_data.get("ebgm")
    signal_detected = any([
        prr is not None and float(prr) > 2,
        ror is not None and float(ror) > 2,
        ic is not None and float(ic) > 0,
        ebgm is not None and float(ebgm) > 2,
    ])

    signal_status = "Signal detected" if signal_detected else "No signal detected"
    metrics = []
    if prr is not None:
        metrics.append(f"PRR={float(prr):.2f}")
    if ror is not None:
        metrics.append(f"ROR={float(ror):.2f}")
    if ic is not None:
        metrics.append(f"IC={float(ic):.2f}")
    if ebgm is not None:
        metrics.append(f"EBGM={float(ebgm):.2f}")

    # Causality summary
    naranjo_score = causality_data.get("score")
    naranjo_cat = causality_data.get("category", "")
    who_cat = causality_data.get("who_umc_category", "")

    # Regulatory summary
    report_type = regulatory_data.get("report_type", "")
    deadline = regulatory_data.get("deadline_days", "")
    is_expedited = regulatory_data.get("is_expedited", False)

    # Build narrative
    parts = [f"Safety assessment for {drug}:"]

    if metrics:
        parts.append(f"Signal detection: {signal_status}. Metrics: {', '.join(metrics)}.")

    if naranjo_score is not None:
        parts.append(f"Causality (Naranjo): Score {naranjo_score} — {naranjo_cat}.")
    if who_cat:
        parts.append(f"Causality (WHO-UMC): {who_cat}.")

    if report_type:
        parts.append(f"Regulatory: {report_type} report, {deadline}-day deadline. Expedited: {'Yes' if is_expedited else 'No'}.")

    # Recommendation
    if signal_detected and naranjo_score is not None and int(naranjo_score) >= 5:
        recommendation = "Further investigation warranted. Consider enhanced monitoring and regulatory notification."
    elif signal_detected:
        recommendation = "Statistical signal detected. Clinical review recommended before regulatory action."
    else:
        recommendation = "No actionable signal at this time. Continue routine surveillance."

    summary = " ".join(parts)

    return {
        "drug": drug,
        "summary": summary,
        "signal_status": signal_status,
        "signal_metrics": metrics,
        "causality_naranjo": f"Score {naranjo_score} ({naranjo_cat})" if naranjo_score else "Not assessed",
        "causality_who_umc": who_cat or "Not assessed",
        "regulatory_action": f"{report_type} ({deadline} days)" if report_type else "Not determined",
        "recommendation": recommendation,
    }


# ─── Dispatch ─────────────────────────────────────────────────────────────────

HANDLERS = {
    "route-pv-workflow": route_pv_workflow,
    "classify-pv-intent": classify_pv_intent,
    "summarize-pv-findings": summarize_pv_findings,
}


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        json.dump({"error": "No input"}, sys.stdout)
        return

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    tool = envelope.get("tool", "")
    args = envelope.get("args") or envelope.get("arguments") or {}

    for prefix in ("orchestrator_nexvigilant_com_",):
        if tool.startswith(prefix):
            tool = tool[len(prefix):]
            break

    tool_normalized = tool.replace("_", "-")
    handler = HANDLERS.get(tool_normalized) or HANDLERS.get(tool)
    if not handler:
        json.dump({"error": f"Unknown tool: {tool}", "available": list(HANDLERS.keys())}, sys.stdout)
        return

    try:
        json.dump(handler(args), sys.stdout, default=str)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
