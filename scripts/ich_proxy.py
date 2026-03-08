#!/usr/bin/env python3
"""
ICH Proxy — routes MoltBrowser hub tool calls for ich.org.

Usage:
    echo '{"tool": "get-pv-guidelines", "args": {}}' | python3 ich_proxy.py

ICH guidelines are publicly available at https://ich.org/page/quality-guidelines.
search-guidelines and get-pv-guidelines are semi-live (hardcoded index of key
ICH pharmacovigilance guidelines). get-guideline and get-meddra-guidelines are
stubs. Reads a single JSON object from stdin, dispatches to the appropriate
handler, writes a structured JSON response to stdout.
No external dependencies — stdlib only.
"""

import json
import sys

# Hardcoded index of ICH PV guidelines (source: https://ich.org/page/efficacy-guidelines)
# URLs verified against ich.org guideline registry.
ICH_PV_GUIDELINES = [
    {
        "code": "E2A",
        "title": "Clinical Safety Data Management: Definitions and Standards for Expedited Reporting",
        "url": "https://database.ich.org/sites/default/files/E2A_Guideline.pdf",
        "description": (
            "Defines what constitutes an adverse event, adverse drug reaction, "
            "and unexpected ADR. Establishes criteria for expedited reporting "
            "of serious and unexpected ADRs during clinical development."
        ),
        "status": "Step 5",
    },
    {
        "code": "E2B",
        "title": "Clinical Safety Data Management: Data Elements for Transmission of Individual Case Safety Reports",
        "url": "https://database.ich.org/sites/default/files/E2B_R3__Guideline2.pdf",
        "description": (
            "Specifies the data elements and message format (ICSR) for "
            "electronic transmission of individual case safety reports "
            "between regulatory authorities and industry. Current version: E2B(R3)."
        ),
        "status": "Step 5 (R3)",
    },
    {
        "code": "E2C",
        "title": "Periodic Benefit-Risk Evaluation Report (PBRER)",
        "url": "https://database.ich.org/sites/default/files/E2C_R2_Guideline.pdf",
        "description": (
            "Defines the format and content of Periodic Benefit-Risk Evaluation "
            "Reports (PBRERs), replacing the older PSUR format. Covers cumulative "
            "safety data review and benefit-risk analysis. Current version: E2C(R2)."
        ),
        "status": "Step 5 (R2)",
    },
    {
        "code": "E2D",
        "title": "Post-Approval Safety Data Management: Definitions and Standards for Expedited Reporting",
        "url": "https://database.ich.org/sites/default/files/E2D_Guideline.pdf",
        "description": (
            "Extends E2A definitions to the post-approval setting. Covers "
            "expedited reporting obligations for marketed products, including "
            "spontaneous reports, literature cases, and solicited reports."
        ),
        "status": "Step 5",
    },
    {
        "code": "E2E",
        "title": "Pharmacovigilance Planning",
        "url": "https://database.ich.org/sites/default/files/E2E_Guideline.pdf",
        "description": (
            "Provides guidance on pharmacovigilance planning, including the "
            "Safety Specification and Pharmacovigilance Plan. Describes how to "
            "identify safety concerns and plan activities to characterize risks."
        ),
        "status": "Step 5",
    },
    {
        "code": "E2F",
        "title": "Development Safety Update Report (DSUR)",
        "url": "https://database.ich.org/sites/default/files/E2F_Guideline.pdf",
        "description": (
            "Defines the format and content of the Development Safety Update "
            "Report, a periodic report submitted during clinical development "
            "to regulatory authorities. Covers cumulative safety evaluation "
            "of an investigational drug."
        ),
        "status": "Step 5",
    },
    {
        "code": "M1",
        "title": "MedDRA — Medical Dictionary for Regulatory Activities",
        "url": "https://database.ich.org/sites/default/files/M1_EWG_Concept_Paper.pdf",
        "description": (
            "ICH-maintained medical terminology dictionary used for coding "
            "adverse events, indications, and medical history in regulatory "
            "submissions. Managed by the MedDRA MSSO."
        ),
        "status": "Maintained by MedDRA MSSO",
    },
]

