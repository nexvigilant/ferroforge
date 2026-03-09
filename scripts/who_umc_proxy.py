#!/usr/bin/env python3
"""
WHO-UMC Proxy — routes MoltBrowser hub tool calls for WHO-UMC domain tools.

Usage:
    echo '{"tool": "get-causality-assessment", "args": {}}' | python3 who_umc_proxy.py

WHO-UMC (Uppsala Monitoring Centre) maintains VigiBase, the global ICSR
database. Access requires credentials. Signal detection and causality
assessment methodologies are published openly.

SEMI-LIVE tools return hardcoded reference data from official WHO-UMC
publications. Stub tools require VigiBase credentials for live data.

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.
"""

import json
import sys


def get_signal_methodology(args: dict) -> dict:
    """
    Tool: get-signal-methodology

    Returns a description of WHO-UMC's signal detection methodologies:
    vigiRank, BCPNN, and IC (Information Component).
    SEMI-LIVE: hardcoded from published WHO-UMC methodology documents.
    """
    methodologies = [
        {
            "name": "vigiRank",
            "type": "composite_signal_detection",
            "description": "A predictive model that combines multiple features to rank "
                           "drug-ADR pairs by their likelihood of being true safety signals. "
                           "vigiRank uses a machine-learning approach trained on historical "
                           "signal assessments to integrate statistical, clinical, and "
                           "reporting pattern features into a single score.",
            "key_features": [
                "Disproportionality (IC-based)",
                "Reporting pattern over time",
                "Number of reports",
                "Country distribution",
                "Reporting region pattern",
            ],
            "output": "Ranked list of drug-ADR pairs ordered by predicted signal value",
            "reference": "Caster O, et al. vigiRank for statistical signal detection in "
                         "pharmacovigilance. Drug Safety, 2017.",
        },
        {
            "name": "BCPNN (Bayesian Confidence Propagation Neural Network)",
            "type": "disproportionality_analysis",
            "description": "A Bayesian statistical method used to detect disproportional "
                           "reporting of drug-adverse event combinations in spontaneous "
                           "reporting databases. BCPNN computes the Information Component (IC) "
                           "as its measure of disproportionality, using a Bayesian framework "
                           "that naturally handles sparse data through prior distributions.",
            "mathematical_basis": "Bayesian neural network computing posterior probability of "
                                  "drug-ADR association given observed and expected co-occurrence",
            "advantages": [
                "Robust with sparse data due to Bayesian shrinkage",
                "Handles multiple comparisons naturally",
                "Provides credibility intervals (IC025 lower bound)",
                "Applicable to large-scale screening of entire databases",
            ],
            "reference": "Bate A, et al. A Bayesian neural network method for adverse drug "
                         "reaction signal generation. Eur J Clin Pharmacol, 1998.",
        },
        {
            "name": "IC (Information Component)",
            "type": "disproportionality_measure",
            "description": "The logarithmic measure of disproportionality computed by BCPNN. "
                           "IC quantifies how much more (or less) a particular drug-ADR "
                           "combination is reported compared to what would be expected if "
                           "drug and ADR were independent. A positive IC indicates the "
                           "combination is reported more often than expected.",
            "formula": "IC = log2(P_observed(drug, ADR) / P_expected(drug, ADR))",
            "interpretation": {
                "IC_positive": "Drug-ADR combination reported more than expected",
                "IC_zero": "Drug-ADR combination reported at the expected rate",
                "IC_negative": "Drug-ADR combination reported less than expected",
            },
            "signal_threshold": "IC025 > 0 (lower end of 95% credibility interval exceeds zero)",
            "related_measures": {
                "IC025": "Lower end of the 95% two-sided credibility interval for IC. "
                         "Primary signal detection criterion — when IC025 > 0, the "
                         "association is statistically robust.",
                "IC975": "Upper end of the 95% credibility interval",
            },
            "reference": "Norén GN, et al. A statistical methodology for drug-drug interaction "
                         "surveillance. Stat Med, 2008.",
        },
    ]

    return {
        "status": "ok",
        "source": "WHO-UMC (who-umc.org) — semi-live hardcoded methodology reference",
        "count": len(methodologies),
        "results": methodologies,
    }


