#!/usr/bin/env python3
"""
Academy Course Builder Proxy — KSB decomposition, learning objectives, PV readiness.

Pure computation — no external API calls. The KSB framework and PV readiness
assessment use codified domain knowledge from PDC v4.1 (15 domains, 21 EPAs).

Source logic: domains/education/course-builder/course-builder-service/app/services/
"""

import json
import sys

# ─── PDC v4.1 Domain Knowledge ──────────────────────────────────────────────

PDC_DOMAINS = {
    "D01": "Case Management & Processing",
    "D02": "Medical Terminology & Coding",
    "D03": "Adverse Event Assessment",
    "D04": "Regulatory Requirements",
    "D05": "Regulatory Submissions",
    "D06": "Medication Errors",
    "D07": "Epidemiology & Biostatistics",
    "D08": "Signal Detection",
    "D09": "Signal Evaluation",
    "D10": "Risk Management",
    "D11": "Risk Minimization",
    "D12": "Quality & Compliance",
    "D13": "Regulatory Negotiations",
    "D14": "Communication & Stakeholders",
    "D15": "Strategic Leadership",
}

EPA_LEVELS = {
    1: "Process ICSRs",
    2: "Conduct Safety Surveillance",
    3: "Prepare Safety Communications",
    4: "Support Regulatory Submissions",
    5: "Evaluate Signal Detection Outputs",
    6: "Assess Medication Error Reports",
    7: "Develop Risk Minimization Strategies",
    8: "Lead Signal Investigation Teams",
    9: "Manage Regulatory Inspections",
    10: "Implement and Validate AI Tools",
}

BLOOM_VERBS = {
    "remember": ["define", "list", "identify", "recall", "recognize", "name"],
    "understand": ["explain", "describe", "summarize", "interpret", "classify", "compare"],
    "apply": ["apply", "demonstrate", "calculate", "use", "implement", "execute"],
    "analyze": ["analyze", "differentiate", "examine", "investigate", "categorize"],
    "evaluate": ["evaluate", "assess", "justify", "critique", "judge", "recommend"],
    "create": ["design", "develop", "construct", "formulate", "propose", "create"],
}

# ─── KSB Decomposition ──────────────────────────────────────────────────────