# Full ICH guideline index for search — includes PV plus related guidelines
# (source: https://ich.org/page/efficacy-guidelines, https://ich.org/page/multidisciplinary-guidelines)
ICH_ALL_GUIDELINES = ICH_PV_GUIDELINES + [
    {
        "code": "E6",
        "title": "Good Clinical Practice (GCP)",
        "url": "https://database.ich.org/sites/default/files/ICH_E6-R3_GCP_Principles_2024_0519.pdf",
        "description": (
            "Unified standard for designing, conducting, recording and "
            "reporting clinical trials. Includes safety reporting requirements "
            "for investigators and sponsors. Current version: E6(R3)."
        ),
        "status": "Step 5 (R3)",
    },
    {
        "code": "E8",
        "title": "General Considerations for Clinical Studies",
        "url": "https://database.ich.org/sites/default/files/E8_R1_Guideline.pdf",
        "description": (
            "Framework for clinical study design including safety "
            "considerations. Current version: E8(R1)."
        ),
        "status": "Step 5 (R1)",
    },
    {
        "code": "E9",
        "title": "Statistical Principles for Clinical Trials",
        "url": "https://database.ich.org/sites/default/files/E9-R1_Step4_Guideline_2019_1203.pdf",
        "description": (
            "Statistical methodology for clinical trials, including "
            "estimands framework for safety endpoints. Current version: E9(R1)."
        ),
        "status": "Step 5 (R1)",
    },
    {
        "code": "E19",
        "title": "Optimisation of Safety Data Collection",
        "url": "https://database.ich.org/sites/default/files/E19_Step4_Guideline_2022_1117.pdf",
        "description": (
            "Guidance on selective collection of safety data in late-stage "
            "clinical trials to reduce burden while maintaining patient safety."
        ),
        "status": "Step 5",
    },
]


def search_guidelines(args: dict) -> dict:
    """
    Tool: search-guidelines

    Semi-live — searches hardcoded index of ICH guidelines by keyword.
    Returns matching guidelines from the ICH efficacy and multidisciplinary
    guideline families.
    """
    query = args.get("query", "").strip().lower()
    if not query:
        return {"status": "error", "message": "query is required"}

    matches = []
    for gl in ICH_ALL_GUIDELINES:
        searchable = (
            gl["code"].lower() + " "
            + gl["title"].lower() + " "
            + gl["description"].lower()
        )
        if query in searchable:
            matches.append(gl)

    return {
        "status": "ok",
        "tool": "search-guidelines",
        "query": query,
        "count": len(matches),
        "guidelines": matches,
        "data_source": "ich.org (hardcoded index, source: https://ich.org/page/efficacy-guidelines)",
    }


def get_guideline(args: dict) -> dict:
    """
    Tool: get-guideline

    Stub for full guideline retrieval. The hardcoded index can resolve
    known codes to URLs; full-text extraction would require PDF parsing.
    """
    code = args.get("code", "").strip().upper()
    if not code:
        return {"status": "error", "message": "code is required (e.g. 'E2A', 'E2B', 'E6')"}

    # Try to resolve from the hardcoded index first
    for gl in ICH_ALL_GUIDELINES:
        if gl["code"].upper() == code:
            return {
                "status": "stub",
                "tool": "get-guideline",
                "description": (
                    "Full guideline text retrieval is not yet implemented. "
                    "The guideline metadata and PDF URL are available from "
                    "the hardcoded index below."
                ),
                "parameters_received": {"code": code},
                "resolved": gl,
                "data_source": "ich.org (source: https://ich.org/page/efficacy-guidelines)",
                "implementation_notes": "Full-text extraction requires PDF parsing; PDF URL provided for direct access",
            }

    return {
        "status": "stub",
        "tool": "get-guideline",
        "description": (
            "Full guideline text retrieval is not yet implemented. "
            "The requested code was not found in the hardcoded PV/efficacy index."
        ),
        "parameters_received": {"code": code},
        "resolved": None,
        "data_source": "ich.org (source: https://ich.org/page/efficacy-guidelines)",
        "implementation_notes": (
            "Code not in hardcoded index. Browse https://ich.org/page/search "
            "for the full ICH guideline catalogue."
        ),
    }


def get_pv_guidelines(args: dict) -> dict:
    """
    Tool: get-pv-guidelines

    Semi-live — returns the complete index of ICH pharmacovigilance
    guidelines (E2A through E2F plus M1).
    """
    return {
        "status": "ok",
        "tool": "get-pv-guidelines",
        "count": len(ICH_PV_GUIDELINES),
        "guidelines": ICH_PV_GUIDELINES,
        "data_source": "ich.org (hardcoded index, source: https://ich.org/page/efficacy-guidelines)",
    }


def get_meddra_guidelines(args: dict) -> dict:
    """
    Tool: get-meddra-guidelines

    Stub for MedDRA-specific ICH guidelines. Returns the M1 entry from
    the hardcoded index plus pointers to MedDRA MSSO resources.
    """
    # M1 is in the PV guidelines list — extract it
    m1_entry = None
    for gl in ICH_PV_GUIDELINES:
        if gl["code"] == "M1":
            m1_entry = gl
            break

    return {
        "status": "stub",
        "tool": "get-meddra-guidelines",
        "description": (
            "Returns ICH guidelines related to MedDRA terminology usage. "
            "The M1 guideline entry is provided from the hardcoded index. "
            "Detailed MedDRA usage guides are maintained by the MedDRA MSSO."
        ),
        "parameters_received": args,
        "m1_guideline": m1_entry,
        "data_source": "ich.org (source: https://ich.org/page/multidisciplinary-guidelines)",
        "implementation_notes": (
            "Detailed MedDRA documentation requires MSSO subscription "
            "(source: https://www.meddra.org/how-to-use/support-documentation/english)"
        ),
    }


