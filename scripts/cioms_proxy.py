#!/usr/bin/env python3
"""
CIOMS Proxy — routes MoltBrowser hub tool calls for CIOMS domain tools.

Usage:
    echo '{"tool": "get-working-groups", "args": {}}' | python3 cioms_proxy.py

CIOMS (Council for International Organizations of Medical Sciences) is a
public organization but has no structured API. Tools are SEMI-LIVE with
hardcoded reference data derived from official CIOMS publications.

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.
"""

import json
import sys


def get_working_groups(args: dict) -> dict:
    """
    Tool: get-working-groups

    Returns the list of active CIOMS working groups with their focus areas.
    SEMI-LIVE: hardcoded from official CIOMS publications and website.
    """
    working_groups = [
        {
            "name": "Working Group on Vaccine Safety",
            "status": "current",
            "focus_area": "Harmonization of vaccine safety assessment, "
                          "benefit-risk evaluation for vaccines, "
                          "and standardization of vaccine pharmacovigilance practices",
            "key_outputs": [
                "CIOMS Guide to Vaccine Safety Communication",
                "CIOMS Guide to Active Vaccine Safety Surveillance",
            ],
        },
        {
            "name": "Working Group on Drug Safety Signal Detection and Management (CIOMS VIII)",
            "status": "completed",
            "focus_area": "Practical aspects of signal detection, prioritization, "
                          "and management in pharmacovigilance, including "
                          "statistical and clinical evaluation methodologies",
            "key_outputs": [
                "CIOMS VIII: Practical Aspects of Signal Detection in Pharmacovigilance",
            ],
        },
        {
            "name": "Working Group on Practical Pharmacovigilance (CIOMS V)",
            "status": "completed",
            "focus_area": "Current challenges in pharmacovigilance including "
                          "benefit-risk assessment, signal detection, "
                          "risk management, and communication of safety information",
            "key_outputs": [
                "CIOMS V: Current Challenges in Pharmacovigilance: Pragmatic Approaches",
            ],
        },
        {
            "name": "Working Group on Benefit-Risk Balance (CIOMS IV)",
            "status": "completed",
            "focus_area": "Frameworks and methodologies for evaluating the "
                          "benefit-risk balance of medicinal products, "
                          "including structured approaches to benefit-risk assessment",
            "key_outputs": [
                "CIOMS IV: Benefit-Risk Balance for Marketed Drugs",
            ],
        },
        {
            "name": "Working Group on Standardised MedDRA Queries (SMQs)",
            "status": "current",
            "focus_area": "Development and maintenance of Standardised MedDRA Queries "
                          "for consistent retrieval of safety data from MedDRA-coded "
                          "adverse event databases",
            "key_outputs": [
                "SMQ Introductory Guide",
                "Ongoing SMQ development and revision with each MedDRA release",
            ],
        },
    ]

    return {
        "status": "ok",
        "source": "CIOMS (cioms.ch) — semi-live hardcoded reference data",
        "count": len(working_groups),
        "results": working_groups,
    }


