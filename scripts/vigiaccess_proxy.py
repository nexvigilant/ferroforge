#!/usr/bin/env python3
"""
VigiAccess (WHO) Proxy — routes MoltBrowser hub tool calls for vigiaccess.org.

Usage:
    echo '{"tool": "search-reports", "args": {"drug_name": "metformin"}}' | python3 vigiaccess_proxy.py

VigiAccess has no public API. All tools return intelligent stubs describing
what each tool will return when live (via web scraping or WHO-UMC API access).

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.
"""

import json
import sys


def _stub_response(tool_name: str, description: str, args: dict) -> dict:
    """Build a standardized stub response for a VigiAccess tool."""
    return {
        "status": "stub",
        "tool": tool_name,
        "description": description,
        "parameters_received": args,
        "data_source": "vigiaccess.org",
        "implementation_notes": "Requires VigiAccess web scraping or WHO-UMC API access",
    }


def search_reports(args: dict) -> dict:
    """
    Tool: search-reports

    Searches VigiAccess for individual case safety reports (ICSRs) matching
    the given drug name. Returns report counts and summary statistics from
    the WHO global pharmacovigilance database (VigiBase).
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    return _stub_response(
        "search-reports",
        (
            "Returns total ICSR count, year-over-year trend, and geographic "
            "summary for the specified drug from VigiBase via VigiAccess. "
            "Includes total reports, reports by year, and top reporting regions."
        ),
        args,
    )


def get_adverse_reactions(args: dict) -> dict:
    """
    Tool: get-adverse-reactions

    Retrieves adverse reaction profile for a drug from VigiAccess, grouped
    by MedDRA System Organ Class (SOC). Returns reaction counts by SOC
    with drill-down to Preferred Term level.
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    return _stub_response(
        "get-adverse-reactions",
        (
            "Returns adverse reactions grouped by MedDRA System Organ Class "
            "(SOC) with counts. Each SOC entry includes total reports and "
            "percentage of all reports. Drill-down to Preferred Term available."
        ),
        args,
    )


def get_reporter_distribution(args: dict) -> dict:
    """
    Tool: get-reporter-distribution

    Returns the distribution of reporter types (healthcare professional,
    consumer, pharmaceutical company, other) for a drug's VigiAccess reports.
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    return _stub_response(
        "get-reporter-distribution",
        (
            "Returns reporter type breakdown: healthcare professional, "
            "consumer/non-healthcare professional, pharmaceutical company, "
            "and other/not specified. Includes counts and percentages."
        ),
        args,
    )


def get_age_distribution(args: dict) -> dict:
    """
    Tool: get-age-distribution

    Returns the age group distribution of patients in a drug's VigiAccess
    reports. Age groups follow WHO standard bands (0-27 days, 28 days-23 months,
    2-11 years, 12-17 years, 18-44, 45-64, 65-74, 75+, unknown).
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    return _stub_response(
        "get-age-distribution",
        (
            "Returns patient age group distribution using WHO standard bands: "
            "neonates (0-27 days), infants (28 days-23 months), children (2-11), "
            "adolescents (12-17), adults (18-44, 45-64), elderly (65-74, 75+), "
            "and unknown. Includes counts and percentages per band."
        ),
        args,
    )


def get_region_distribution(args: dict) -> dict:
    """
    Tool: get-region-distribution

    Returns the geographic distribution of a drug's VigiAccess reports by
    WHO region (Africa, Americas, Eastern Mediterranean, Europe, South-East
    Asia, Western Pacific).
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    return _stub_response(
        "get-region-distribution",
        (
            "Returns geographic breakdown by WHO region: Africa, Americas, "
            "Eastern Mediterranean, Europe, South-East Asia, Western Pacific. "
            "Includes report counts and percentages per region."
        ),
        args,
    )


def get_sex_distribution(args: dict) -> dict:
    """
    Tool: get-sex-distribution

    Returns the distribution of reports by patient sex (male, female, unknown)
    for a drug's VigiAccess reports.
    """
    drug_name = args.get("drug_name", args.get("medicine", "")).strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name or medicine is required"}

    return _stub_response(
        "get-sex-distribution",
        (
            "Returns patient sex distribution: male, female, and unknown/not "
            "specified. Includes report counts and percentages per category. "
            "Useful for identifying sex-specific adverse reaction patterns."
        ),
        args,
    )


def get_year_distribution(args: dict) -> dict:
    """
    Tool: get-year-distribution

    Returns the distribution of reports by reporting year for a drug's
    VigiAccess entries. Useful for temporal trend analysis — identifying
    signal emergence, reporting rate changes, and post-marketing surveillance
    patterns.
    """
    drug_name = args.get("drug_name", args.get("medicine", "")).strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name or medicine is required"}

    return _stub_response(
        "get-year-distribution",
        (
            "Returns report counts by year from VigiBase. Enables temporal "
            "trend analysis: signal emergence detection, reporting rate changes "
            "after regulatory actions, and post-marketing surveillance patterns."
        ),
        args,
    )


TOOL_DISPATCH = {
    "search-reports": search_reports,
    "get-adverse-reactions": get_adverse_reactions,
    "get-reporter-distribution": get_reporter_distribution,
    "get-age-distribution": get_age_distribution,
    "get-region-distribution": get_region_distribution,
    "get-sex-distribution": get_sex_distribution,
    "get-year-distribution": get_year_distribution,
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