def get_causality_assessment(args: dict) -> dict:
    """
    Tool: get-causality-assessment

    Returns the WHO-UMC causality assessment categories with criteria for
    each level. The WHO-UMC system is the standard global framework for
    assessing causality between a drug and an adverse event.
    SEMI-LIVE: hardcoded from official WHO-UMC causality assessment guidelines.
    """
    categories = [
        {
            "category": "Certain",
            "criteria": [
                "Event or laboratory test abnormality with plausible time relationship to drug intake",
                "Cannot be explained by disease or other drugs",
                "Response to withdrawal clinically plausible (pharmacologically, pathologically)",
                "Event definitive pharmacologically or phenomenologically, using a satisfactory "
                "rechallenge procedure if necessary",
            ],
            "requirements": "All criteria must be met. Rechallenge is often required.",
            "naranjo_equivalent": "Definite (score >= 9)",
        },
        {
            "category": "Probable/Likely",
            "criteria": [
                "Event or laboratory test abnormality with reasonable time relationship to drug intake",
                "Unlikely to be attributed to disease or other drugs",
                "Response to withdrawal clinically reasonable",
                "Rechallenge not required",
            ],
            "requirements": "All criteria must be met.",
            "naranjo_equivalent": "Probable (score 5-8)",
        },
        {
            "category": "Possible",
            "criteria": [
                "Event or laboratory test abnormality with reasonable time relationship to drug intake",
                "Could also be explained by disease or other drugs",
                "Information on drug withdrawal may be lacking or unclear",
            ],
            "requirements": "Time relationship is necessary; alternative explanations are acknowledged.",
            "naranjo_equivalent": "Possible (score 1-4)",
        },
        {
            "category": "Unlikely",
            "criteria": [
                "Event or laboratory test abnormality with improbable time relationship to drug intake "
                "(but not impossible)",
                "Disease or other drugs provide plausible explanations",
            ],
            "requirements": "A temporal association exists but is implausible; "
                            "other causes are more likely.",
            "naranjo_equivalent": "Doubtful (score <= 0)",
        },
        {
            "category": "Conditional/Unclassified",
            "criteria": [
                "Event or laboratory test abnormality reported as an adverse reaction",
                "More data needed for proper assessment",
                "Additional data are being examined or requested",
            ],
            "requirements": "Used when a report suggests a causal relationship but "
                            "is incomplete and requires supplementary information.",
            "naranjo_equivalent": "N/A — assessment pending",
        },
        {
            "category": "Unassessable/Unclassifiable",
            "criteria": [
                "Report suggesting an adverse reaction",
                "Cannot be judged because information is insufficient or contradictory",
                "Data cannot be supplemented or verified",
            ],
            "requirements": "Used when the report cannot be assessed due to missing "
                            "or contradictory information that cannot be obtained.",
            "naranjo_equivalent": "N/A — not assessable",
        },
    ]

    return {
        "status": "ok",
        "source": "WHO-UMC causality assessment system — semi-live hardcoded reference",
        "system_name": "WHO-UMC System for Standardised Case Causality Assessment",
        "reference": "The use of the WHO-UMC system for standardised case causality assessment. "
                     "Uppsala Monitoring Centre. Available at: https://who-umc.org/",
        "note": "The WHO-UMC system is designed for clinical assessment of individual case "
                "reports. It is distinct from algorithmic methods (e.g., Naranjo) but "
                "approximate equivalences are provided for reference.",
        "count": len(categories),
        "results": categories,
    }


def search_vigibase(args: dict) -> dict:
    """
    Tool: search-vigibase

    Searches WHO VigiBase, the global ICSR database. STUB — requires
    VigiBase access credentials from WHO-UMC.
    """
    drug = (args.get("drug") or args.get("drug_name") or args.get("name")
            or args.get("substance") or args.get("query") or "").strip()
    reaction = args.get("reaction", "").strip()

    return {
        "status": "stub",
        "message": "search-vigibase is not yet implemented. "
                   "VigiBase access requires credentials from WHO-UMC "
                   "(Uppsala Monitoring Centre). Apply at https://who-umc.org/ "
                   "for VigiBase access.",
        "query": {
            "drug": drug or None,
            "reaction": reaction or None,
        },
        "count": 0,
        "results": [],
    }


