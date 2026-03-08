#!/usr/bin/env python3
"""
MedDRA Proxy — routes MoltBrowser hub tool calls for meddra.org.

Usage:
    echo '{"tool": "search-terms", "args": {"query": "headache"}}' | python3 meddra_proxy.py

MedDRA requires an MSSO subscription license (source: https://www.meddra.org/how-to-use/support-documentation/english).
All handlers return informative stubs describing what each tool would return
when connected to a live MedDRA dictionary. Reads a single JSON object from
stdin, dispatches to the appropriate handler, writes a structured JSON
response to stdout. No external dependencies — stdlib only.
"""

import json
import sys

# MedDRA hierarchy levels per MedDRA Introductory Guide
# (source: https://www.meddra.org/how-to-use/basics/hierarchy)
HIERARCHY_NOTE = (
    "MedDRA hierarchy: LLT -> PT -> HLT -> HLGT -> SOC "
    "(source: https://www.meddra.org/how-to-use/basics/hierarchy)"
)

# 27 SOCs per MedDRA structure
# (source: https://www.meddra.org/how-to-use/basics/hierarchy)
SOC_NOTE = (
    "27 SOCs organize all medical concepts by body system "
    "(source: https://www.meddra.org/how-to-use/basics/hierarchy)"
)

# SMQ documentation
# (source: https://www.meddra.org/how-to-use/tools/smqs)
SMQ_NOTE = (
    "SMQs are validated, pre-defined groupings of MedDRA terms for signal detection "
    "(source: https://www.meddra.org/how-to-use/tools/smqs)"
)


def search_terms(args: dict) -> dict:
    """
    Tool: search-terms

    Stub for MedDRA term search. When live, searches the MedDRA dictionary
    for PTs, LLTs, and HLTs matching the query.
    """
    query = args.get("query", "").strip()
    if not query:
        return {"status": "error", "message": "query is required"}

    return {
        "status": "stub",
        "tool": "search-terms",
        "description": (
            "Searches the MedDRA dictionary for Preferred Terms (PTs), "
            "Lowest Level Terms (LLTs), and High Level Terms (HLTs) matching "
            "the query. Returns coded terms with SOC hierarchy, MedDRA code, "
            "term level (LLT/PT/HLT/HLGT/SOC), and currency status. "
            + HIERARCHY_NOTE
        ),
        "parameters_received": {"query": query},
        "data_source": "meddra.org",
        "implementation_notes": "Requires MedDRA MSSO subscription license (source: https://www.meddra.org/how-to-use/support-documentation/english)",
    }


def get_term_hierarchy(args: dict) -> dict:
    """
    Tool: get-term-hierarchy

    Stub for MedDRA hierarchy lookup. When live, returns the full hierarchy
    for a given MedDRA term or code.
    """
    term = args.get("term", "").strip()
    code = args.get("code", "")
    if not term and not code:
        return {"status": "error", "message": "term or code is required"}

    return {
        "status": "stub",
        "tool": "get-term-hierarchy",
        "description": (
            "Returns the full MedDRA hierarchy for a given term or code. "
            + HIERARCHY_NOTE
            + ". Also returns the primary SOC flag "
            "and any multi-axiality (secondary SOC assignments)."
        ),
        "parameters_received": {
            "term": term or None,
            "code": code or None,
        },
        "data_source": "meddra.org",
        "implementation_notes": "Requires MedDRA MSSO subscription license (source: https://www.meddra.org/how-to-use/support-documentation/english)",
    }


def get_soc_terms(args: dict) -> dict:
    """
    Tool: get-soc-terms

    Stub for MedDRA SOC listing. When live, returns all Preferred Terms
    within a given System Organ Class.
    """
    soc = args.get("soc", "").strip()
    if not soc:
        return {"status": "error", "message": "soc is required"}

    return {
        "status": "stub",
        "tool": "get-soc-terms",
        "description": (
            "Returns all Preferred Terms (PTs) classified under the specified "
            "System Organ Class (SOC). " + SOC_NOTE
            + ". Results include PT code, term name, "
            "and primary/secondary SOC flag."
        ),
        "parameters_received": {"soc": soc},
        "data_source": "meddra.org",
        "implementation_notes": "Requires MedDRA MSSO subscription license (source: https://www.meddra.org/how-to-use/support-documentation/english)",
    }