def get_safety_guidelines(args: dict) -> dict:
    """
    Tool: get-safety-guidelines

    Semi-live — returns ICH Safety (S-series) guidelines relevant to
    nonclinical and clinical safety evaluation.
    """
    safety_guidelines = [
        {
            "code": "S7A",
            "title": "Safety Pharmacology Studies for Human Pharmaceuticals",
            "url": "https://database.ich.org/sites/default/files/S7A_Guideline.pdf",
            "description": (
                "Core battery of safety pharmacology studies assessing effects "
                "on cardiovascular, respiratory, and central nervous systems."
            ),
            "status": "Step 5",
        },
        {
            "code": "S7B",
            "title": "Nonclinical Evaluation of the Potential for Delayed Ventricular Repolarization (QT Interval Prolongation)",
            "url": "https://database.ich.org/sites/default/files/S7B_Guideline.pdf",
            "description": (
                "Nonclinical strategy for assessing QT/QTc interval prolongation "
                "risk — hERG channel assay and in vivo QT studies."
            ),
            "status": "Step 5",
        },
        {
            "code": "S1",
            "title": "Carcinogenicity Studies",
            "url": "https://database.ich.org/sites/default/files/S1_Guideline.pdf",
            "description": (
                "Guidance on when carcinogenicity studies are needed, study design, "
                "dose selection, and evaluation of results."
            ),
            "status": "Step 5",
        },
        {
            "code": "S2",
            "title": "Genotoxicity Testing and Data Interpretation",
            "url": "https://database.ich.org/sites/default/files/S2-R1_Guideline.pdf",
            "description": (
                "Standard battery for genotoxicity testing: bacterial reverse "
                "mutation, in vitro cytogenetics, and in vivo micronucleus. "
                "Current version: S2(R1)."
            ),
            "status": "Step 5 (R1)",
        },
        {
            "code": "S5",
            "title": "Reproductive Toxicology",
            "url": "https://database.ich.org/sites/default/files/S5-R3_Step4_Guideline_2020_0218.pdf",
            "description": (
                "Detection of toxicity to reproduction including fertility, "
                "embryo-fetal development, and pre/postnatal development. "
                "Current version: S5(R3)."
            ),
            "status": "Step 5 (R3)",
        },
        {
            "code": "S6",
            "title": "Preclinical Safety Evaluation of Biotechnology-Derived Pharmaceuticals",
            "url": "https://database.ich.org/sites/default/files/S6_R1_Guideline.pdf",
            "description": (
                "Nonclinical safety evaluation specific to biologics — species "
                "selection, immunogenicity, tissue cross-reactivity. Current: S6(R1)."
            ),
            "status": "Step 5 (R1)",
        },
        {
            "code": "S9",
            "title": "Nonclinical Evaluation for Anticancer Pharmaceuticals",
            "url": "https://database.ich.org/sites/default/files/S9_Guideline.pdf",
            "description": (
                "Abbreviated nonclinical programs for anticancer drugs — reflects "
                "the serious nature of the target disease and urgency of treatment."
            ),
            "status": "Step 5",
        },
    ]
    return {
        "status": "ok",
        "tool": "get-safety-guidelines",
        "count": len(safety_guidelines),
        "guidelines": safety_guidelines,
        "data_source": "ich.org (hardcoded index, source: https://ich.org/page/safety-guidelines)",
    }


def get_quality_guidelines(args: dict) -> dict:
    """
    Tool: get-quality-guidelines

    Semi-live — returns ICH Quality (Q-series) guidelines for pharmaceutical
    quality, manufacturing, and analytical standards.
    """
    quality_guidelines = [
        {
            "code": "Q1A",
            "title": "Stability Testing of New Drug Substances and Products",
            "url": "https://database.ich.org/sites/default/files/Q1A%28R2%29%20Guideline.pdf",
            "description": "Stability study design, storage conditions, and testing frequency. Current: Q1A(R2).",
            "status": "Step 5 (R2)",
        },
        {
            "code": "Q2",
            "title": "Validation of Analytical Procedures",
            "url": "https://database.ich.org/sites/default/files/Q2(R2)_Guideline_2022_1129.pdf",
            "description": "Validation characteristics: accuracy, precision, specificity, detection/quantitation limits. Current: Q2(R2).",
            "status": "Step 5 (R2)",
        },
        {
            "code": "Q3A",
            "title": "Impurities in New Drug Substances",
            "url": "https://database.ich.org/sites/default/files/Q3A%28R2%29%20Guideline.pdf",
            "description": "Reporting, identification, and qualification thresholds for impurities. Current: Q3A(R2).",
            "status": "Step 5 (R2)",
        },
        {
            "code": "Q8",
            "title": "Pharmaceutical Development",
            "url": "https://database.ich.org/sites/default/files/Q8_R2_Guideline.pdf",
            "description": "Quality by Design (QbD) framework — design space, control strategy, PAT. Current: Q8(R2).",
            "status": "Step 5 (R2)",
        },
        {
            "code": "Q12",
            "title": "Technical and Regulatory Considerations for Pharmaceutical Product Lifecycle Management",
            "url": "https://database.ich.org/sites/default/files/Q12_Step4_Guideline_2019_1119.pdf",
            "description": "Post-approval change management including established conditions and PACMP.",
            "status": "Step 5",
        },
    ]
    return {
        "status": "ok",
        "tool": "get-quality-guidelines",
        "count": len(quality_guidelines),
        "guidelines": quality_guidelines,
        "data_source": "ich.org (hardcoded index, source: https://ich.org/page/quality-guidelines)",
    }


