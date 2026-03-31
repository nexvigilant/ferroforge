#!/usr/bin/env python3
"""
Regulatory Agency Cross-Reference Mesh Proxy — NexVigilant Station

Domain: regulatory-mesh.nexvigilant.com
Lateral linkages: maps equivalent actions, terminology, and systems across 11 PV agencies.
"""

import json
import sys

# Regulatory action equivalence map — lateral linkages
ACTION_EQUIVALENCE = {
    "boxed_warning": {
        "FDA": "Boxed Warning (Black Box)",
        "EMA": "Contraindication / Special Warning (SmPC Section 4.3-4.4)",
        "PMDA": "Red Frame Warning (赤枠警告)",
        "Health_Canada": "Serious Warnings and Precautions Box",
        "MHRA": "Class 1 Drug Alert / Contraindication",
        "TGA": "Black Box Warning (PI Section 4.3-4.4)",
        "Swissmedic": "Important warnings (Wichtige Hinweise)",
        "ANVISA": "Contraindicação em bula",
    },
    "safety_communication": {
        "FDA": "MedWatch Safety Alert / Drug Safety Communication",
        "EMA": "PRAC Recommendation / Referral Outcome",
        "PMDA": "Safety Information (安全性情報)",
        "Health_Canada": "Summary Safety Review / Health Product InfoWatch",
        "MHRA": "Drug Safety Update Article",
        "TGA": "Safety Advisory",
        "Swissmedic": "Direct Healthcare Professional Communication (DHPC)",
        "HSA": "Dear Healthcare Professional Letter",
        "Medsafe": "Prescriber Update Article",
        "ANVISA": "Alerta de Farmacovigilância",
        "COFEPRIS": "Comunicado de Farmacovigilancia",
    },
    "recall": {
        "FDA": "Drug Recall (Class I/II/III)",
        "EMA": "Withdrawal / Suspension of Marketing Authorisation",
        "PMDA": "Emergency Safety Information / Recall (回収)",
        "Health_Canada": "Type I/II/III Recall",
        "MHRA": "Class 1/2/3/4 Drug Alert",
        "TGA": "Recall Action (hazard classification)",
        "Swissmedic": "Chargenrückruf",
        "HSA": "Product Recall",
        "Medsafe": "Recall Notice",
        "ANVISA": "Recolhimento voluntário / Interdição",
    },
    "rmp": {
        "FDA": "REMS (Risk Evaluation and Mitigation Strategy)",
        "EMA": "Risk Management Plan (RMP) — EU-RMP",
        "PMDA": "Risk Management Plan (医薬品リスク管理計画)",
        "Health_Canada": "Risk Management Plan (harmonized with EU)",
        "MHRA": "Risk Management Plan (UK-RMP, post-Brexit)",
        "TGA": "Risk Management Plan (AU-RMP)",
        "Swissmedic": "Risk Management Plan (CH-RMP)",
    },
    "periodic_report": {
        "FDA": "DSUR / PSUR (IND: DSUR, NDA: PBRER)",
        "EMA": "PSUR/PBRER (per EURD list)",
        "PMDA": "Periodic Safety Update Report (定期安全性最新報告)",
        "Health_Canada": "PSUR/PBRER (aligned with ICH E2C(R2))",
        "MHRA": "PSUR/PBRER (UK EURD list)",
        "TGA": "PSUR/PBRER",
    },
}