def get_smq(args: dict) -> dict:
    """
    Tool: get-smq

    Stub for MedDRA Standardised MedDRA Query lookup. When live, returns
    the component terms of an SMQ.
    """
    smq_name = args.get("smq_name", "").strip()
    smq_code = args.get("smq_code", "")
    if not smq_name and not smq_code:
        return {"status": "error", "message": "smq_name or smq_code is required"}

    return {
        "status": "stub",
        "tool": "get-smq",
        "description": (
            "Returns the component Preferred Terms of a Standardised MedDRA "
            "Query (SMQ). " + SMQ_NOTE
            + ". Results include narrow/broad scope classification, term weight, "
            "and SMQ algorithm category."
        ),
        "parameters_received": {
            "smq_name": smq_name or None,
            "smq_code": smq_code or None,
        },
        "data_source": "meddra.org",
        "implementation_notes": "Requires MedDRA MSSO subscription license (source: https://www.meddra.org/how-to-use/support-documentation/english)",
    }


def get_hierarchy_overview(args: dict) -> dict:
    """
    Tool: get-hierarchy-overview

    Semi-live — returns the complete MedDRA hierarchy structure description
    with level counts and relationships. Essential reference for understanding
    MedDRA coding in pharmacovigilance.
    """
    return {
        "status": "ok",
        "tool": "get-hierarchy-overview",
        "hierarchy": {
            "levels": [
                {
                    "level": 1,
                    "name": "System Organ Class (SOC)",
                    "abbreviation": "SOC",
                    "count": 27,
                    "description": (
                        "Highest level — groupings by body system, aetiology, "
                        "or purpose (e.g., Cardiac disorders, Infections and "
                        "infestations, Surgical and medical procedures)."
                    ),
                },
                {
                    "level": 2,
                    "name": "High Level Group Term (HLGT)",
                    "abbreviation": "HLGT",
                    "count_approximate": 337,
                    "description": (
                        "Superordinate descriptor linking one or more HLTs. "
                        "Example: 'Coronary artery disorders' under Cardiac disorders SOC."
                    ),
                },
                {
                    "level": 3,
                    "name": "High Level Term (HLT)",
                    "abbreviation": "HLT",
                    "count_approximate": 1737,
                    "description": (
                        "Superordinate descriptor for a group of related PTs. "
                        "Example: 'Myocardial infarction' HLT groups several "
                        "MI-related PTs."
                    ),
                },
                {
                    "level": 4,
                    "name": "Preferred Term (PT)",
                    "abbreviation": "PT",
                    "count_approximate": 27000,
                    "description": (
                        "Standard term representing a single medical concept. "
                        "The primary coding level for adverse event reporting. "
                        "Example: 'Acute myocardial infarction'."
                    ),
                },
                {
                    "level": 5,
                    "name": "Lowest Level Term (LLT)",
                    "abbreviation": "LLT",
                    "count_approximate": 83000,
                    "description": (
                        "Most granular level — synonyms, spelling variations, "
                        "and sub-types linked to a parent PT. Each LLT maps "
                        "to exactly one PT. Example: 'Heart attack' -> PT 'Myocardial infarction'."
                    ),
                },
            ],
            "relationships": {
                "direction": "LLT -> PT -> HLT -> HLGT -> SOC (bottom to top)",
                "multi_axiality": (
                    "A PT may be linked to more than one SOC. One SOC is designated "
                    "'primary' for tabulation; others are 'secondary' for retrieval."
                ),
                "coding_convention": (
                    "Adverse events should be coded to the most specific LLT, which "
                    "auto-maps to the correct PT. Signal detection and regulatory "
                    "reporting primarily use the PT level."
                ),
            },
        },
        "data_source": "meddra.org (source: https://www.meddra.org/how-to-use/basics/hierarchy)",
    }