PV_KSB_TEMPLATES = {
    "signal detection": {
        "knowledge": [
            {"title": "Disproportionality Analysis Methods", "description": "Understanding of PRR, ROR, IC, and EBGM statistical measures for detecting safety signals in spontaneous reporting databases.", "learning_objectives": ["Define the four standard disproportionality measures", "Explain the 2x2 contingency table structure", "State Evans criteria thresholds (PRR>=2, chi-square>=3.841, N>=3)"], "key_points": ["PRR measures proportional reporting vs background", "ROR uses odds ratio approach", "IC uses information-theoretic framework", "EBGM uses empirical Bayes shrinkage"], "examples": ["Semaglutide + pancreatitis PRR=3.2 indicates signal", "Metformin + lactic acidosis as known signal"], "assessment_criteria": ["Can calculate PRR from contingency table", "Can interpret signal thresholds correctly"]},
            {"title": "Spontaneous Reporting Database Structure", "description": "Knowledge of FAERS, EudraVigilance, and VigiBase database structures, their strengths, limitations, and appropriate use cases.", "learning_objectives": ["Describe the structure of FDA FAERS quarterly data", "Identify limitations of spontaneous reporting (Weber effect, stimulated reporting)"], "key_points": ["FAERS receives ~2M reports annually", "Reporting is voluntary (except for manufacturers)", "Under-reporting is the primary limitation"], "examples": ["FAERS quarterly ASCII data format", "EudraVigilance EVDAS access"], "assessment_criteria": ["Can navigate FAERS data structure", "Can articulate reporting biases"]},
        ],
        "skills": [
            {"title": "Signal Detection Execution", "description": "Ability to run disproportionality analyses, interpret results, and triage signals for further evaluation.", "learning_objectives": ["Execute a multi-metric signal detection analysis", "Triage signals by clinical significance"], "key_points": ["Run all 4 metrics on every drug-event pair", "Apply clinical judgment to statistical findings", "Document rationale for signal prioritization"], "examples": ["Running PRR/ROR/IC/EBGM on a new drug", "Prioritizing signals for PRAC review"], "assessment_criteria": ["Can complete end-to-end signal detection", "Can write a signal prioritization memo"]},
        ],
        "behaviors": [
            {"title": "Scientific Rigor in Signal Evaluation", "description": "Professional conduct in approaching signal detection with appropriate skepticism, reproducibility, and documentation.", "learning_objectives": ["Apply scientific method to signal evaluation", "Document all analytical decisions with rationale"], "key_points": ["Avoid confirmation bias", "Document negative findings too", "Peer review before escalation"], "examples": ["Documenting why a signal was dismissed", "Seeking independent replication"], "assessment_criteria": ["Demonstrates reproducible analytical workflow", "Provides balanced signal assessment"]},
        ],
    },
    "causality assessment": {
        "knowledge": [
            {"title": "Causality Assessment Algorithms", "description": "Understanding of Naranjo, WHO-UMC, and RUCAM standardized assessment methods.", "learning_objectives": ["Describe the Naranjo 10-question scoring system", "Explain WHO-UMC 6-category classification", "Differentiate when to use RUCAM vs Naranjo"], "key_points": ["Naranjo: score-based (0-13), Definite/Probable/Possible/Doubtful", "WHO-UMC: criteria-based, Certain to Unassessable", "RUCAM: specific to hepatotoxicity"], "examples": ["Scoring a case of drug-induced liver injury with RUCAM", "WHO-UMC assessment of temporal relationship"], "assessment_criteria": ["Can score a case using all three algorithms", "Can select appropriate algorithm for case type"]},
        ],
        "skills": [
            {"title": "Case-Level Causality Determination", "description": "Ability to apply causality algorithms to individual case safety reports and document the assessment.", "learning_objectives": ["Complete a Naranjo assessment for a given case", "Apply WHO-UMC criteria systematically"], "key_points": ["Gather all relevant case information first", "Consider alternative causes thoroughly", "Document temporal relationship precisely"], "examples": ["Assessing dechallenge/rechallenge evidence", "Evaluating confounding medications"], "assessment_criteria": ["Produces consistent causality determinations", "Documents reasoning transparently"]},
        ],
        "behaviors": [
            {"title": "Patient-Centered Safety Mindset", "description": "Approaching causality assessment with the understanding that every case represents a patient.", "learning_objectives": ["Recognize the human impact behind each ICSR", "Balance urgency with thoroughness"], "key_points": ["Each case is a patient's experience", "Err on the side of safety when uncertain", "Follow up on incomplete information"], "examples": ["Requesting follow-up for insufficient data", "Escalating uncertain but serious cases"], "assessment_criteria": ["Demonstrates appropriate urgency for serious cases", "Shows empathy in case narratives"]},
        ],
    },
}


def decompose_ksb(args: dict) -> dict:
    topic = str(args.get("topic", "")).strip()
    domain = str(args.get("domain", "Pharmacovigilance")).strip()

    if not topic:
        return {"error": "topic is required"}

    # Check for template match
    topic_lower = topic.lower()
    template = None
    for key, tmpl in PV_KSB_TEMPLATES.items():
        if key in topic_lower:
            template = tmpl
            break

    if template:
        return {
            "topic": topic,
            "domain": domain,
            "knowledge": [{"type": "knowledge", **k} for k in template["knowledge"]],
            "skills": [{"type": "skill", **s} for s in template["skills"]],
            "behaviors": [{"type": "behavior", **b} for b in template["behaviors"]],
            "source": "PDC v4.1 competency framework",
            "note": "Pre-built KSB decomposition from NexVigilant competency model. For custom topics, use the full course builder pipeline.",
        }

    # Generic decomposition for unknown topics
    return {
        "topic": topic,
        "domain": domain,
        "knowledge": [{"type": "knowledge", "title": f"Foundations of {topic}", "description": f"Core concepts, definitions, and theoretical framework for {topic}.", "learning_objectives": [f"Define key terms in {topic}", f"Explain the purpose and scope of {topic}", f"Identify regulatory references relevant to {topic}"], "key_points": [f"Regulatory context for {topic}", "Historical development", "Current best practices"], "examples": [], "assessment_criteria": [f"Can articulate core concepts of {topic}"]}],
        "skills": [{"type": "skill", "title": f"Practical Application of {topic}", "description": f"Ability to apply {topic} concepts in real-world PV scenarios.", "learning_objectives": [f"Execute a standard {topic} workflow", f"Interpret results in context"], "key_points": ["Step-by-step execution", "Quality checks", "Documentation requirements"], "examples": [], "assessment_criteria": [f"Can complete a {topic} task independently"]}],
        "behaviors": [{"type": "behavior", "title": f"Professional Conduct in {topic}", "description": f"Appropriate professional attitudes and decision-making related to {topic}.", "learning_objectives": ["Apply ethical principles", "Document decisions with rationale"], "key_points": ["Patient safety first", "Regulatory compliance", "Scientific integrity"], "examples": [], "assessment_criteria": ["Demonstrates professional judgment"]}],
        "source": "Generic KSB template — use specific PV topics for richer decomposition",
    }