def get_country_programs(args: dict) -> dict:
    """
    Tool: get-country-programs

    Returns information about WHO Programme for International Drug Monitoring
    member countries. STUB — requires WHO-UMC data access.
    """
    country = args.get("country", "").strip()

    return {
        "status": "stub",
        "message": "get-country-programs is not yet implemented. "
                   "WHO Programme member country data requires WHO-UMC access. "
                   "The programme has over 170 member countries. "
                   "Visit https://who-umc.org/global-pharmacovigilance/who-programme/ "
                   "for the current member list.",
        "query": {
            "country": country or None,
        },
        "count": 0,
        "results": [],
    }


def get_naranjo_algorithm(args: dict) -> dict:
    """
    Tool: get-naranjo-algorithm

    Returns the Naranjo Adverse Drug Reaction Probability Scale — a structured
    questionnaire for causality assessment. SEMI-LIVE: hardcoded from the original
    1981 Naranjo et al. publication.
    """
    questions = [
        {
            "number": 1,
            "question": "Are there previous conclusive reports on this reaction?",
            "scores": {"yes": 1, "no": 0, "unknown": 0},
        },
        {
            "number": 2,
            "question": "Did the adverse event appear after the suspected drug was administered?",
            "scores": {"yes": 2, "no": -1, "unknown": 0},
        },
        {
            "number": 3,
            "question": "Did the adverse reaction improve when the drug was discontinued or a specific antagonist was administered?",
            "scores": {"yes": 1, "no": 0, "unknown": 0},
        },
        {
            "number": 4,
            "question": "Did the adverse reaction reappear when the drug was readministered?",
            "scores": {"yes": 2, "no": -1, "unknown": 0},
        },
        {
            "number": 5,
            "question": "Are there alternative causes (other than the drug) that could have on their own caused the reaction?",
            "scores": {"yes": -1, "no": 2, "unknown": 0},
        },
        {
            "number": 6,
            "question": "Did the reaction reappear when a placebo was given?",
            "scores": {"yes": -1, "no": 1, "unknown": 0},
        },
        {
            "number": 7,
            "question": "Was the drug detected in the blood (or other fluids) in concentrations known to be toxic?",
            "scores": {"yes": 1, "no": 0, "unknown": 0},
        },
        {
            "number": 8,
            "question": "Was the reaction more severe when the dose was increased, or less severe when the dose was decreased?",
            "scores": {"yes": 1, "no": 0, "unknown": 0},
        },
        {
            "number": 9,
            "question": "Did the patient have a similar reaction to the same or similar drugs in any previous exposure?",
            "scores": {"yes": 1, "no": 0, "unknown": 0},
        },
        {
            "number": 10,
            "question": "Was the adverse event confirmed by any objective evidence?",
            "scores": {"yes": 1, "no": 0, "unknown": 0},
        },
    ]

    interpretation = {
        "definite": {"range": "9+", "description": "Definite adverse drug reaction"},
        "probable": {"range": "5-8", "description": "Probable adverse drug reaction"},
        "possible": {"range": "1-4", "description": "Possible adverse drug reaction"},
        "doubtful": {"range": "0 or less", "description": "Doubtful adverse drug reaction"},
    }

    return {
        "status": "ok",
        "source": "Naranjo CA, et al. A method for estimating the probability of adverse drug "
                  "reactions. Clin Pharmacol Ther. 1981;30(2):239-45.",
        "algorithm_name": "Naranjo Adverse Drug Reaction Probability Scale",
        "score_range": {"min": -4, "max": 13},
        "questions": questions,
        "interpretation": interpretation,
        "note": "The Naranjo scale is the most widely used causality assessment tool globally. "
                "It complements the WHO-UMC system — Naranjo is algorithmic/scored while WHO-UMC "
                "is expert-judgment/categorical.",
    }