def get_version_info(args: dict) -> dict:
    """
    Tool: get-version-info

    Semi-live — returns MedDRA version information, update cycle, and
    maintenance organization details.
    """
    return {
        "status": "ok",
        "tool": "get-version-info",
        "current_version": {
            "version": "27.1",
            "release_date": "September 2024",
            "note": "Version numbers may have been updated since this reference was compiled.",
        },
        "update_cycle": {
            "frequency": "Biannual — two releases per year (March and September)",
            "versioning": "Major.Minor (e.g., 27.0 in March, 27.1 in September)",
            "process": (
                "Change requests submitted by member organizations, reviewed by "
                "MedDRA Maintenance and Support Services Organization (MSSO), "
                "approved by ICH MedDRA Management Committee."
            ),
        },
        "maintenance_organization": {
            "name": "MedDRA MSSO (Maintenance and Support Services Organization)",
            "operator": "Operated under contract to ICH",
            "url": "https://www.meddra.org",
            "services": [
                "Term distribution (annual subscription)",
                "Browser and search tools",
                "Change request processing",
                "Documentation and training",
                "SMQ development and maintenance",
            ],
        },
        "regulatory_requirement": (
            "MedDRA is the required terminology for ICSR coding in ICH regions "
            "(US FDA, EMA, PMDA) per E2B(R3) implementation guides."
        ),
        "data_source": "meddra.org (source: https://www.meddra.org/about-meddra/organisation)",
    }


def get_multiaxiality_guide(args: dict) -> dict:
    """
    Tool: get-multiaxiality-guide

    Semi-live — returns guidance on MedDRA multi-axiality, where a Preferred
    Term can be classified under more than one System Organ Class.
    """
    return {
        "status": "ok",
        "tool": "get-multiaxiality-guide",
        "concept": (
            "Multi-axiality means a single PT can be linked to multiple SOCs. "
            "One SOC is designated 'primary' for statistical tabulation; additional "
            "SOCs are 'secondary' to allow retrieval from multiple perspectives."
        ),
        "examples": [
            {
                "pt": "Pneumonia",
                "primary_soc": "Infections and infestations",
                "secondary_socs": ["Respiratory, thoracic and mediastinal disorders"],
                "rationale": (
                    "Pneumonia is primarily an infection but also manifests as a "
                    "respiratory disorder. Multi-axiality ensures retrieval under both."
                ),
            },
            {
                "pt": "Drug-induced liver injury",
                "primary_soc": "Hepatobiliary disorders",
                "secondary_socs": ["Injury, poisoning and procedural complications"],
                "rationale": (
                    "DILI is a hepatic condition but also classified as an injury "
                    "when drug-induced."
                ),
            },
            {
                "pt": "Suicidal ideation",
                "primary_soc": "Psychiatric disorders",
                "secondary_socs": ["Social circumstances"],
                "rationale": (
                    "Primarily psychiatric, but social context classification "
                    "enables broader retrieval in post-marketing surveillance."
                ),
            },
        ],
        "impact_on_signal_detection": {
            "primary_soc_rule": (
                "When computing disproportionality signals (PRR, ROR, IC), use "
                "the PRIMARY SOC assignment to avoid double-counting events."
            ),
            "retrieval_rule": (
                "When searching for all cases related to a body system, include "
                "BOTH primary and secondary SOC assignments for completeness."
            ),
            "regulatory_guidance": (
                "ICH E2B(R3) requires coding to the LLT level. The PT and SOC "
                "assignments are automatic via the MedDRA hierarchy. Primary SOC "
                "designation follows MedDRA's published primary SOC algorithm."
            ),
        },
        "data_source": "meddra.org (source: https://www.meddra.org/how-to-use/basics/hierarchy)",
    }


TOOL_DISPATCH = {
    "search-terms": search_terms,
    "get-term-hierarchy": get_term_hierarchy,
    "get-soc-terms": get_soc_terms,
    "get-smq": get_smq,
    "get-hierarchy-overview": get_hierarchy_overview,
    "get-version-info": get_version_info,
    "get-multiaxiality-guide": get_multiaxiality_guide,
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