# ─── Learning Objectives ─────────────────────────────────────────────────────

def generate_learning_objectives(args: dict) -> dict:
    competency = str(args.get("competency", "")).strip()
    level = str(args.get("level", "apply")).lower().strip()

    if not competency:
        return {"error": "competency is required"}

    if level not in BLOOM_VERBS:
        level = "apply"

    verbs = BLOOM_VERBS[level]
    objectives = [
        f"{verbs[0].capitalize()} the key principles of {competency}",
        f"{verbs[1].capitalize()} how {competency} relates to patient safety outcomes",
        f"{verbs[2].capitalize()} {competency} in a regulatory pharmacovigilance context",
    ]

    if level in ("analyze", "evaluate", "create"):
        objectives.append(f"{verbs[3].capitalize()} the effectiveness of current {competency} practices")

    return {
        "competency": competency,
        "bloom_level": level,
        "objectives": objectives,
        "verb_bank": verbs,
        "format": "ABCD: Audience (PV professional), Behavior (verb + object), Condition (given context), Degree (measurable standard)",
    }


# ─── PV Readiness Assessment ─────────────────────────────────────────────────

def assess_pv_readiness(args: dict) -> dict:
    years = float(args.get("experience_years", 0))
    role = str(args.get("current_role", "")).strip()
    domains_str = str(args.get("domains_familiar", "")).strip()

    familiar = [d.strip().lower() for d in domains_str.split(",") if d.strip()] if domains_str else []

    # Map experience to EPA level
    if years >= 10:
        level = 5
        readiness = "Expert"
        track = "Leadership & Innovation (EPAs 11-21)"
    elif years >= 5:
        level = 4
        readiness = "Advanced"
        track = "Signal Management & Risk (EPAs 5-10)"
    elif years >= 2:
        level = 3
        readiness = "Intermediate"
        track = "Core PV Operations (EPAs 1-5)"
    elif years >= 0.5:
        level = 2
        readiness = "Early Career"
        track = "Foundations & Case Processing (EPAs 1-3)"
    else:
        level = 1
        readiness = "Beginner"
        track = "PV Fundamentals (Academy L1)"

    # Identify gaps
    domain_keywords = {
        "signal": ["D08", "D09"],
        "case": ["D01", "D03"],
        "coding": ["D02"],
        "regulatory": ["D04", "D05", "D12"],
        "risk": ["D10", "D11"],
        "communication": ["D14"],
    }
    covered_domains = set()
    for f in familiar:
        for keyword, codes in domain_keywords.items():
            if keyword in f:
                covered_domains.update(codes)

    all_domains = set(PDC_DOMAINS.keys())
    gaps = all_domains - covered_domains
    priority_gaps = [{"domain": d, "name": PDC_DOMAINS[d]} for d in sorted(gaps)[:5]]

    epa_coverage = {}
    for epa_num, epa_name in EPA_LEVELS.items():
        if epa_num <= level:
            epa_coverage[f"EPA-{epa_num}"] = {"name": epa_name, "status": "at_level"}
        else:
            epa_coverage[f"EPA-{epa_num}"] = {"name": epa_name, "status": "growth_area"}

    return {
        "readiness_level": readiness,
        "competency_level": level,
        "experience_years": years,
        "recommended_track": track,
        "epa_coverage": epa_coverage,
        "domains_covered": len(covered_domains),
        "domains_total": len(all_domains),
        "priority_gaps": priority_gaps,
        "next_step": f"Start with {track} in NexVigilant Academy",
    }


# ─── Dispatch ─────────────────────────────────────────────────────────────────

HANDLERS = {
    "decompose-ksb": decompose_ksb,
    "generate-learning-objectives": generate_learning_objectives,
    "assess-pv-readiness": assess_pv_readiness,
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

    for prefix in ("academy_nexvigilant_com_",):
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