def get_ic_computation(args: dict) -> dict:
    """
    Tool: get-ic-computation

    Returns the Information Component (IC) computation methodology with
    a worked example. SEMI-LIVE: reference from WHO-UMC published methodology.
    """
    return {
        "status": "ok",
        "source": "WHO-UMC — Bayesian Confidence Propagation Neural Network methodology",
        "measure_name": "Information Component (IC)",
        "formula": {
            "ic": "IC = log2(observed / expected)",
            "observed": "P(drug AND event) = n_drug_event / N_total",
            "expected": "P(drug) × P(event) = (n_drug / N_total) × (n_event / N_total)",
            "simplified": "IC = log2((n_drug_event × N_total) / (n_drug × n_event))",
        },
        "credibility_interval": {
            "ic025": "Lower bound of 95% credibility interval — primary signal criterion",
            "ic975": "Upper bound of 95% credibility interval",
            "signal_threshold": "IC025 > 0 indicates a statistically robust signal",
        },
        "worked_example": {
            "description": "Drug X with Event Y in a database of 1,000,000 reports",
            "inputs": {
                "n_drug_event": 50,
                "n_drug": 5000,
                "n_event": 10000,
                "N_total": 1000000,
            },
            "computation": {
                "observed": "50 / 1,000,000 = 0.00005",
                "expected": "(5,000 / 1,000,000) × (10,000 / 1,000,000) = 0.00005 × 0.00001 = 0.00000005",
                "but_simplified": "(50 × 1,000,000) / (5,000 × 10,000) = 50,000,000 / 50,000,000 = 1.0",
                "ic_value": "IC = log2(1.0) = 0.0",
            },
            "interpretation": "IC = 0.0 means the drug-event combination is reported exactly at the "
                              "expected rate. No signal. If n_drug_event were 100, IC = log2(2.0) = 1.0, "
                              "indicating twice the expected reporting rate.",
        },
        "comparison_with_other_measures": {
            "PRR": "Proportional Reporting Ratio — frequentist, no shrinkage",
            "ROR": "Reporting Odds Ratio — frequentist, odds-based",
            "EBGM": "Empirical Bayes Geometric Mean — Bayesian with Gamma-Poisson, used by FDA",
            "IC": "Information Component — Bayesian with BCPNN, used by WHO-UMC",
        },
    }


def get_adverse_reaction_terminology(args: dict) -> dict:
    """
    Tool: get-adverse-reaction-terminology

    Returns WHO-ART (Adverse Reaction Terminology) hierarchy description.
    SEMI-LIVE: reference from WHO-UMC published documentation.
    """
    return {
        "status": "ok",
        "source": "WHO-UMC — WHO Adverse Reaction Terminology (WHO-ART)",
        "terminology_name": "WHO-ART (WHO Adverse Reaction Terminology)",
        "current_status": "Legacy — largely superseded by MedDRA for regulatory reporting, "
                          "but still used in VigiBase historical data and some national PV centres.",
        "hierarchy": {
            "levels": [
                {
                    "level": 1,
                    "name": "System Organ Class (SOC)",
                    "description": "Highest level — body system affected",
                    "example": "Gastrointestinal disorders",
                    "count": "32 SOCs",
                },
                {
                    "level": 2,
                    "name": "High Level Term (HLT)",
                    "description": "Grouped related preferred terms",
                    "example": "Nausea and vomiting symptoms",
                },
                {
                    "level": 3,
                    "name": "Preferred Term (PT)",
                    "description": "Standard term for individual ADR",
                    "example": "Nausea",
                    "count": "~2,000 PTs",
                },
                {
                    "level": 4,
                    "name": "Included Term (IT)",
                    "description": "Synonyms and verbatim terms mapped to PT",
                    "example": "Feeling sick, queasy",
                },
            ],
        },
        "meddra_comparison": {
            "who_art_levels": 4,
            "meddra_levels": 5,
            "key_difference": "MedDRA adds High Level Group Term (HLGT) between HLT and SOC, "
                              "and has ~80,000+ terms vs WHO-ART's ~2,000 PTs",
            "migration_note": "ICH E2B(R3) mandates MedDRA for regulatory reporting. "
                              "WHO-ART remains in historical VigiBase data.",
        },
    }


TOOL_DISPATCH = {
    "get-signal-methodology": get_signal_methodology,
    "get-causality-assessment": get_causality_assessment,
    "search-vigibase": search_vigibase,
    "get-country-programs": get_country_programs,
    "get-naranjo-algorithm": get_naranjo_algorithm,
    "get-ic-computation": get_ic_computation,
    "get-adverse-reaction-terminology": get_adverse_reaction_terminology,
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