def get_cioms_form(args: dict) -> dict:
    """
    Tool: get-cioms-form

    Returns the CIOMS I form structure — the standard Individual Case Safety
    Report (ICSR) form used internationally for reporting adverse drug reactions
    to regulatory authorities.
    SEMI-LIVE: hardcoded schema of the standard CIOMS I form fields.
    """
    form_structure = {
        "form_name": "CIOMS I Form",
        "full_title": "Council for International Organizations of Medical Sciences — "
                      "Suspected Adverse Reaction Report Form",
        "purpose": "Standard form for reporting Individual Case Safety Reports (ICSRs) "
                   "of suspected adverse drug reactions from healthcare professionals "
                   "and marketing authorization holders to regulatory authorities",
        "sections": [
            {
                "section": "I",
                "title": "Patient Information",
                "fields": [
                    {"field": "patient_initials", "type": "text", "description": "Patient initials or identifier"},
                    {"field": "country", "type": "text", "description": "Country where the reaction occurred"},
                    {"field": "date_of_birth", "type": "date", "description": "Date of birth (or age at time of event)"},
                    {"field": "age", "type": "number", "description": "Age at time of event"},
                    {"field": "sex", "type": "choice", "options": ["Male", "Female"], "description": "Patient sex"},
                    {"field": "weight_kg", "type": "number", "description": "Weight in kilograms"},
                    {"field": "height_cm", "type": "number", "description": "Height in centimeters"},
                ],
            },
            {
                "section": "II",
                "title": "Suspected Adverse Reaction(s)",
                "fields": [
                    {"field": "reaction_description", "type": "text", "description": "Full description of reaction(s) including relevant tests/lab data"},
                    {"field": "reaction_start_date", "type": "date", "description": "Date reaction started"},
                    {"field": "reaction_end_date", "type": "date", "description": "Date reaction ended (if applicable)"},
                    {"field": "reaction_duration", "type": "text", "description": "Duration of reaction"},
                    {"field": "seriousness_criteria", "type": "multi_choice", "options": [
                        "Death",
                        "Life-threatening",
                        "Hospitalization (initial or prolonged)",
                        "Disability/Incapacity",
                        "Congenital anomaly/Birth defect",
                        "Other medically important condition",
                    ], "description": "ICH E2A seriousness criteria"},
                    {"field": "outcome", "type": "choice", "options": [
                        "Recovered/Resolved",
                        "Recovering/Resolving",
                        "Not recovered/Not resolved",
                        "Recovered with sequelae",
                        "Fatal",
                        "Unknown",
                    ], "description": "Outcome of reaction at time of report"},
                ],
            },
            {
                "section": "III",
                "title": "Suspected Drug(s)",
                "fields": [
                    {"field": "drug_name", "type": "text", "description": "Brand name and/or INN (generic name)"},
                    {"field": "indication", "type": "text", "description": "Indication for use"},
                    {"field": "daily_dose", "type": "text", "description": "Daily dose and units"},
                    {"field": "route_of_administration", "type": "text", "description": "Route of administration"},
                    {"field": "therapy_start_date", "type": "date", "description": "Date therapy started"},
                    {"field": "therapy_end_date", "type": "date", "description": "Date therapy stopped"},
                    {"field": "therapy_duration", "type": "text", "description": "Duration of treatment"},
                    {"field": "dechallenge", "type": "choice", "options": ["Yes — reaction abated", "Yes — reaction did not abate", "Not applicable", "Unknown"], "description": "Did reaction abate after drug was stopped?"},
                    {"field": "rechallenge", "type": "choice", "options": ["Yes — reaction recurred", "Yes — reaction did not recur", "Not applicable", "Unknown"], "description": "Did reaction recur on re-administration?"},
                    {"field": "batch_number", "type": "text", "description": "Batch/lot number"},
                    {"field": "expiry_date", "type": "date", "description": "Expiration date of product"},
                ],
            },
            {
                "section": "IV",
                "title": "Concomitant Drugs and History",
                "fields": [
                    {"field": "concomitant_drugs", "type": "text_list", "description": "Other drugs taken concurrently (name, dose, route, dates)"},
                    {"field": "relevant_history", "type": "text", "description": "Relevant medical history, allergies, previous drug reactions"},
                ],
            },
            {
                "section": "V",
                "title": "Reporter Information",
                "fields": [
                    {"field": "reporter_name", "type": "text", "description": "Name of reporter"},
                    {"field": "reporter_address", "type": "text", "description": "Address of reporter"},
                    {"field": "reporter_qualification", "type": "choice", "options": ["Physician", "Pharmacist", "Other health professional", "Lawyer", "Consumer"], "description": "Professional qualification"},
                    {"field": "report_date", "type": "date", "description": "Date of this report"},
                ],
            },
            {
                "section": "VI",
                "title": "Administrative Information",
                "fields": [
                    {"field": "report_source", "type": "choice", "options": ["Clinical trial", "Literature", "Healthcare professional", "Regulatory authority", "Other"], "description": "Source of report"},
                    {"field": "case_number", "type": "text", "description": "Manufacturer/reporting organization case number"},
                    {"field": "date_received", "type": "date", "description": "Date report was first received by company"},
                    {"field": "report_type", "type": "choice", "options": ["Initial", "Follow-up"], "description": "Type of report"},
                ],
            },
        ],
    }

    return {
        "status": "ok",
        "source": "CIOMS I form standard — semi-live hardcoded reference schema",
        "form": form_structure,
    }


def search_publications(args: dict) -> dict:
    """
    Tool: search-publications

    Searches CIOMS publications catalog. STUB — returns placeholder guidance.
    CIOMS publications are available at cioms.ch/publications/ but there is
    no structured API.
    """
    query = args.get("query", "").strip()

    return {
        "status": "stub",
        "message": "search-publications is not yet implemented. "
                   "CIOMS does not provide a structured API for publication search. "
                   "Visit https://cioms.ch/publications/ to browse the catalog manually.",
        "query": query or None,
        "count": 0,
        "results": [],
    }


TOOL_DISPATCH = {
    "get-working-groups": get_working_groups,
    "get-cioms-form": get_cioms_form,
    "search-publications": search_publications,
}


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        result = {"status": "error", "message": "No input received on stdin", "count": 0, "results": []}
        print(json.dumps(result))
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        result = {"status": "error", "message": f"Invalid JSON input: {exc}", "count": 0, "results": []}
        print(json.dumps(result))
        sys.exit(1)

    tool_name = payload.get("tool", "").strip()
    args = payload.get("arguments", payload.get("args", {}))

    if tool_name not in TOOL_DISPATCH:
        known = list(TOOL_DISPATCH.keys())
        result = {
            "status": "error",
            "message": f"Unknown tool '{tool_name}'. Known tools: {known}",
            "count": 0,
            "results": [],
        }
        print(json.dumps(result))
        sys.exit(1)

    handler = TOOL_DISPATCH[tool_name]
    result = handler(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
