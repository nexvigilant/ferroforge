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


def get_seriousness_criteria(args: dict) -> dict:
    """
    Tool: get-seriousness-criteria

    Returns the ICH E2A seriousness criteria used internationally to classify
    adverse events as serious. These criteria determine expedited reporting
    obligations.
    SEMI-LIVE: hardcoded from ICH E2A guideline (1994, current).
    """
    criteria = [
        {
            "criterion": "Death",
            "code": "DEATH",
            "description": "The adverse event resulted in the patient's death.",
            "reporting_implication": "Expedited report required within 7 calendar days (initial) "
                                     "and 15 calendar days (follow-up).",
        },
        {
            "criterion": "Life-threatening",
            "code": "LIFE_THREATENING",
            "description": "The patient was at substantial risk of dying at the time of "
                           "the adverse event. It does NOT refer to an event that hypothetically "
                           "might have caused death if it were more severe.",
            "reporting_implication": "Expedited report required within 15 calendar days.",
        },
        {
            "criterion": "Hospitalization (initial or prolonged)",
            "code": "HOSPITALIZATION",
            "description": "The adverse event required inpatient hospitalization or prolonged "
                           "an existing hospitalization. Emergency room visits that do not "
                           "result in admission are generally NOT considered hospitalization.",
            "reporting_implication": "Expedited report required within 15 calendar days.",
        },
        {
            "criterion": "Disability/Incapacity",
            "code": "DISABILITY",
            "description": "The adverse event resulted in a substantial disruption of a person's "
                           "ability to conduct normal life functions.",
            "reporting_implication": "Expedited report required within 15 calendar days.",
        },
        {
            "criterion": "Congenital anomaly/Birth defect",
            "code": "CONGENITAL_ANOMALY",
            "description": "The adverse event resulted in a congenital anomaly or birth defect "
                           "in the offspring of a patient who received the drug.",
            "reporting_implication": "Expedited report required within 15 calendar days.",
        },
        {
            "criterion": "Other medically important condition",
            "code": "MEDICALLY_IMPORTANT",
            "description": "The event may not be immediately life-threatening or result in death "
                           "or hospitalization, but may jeopardize the patient and may require "
                           "intervention to prevent one of the other outcomes. Examples: allergic "
                           "bronchospasm requiring intensive treatment in ER, blood dyscrasias, "
                           "convulsions, drug dependence, drug abuse.",
            "reporting_implication": "Expedited report required within 15 calendar days.",
        },
    ]

    return {
        "status": "ok",
        "source": "ICH E2A (Clinical Safety Data Management: Definitions and Standards "
                  "for Expedited Reporting, 1994) — semi-live hardcoded reference",
        "guideline": "ICH E2A",
        "criteria_count": len(criteria),
        "criteria": criteria,
        "note": "An event is classified as 'serious' if it meets ANY ONE of these criteria. "
                "A single event can meet multiple criteria simultaneously.",
    }


def get_causality_categories(args: dict) -> dict:
    """
    Tool: get-causality-categories

    Returns the WHO-UMC causality assessment categories used internationally
    to evaluate the likelihood that a drug caused an adverse event.
    SEMI-LIVE: hardcoded from WHO-UMC system (current standard).
    """
    categories = [
        {
            "category": "Certain",
            "criteria": [
                "Event or laboratory test abnormality with plausible time relationship to drug intake",
                "Cannot be explained by disease or other drugs",
                "Response to withdrawal plausible (pharmacologically, pathologically)",
                "Event definitive pharmacologically or phenomenologically (i.e., an objective and "
                "specific medical disorder or a recognized pharmacological phenomenon)",
                "Rechallenge satisfactory, if necessary",
            ],
        },
        {
            "category": "Probable/Likely",
            "criteria": [
                "Event or laboratory test abnormality with reasonable time relationship to drug intake",
                "Unlikely to be attributed to disease or other drugs",
                "Response to withdrawal clinically reasonable",
                "Rechallenge not required",
            ],
        },
        {
            "category": "Possible",
            "criteria": [
                "Event or laboratory test abnormality with reasonable time relationship to drug intake",
                "Could also be explained by disease or other drugs",
                "Information on drug withdrawal may be lacking or unclear",
            ],
        },
        {
            "category": "Unlikely",
            "criteria": [
                "Event or laboratory test abnormality with a time to drug intake that makes a "
                "relationship improbable (but not impossible)",
                "Disease or other drugs provide plausible explanations",
            ],
        },
        {
            "category": "Conditional/Unclassified",
            "criteria": [
                "Event or laboratory test abnormality",
                "More data for proper assessment needed",
                "OR additional data under examination",
            ],
        },
        {
            "category": "Unassessable/Unclassifiable",
            "criteria": [
                "Report suggesting an adverse reaction",
                "Cannot be judged because information is insufficient or contradictory",
                "Data cannot be supplemented or verified",
            ],
        },
    ]

    return {
        "status": "ok",
        "source": "WHO-UMC causality assessment system — semi-live hardcoded reference",
        "system": "WHO-UMC",
        "category_count": len(categories),
        "categories": categories,
        "note": "The WHO-UMC system is one of the most widely used causality assessment "
                "methods globally. It is a clinical judgment-based approach, distinct from "
                "the Naranjo algorithm (which uses a scored questionnaire).",
    }