# Expedited reporting timelines (days)
REPORTING_TIMELINES = {
    "fatal_life_threatening": {
        "FDA": {"days": 15, "mechanism": "MedWatch 3500A", "regulation": "21 CFR 314.80"},
        "EMA": {"days": 15, "mechanism": "EudraVigilance ICSR", "regulation": "Regulation (EU) No 1235/2010"},
        "PMDA": {"days": 15, "mechanism": "PMDA ICSR", "regulation": "PAL Article 77-4-2"},
        "Health_Canada": {"days": 15, "mechanism": "MedEffect ICSR", "regulation": "C.01.017"},
        "MHRA": {"days": 15, "mechanism": "Yellow Card ICSR", "regulation": "SI 2012/1916"},
        "TGA": {"days": 15, "mechanism": "TGA ICSR", "regulation": "Therapeutic Goods Act 1989"},
        "Swissmedic": {"days": 15, "mechanism": "ElViS ICSR", "regulation": "TPA Art. 59"},
        "HSA": {"days": 15, "mechanism": "PRISM ADR", "regulation": "Health Products Act"},
        "ANVISA": {"days": 15, "mechanism": "Notivisa ICSR", "regulation": "RDC 4/2009"},
    },
    "serious_non_fatal": {
        "FDA": {"days": 15, "note": "unexpected serious"},
        "EMA": {"days": 15, "note": "all serious from EEA, 90d non-EEA"},
        "PMDA": {"days": 15, "note": "known serious: 30 days"},
        "Health_Canada": {"days": 15},
        "MHRA": {"days": 15},
        "TGA": {"days": 15},
    },
    "periodic": {
        "FDA": {"days": 90, "note": "Quarterly for first 3 years post-approval, then annual"},
        "EMA": {"note": "Per EURD list — 6-monthly or annual"},
        "PMDA": {"note": "Semi-annual for first 2 years (early post-marketing phase)"},
    },
}

# Causality assessment methods per agency
CAUSALITY_METHODS = {
    "FDA": {"primary": "No mandated algorithm", "common": "Naranjo, WHO-UMC", "note": "Case-by-case clinical judgment"},
    "EMA": {"primary": "WHO-UMC system (recommended)", "common": "Naranjo", "note": "GVP Module VI"},
    "PMDA": {"primary": "PMDA causality categories", "common": "WHO-UMC adapted", "note": "5 categories: Certain to Unassessable"},
    "Health_Canada": {"primary": "WHO-UMC system", "common": "Naranjo", "note": "Canada Vigilance assessment"},
    "MHRA": {"primary": "WHO-UMC system", "common": "Naranjo", "note": "Yellow Card assessment"},
    "WHO": {"primary": "WHO-UMC system", "categories": ["Certain", "Probable", "Possible", "Unlikely", "Conditional", "Unassessable"]},
}

# Database coverage map
DATABASE_COVERAGE = {
    "FDA": {"db": "FAERS", "access": "public_api", "tool": "api_fda_gov_search_adverse_events", "reports_annual": "~2M"},
    "EMA": {"db": "EudraVigilance", "access": "public_portal", "tool": "eudravigilance_ema_europa_eu_search_reports", "reports_annual": "~1.8M"},
    "WHO": {"db": "VigiBase", "access": "vigiaccess_public", "tool": "vigiaccess_org_search_reports", "reports_annual": "~34M cumulative"},
    "PMDA": {"db": "JADER", "access": "web_portal", "tool": "www_pmda_go_jp_get_adverse_reactions", "reports_annual": "~60K"},
    "Health_Canada": {"db": "Canada Vigilance", "access": "web_portal", "tool": "recalls_rappels_canada_ca_search_adverse_reactions", "reports_annual": "~80K"},
    "MHRA": {"db": "Yellow Card", "access": "web_portal", "tool": "www_gov_uk_search_yellow_card_reports", "reports_annual": "~40K"},
    "TGA": {"db": "DAEN", "access": "web_portal", "tool": "www_tga_gov_au_search_daen_reports", "reports_annual": "~20K"},
}


def _drug(a: dict) -> str:
    return (a.get("drug_name") or a.get("drug") or a.get("query") or "").strip()


def map_equivalent_actions(args: dict) -> dict:
    action_type = args.get("action_type", "").strip().lower().replace(" ", "_")
    source = args.get("source_agency", "").strip()
    if not action_type:
        return {"status": "ok", "source": "Regulatory Action Equivalence Map", "available_types": list(ACTION_EQUIVALENCE.keys())}
    mapping = ACTION_EQUIVALENCE.get(action_type)
    if not mapping:
        return {"status": "error", "message": f"Unknown action_type '{action_type}'. Available: {list(ACTION_EQUIVALENCE.keys())}"}
    return {
        "status": "ok", "source": "Regulatory Action Equivalence",
        "action_type": action_type,
        "source_agency": source or "all",
        "equivalences": mapping,
        "note": "Equivalent regulatory actions across jurisdictions. Severity and legal weight may differ.",
    }