def get_e2b_data_elements(args: dict) -> dict:
    """
    Tool: get-e2b-data-elements

    Semi-live — returns the key E2B(R3) ICSR data element categories
    and their structure. Essential reference for ICSR electronic transmission.
    """
    return {
        "status": "ok",
        "tool": "get-e2b-data-elements",
        "source": "ICH E2B(R3) — Electronic Transmission of Individual Case Safety Reports",
        "url": "https://database.ich.org/sites/default/files/E2B_R3__Guideline2.pdf",
        "data_element_categories": [
            {
                "section": "A. Administrative Information",
                "elements": [
                    "A.1 Identification of the case safety report",
                    "A.2 Primary source(s) of information",
                    "A.3 Information on sender and receiver",
                ],
            },
            {
                "section": "B. Patient Information",
                "elements": [
                    "B.1 Patient characteristics (age, sex, weight, height)",
                    "B.2 Relevant medical history and concurrent conditions",
                    "B.3 Relevant past drug history",
                    "B.4 Drug(s) information",
                    "B.5 Reaction(s)/event(s)",
                ],
            },
            {
                "section": "B.4 Drug Information (per drug)",
                "elements": [
                    "B.4.k.1 Characterisation of drug role (suspect/concomitant/interacting)",
                    "B.4.k.2 Drug identification (active substance, product name, INN)",
                    "B.4.k.4 Dosage and route of administration",
                    "B.4.k.5 Dates of drug therapy start and end",
                    "B.4.k.7 Drug-reaction/event matrix (dechallenge, rechallenge)",
                    "B.4.k.8 Additional information on drug",
                ],
            },
            {
                "section": "B.5 Reaction/Event (per reaction)",
                "elements": [
                    "B.5.1 Reaction/event as reported by primary source",
                    "B.5.2 Reaction/event coded (MedDRA LLT and PT)",
                    "B.5.3 Date of onset and resolution",
                    "B.5.4 Duration of reaction/event",
                    "B.5.6 Outcome of reaction/event at time of last observation",
                ],
            },
            {
                "section": "C. Narrative and Further Information",
                "elements": [
                    "C.1 Case narrative including clinical course",
                    "C.2 Reporter's comments",
                    "C.3 Sender's diagnosis and comments",
                    "C.4 Literature references",
                ],
            },
        ],
        "key_concepts": {
            "seriousness_criteria": [
                "Results in death",
                "Is life-threatening",
                "Requires inpatient hospitalization or prolongation",
                "Results in persistent or significant disability/incapacity",
                "Is a congenital anomaly/birth defect",
                "Is a medically important condition",
            ],
            "reporter_qualification": [
                "1 = Physician",
                "2 = Pharmacist",
                "3 = Other health professional",
                "4 = Lawyer",
                "5 = Consumer or non-health professional",
            ],
            "drug_characterisation": [
                "1 = Suspect",
                "2 = Concomitant",
                "3 = Interacting",
            ],
        },
        "data_source": "ich.org (source: ICH E2B(R3) guideline)",
    }


TOOL_DISPATCH = {
    "search-guidelines": search_guidelines,
    "get-guideline": get_guideline,
    "get-pv-guidelines": get_pv_guidelines,
    "get-meddra-guidelines": get_meddra_guidelines,
    "get-safety-guidelines": get_safety_guidelines,
    "get-quality-guidelines": get_quality_guidelines,
    "get-e2b-data-elements": get_e2b_data_elements,
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
        result = {
            "status": "error",
            "message": f"Unknown tool '{tool_name}'. Known tools: {known}",
        }
        print(json.dumps(result))
        sys.exit(1)

    handler = TOOL_DISPATCH[tool_name]
    result = handler(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