def get_reporting_timelines(args: dict) -> dict:
    """
    Tool: get-reporting-timelines

    Returns expedited and periodic safety reporting timelines by region
    (US FDA, EU EMA, Japan PMDA, ICH harmonized). Covers ICSRs, PSURs/PBRERs,
    and DSURs.
    SEMI-LIVE: hardcoded from ICH E2A/E2B/E2C/E2D/E2F and regional regulations.
    """
    timelines = {
        "expedited_reports": {
            "description": "Individual Case Safety Reports (ICSRs) requiring expedited submission",
            "by_region": {
                "ICH_harmonized": {
                    "fatal_or_life_threatening_unexpected": "7 calendar days (initial), 15 days (follow-up)",
                    "serious_unexpected": "15 calendar days",
                    "source": "ICH E2A",
                },
                "US_FDA": {
                    "fatal_or_life_threatening_unexpected": "7 calendar days (IND safety report), "
                                                            "15 calendar days (MedWatch 3500A)",
                    "serious_unexpected": "15 calendar days",
                    "field_alert_report": "3 working days (product quality defect posing safety risk)",
                    "source": "21 CFR 312.32 (IND), 21 CFR 314.80 (NDA), FDA Safety Reporting Portal",
                },
                "EU_EMA": {
                    "fatal_or_life_threatening_unexpected": "7 calendar days (initial), "
                                                            "8 additional days (follow-up = 15 total)",
                    "serious_unexpected": "15 calendar days",
                    "submission_system": "EudraVigilance (electronic only since 2017)",
                    "source": "Regulation (EU) No 726/2004, Directive 2001/83/EC",
                },
                "Japan_PMDA": {
                    "fatal_or_life_threatening_known": "15 days",
                    "fatal_or_life_threatening_unknown": "7 days (initial), 15 days (follow-up)",
                    "serious_unknown": "15 days",
                    "source": "PMDA Pharmaceutical Affairs Law, Article 77-4-2",
                },
            },
        },
        "periodic_reports": {
            "PSUR_PBRER": {
                "full_name": "Periodic Safety Update Report / Periodic Benefit-Risk Evaluation Report",
                "frequency": "Every 6 months (first 2 years post-approval), annually (next 2 years), "
                             "then every 3 years (or per EURD list in EU)",
                "guideline": "ICH E2C(R2)",
                "scope": "Cumulative review of global safety data with benefit-risk evaluation",
            },
            "DSUR": {
                "full_name": "Development Safety Update Report",
                "frequency": "Annually during clinical development (within 60 days of DIBD anniversary)",
                "guideline": "ICH E2F",
                "scope": "Review of safety information collected during reporting period for "
                         "investigational drugs",
            },
        },
    }

    return {
        "status": "ok",
        "source": "ICH E2A/E2B/E2C(R2)/E2D/E2F and regional regulations — "
                  "semi-live hardcoded reference",
        "timelines": timelines,
    }


def get_cioms_form_ii(args: dict) -> dict:
    """
    Tool: get-cioms-form-ii

    Returns the CIOMS II form structure — the standardized format for
    line listings used in Periodic Safety Update Reports (PSURs). CIOMS II
    defines the minimum data elements for tabulating individual cases.
    SEMI-LIVE: hardcoded schema based on CIOMS II Working Group recommendations.
    """
    form_structure = {
        "form_name": "CIOMS II Line Listing",
        "full_title": "CIOMS Working Group II — International Reporting of Periodic "
                      "Drug-Safety Update Summaries (Line Listing Format)",
        "purpose": "Standardized tabular format for presenting individual case "
                   "summaries in Periodic Safety Update Reports (PSURs). Enables "
                   "regulators to review individual cases within the context of "
                   "cumulative safety data.",
        "columns": [
            {"column": 1, "field": "case_number", "description": "Company case reference number"},
            {"column": 2, "field": "country", "description": "Country where the event was reported"},
            {"column": 3, "field": "source", "description": "Source type: spontaneous, clinical trial, literature, regulatory authority"},
            {"column": 4, "field": "age_sex", "description": "Patient age and sex"},
            {"column": 5, "field": "daily_dose_route", "description": "Daily dose and route of administration"},
            {"column": 6, "field": "date_of_onset", "description": "Date of onset of the reaction"},
            {"column": 7, "field": "reaction_terms", "description": "Adverse reaction terms (preferably coded to MedDRA Preferred Terms)"},
            {"column": 8, "field": "outcome", "description": "Outcome: recovered, not recovered, fatal, unknown"},
            {"column": 9, "field": "comments", "description": "Brief comments on causality assessment, concomitant drugs, relevant history"},
        ],
        "usage_context": {
            "psur_section": "Line listings appear in PSUR/PBRER Section 7 (Patient Listings)",
            "grouping": "Cases are typically grouped by SOC or by seriousness",
            "reference_period": "Covers the reporting interval of the PSUR",
        },
    }

    return {
        "status": "ok",
        "source": "CIOMS II Working Group — International Reporting of Periodic "
                  "Drug-Safety Update Summaries (1992) — semi-live hardcoded reference schema",
        "form": form_structure,
    }


TOOL_DISPATCH = {
    "get-working-groups": get_working_groups,
    "get-cioms-form": get_cioms_form,
    "search-publications": search_publications,
    "get-seriousness-criteria": get_seriousness_criteria,
    "get-causality-categories": get_causality_categories,
    "get-reporting-timelines": get_reporting_timelines,
    "get-cioms-form-ii": get_cioms_form_ii,
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