def translate_terminology(args: dict) -> dict:
    term = args.get("term", "").strip()
    from_ag = args.get("from_agency", "").strip()
    to_ag = args.get("to_agency", "").strip()
    if not term:
        return {"status": "error", "message": "term is required"}
    term_lower = term.lower()
    results = {}
    for action_type, mapping in ACTION_EQUIVALENCE.items():
        for agency, desc in mapping.items():
            if term_lower in desc.lower():
                results[action_type] = mapping
                break
    if not results:
        return {"status": "ok", "source": "Terminology Translation", "term": term, "matches": [], "note": "No exact match. Try a broader action type."}
    return {
        "status": "ok", "source": "Terminology Translation",
        "term": term, "from": from_ag or "detected", "to": to_ag or "all",
        "translations": results,
    }


def get_reporting_requirements(args: dict) -> dict:
    drug = _drug(args)
    event_type = args.get("event_type", "fatal_life_threatening").strip().lower().replace(" ", "_")
    timeline = REPORTING_TIMELINES.get(event_type)
    if not timeline:
        return {"status": "ok", "source": "Reporting Timelines", "available_types": list(REPORTING_TIMELINES.keys())}
    return {
        "status": "ok", "source": "Cross-Jurisdictional Reporting Requirements",
        "drug": drug or "generic",
        "event_type": event_type,
        "timelines": timeline,
        "note": "Most major agencies align at 15 calendar days for fatal/life-threatening events per ICH E2D harmonization.",
    }


def compare_classification_systems(args: dict) -> dict:
    system = args.get("system", "causality").strip().lower()
    if system == "causality":
        return {"status": "ok", "source": "Causality Assessment Systems", "systems": CAUSALITY_METHODS}
    elif system in ("reporting", "timelines"):
        return {"status": "ok", "source": "Reporting Timelines", "timelines": REPORTING_TIMELINES}
    elif system in ("action", "actions"):
        return {"status": "ok", "source": "Action Types", "types": {k: list(v.keys()) for k, v in ACTION_EQUIVALENCE.items()}}
    return {"status": "ok", "source": "Classification Systems", "available": ["causality", "reporting", "actions"]}


def get_mutual_recognition(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    return {
        "status": "ok", "source": "Mutual Recognition & Reliance Pathways",
        "drug": drug,
        "pathways": [
            {"name": "FDA-EMA Parallel Scientific Advice", "agencies": ["FDA", "EMA"], "type": "joint_review"},
            {"name": "ACSS Consortium", "agencies": ["Australia", "Canada", "Singapore", "Switzerland", "UK"], "type": "work_sharing"},
            {"name": "Project Orbis", "agencies": ["FDA", "Health Canada", "TGA", "Swissmedic", "HSA", "MHRA"], "type": "oncology_concurrent_review"},
            {"name": "ICH E2B(R3)", "agencies": ["all ICH members"], "type": "harmonized_icsr_format"},
            {"name": "WHO Prequalification", "agencies": ["WHO + member states"], "type": "prequalification"},
            {"name": "IGDRP", "agencies": ["30+ agencies"], "type": "generic_drug_regulators"},
        ],
        "note": f"Check if '{drug}' was reviewed under any of these pathways for expedited/shared regulatory assessment.",
    }


def map_safety_database_coverage(args: dict) -> dict:
    return {
        "status": "ok", "source": "Global PV Database Coverage Map",
        "databases": DATABASE_COVERAGE,
        "note": "Annual report volumes are approximate. FAERS and EudraVigilance are largest. VigiBase (WHO) is the global aggregate.",
        "station_coverage": "All databases have NexVigilant Station tools for querying.",
    }


DISPATCH = {
    "map-equivalent-actions": map_equivalent_actions,
    "translate-terminology": translate_terminology,
    "get-reporting-requirements": get_reporting_requirements,
    "compare-classification-systems": compare_classification_systems,
    "get-mutual-recognition": get_mutual_recognition,
    "map-safety-database-coverage": map_safety_database_coverage,
}


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"status": "error", "message": "No input"}))
        return
    try:
        p = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        return
    tool = p.get("tool", "").strip()
    args = p.get("arguments", p.get("args", {}))
    h = DISPATCH.get(tool)
    if not h:
        print(json.dumps({"status": "error", "message": f"Unknown '{tool}'"}))
        return
    try:
        print(json.dumps(h(args)))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))


if __name__ == "__main__":
    main()
