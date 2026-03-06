#!/usr/bin/env python3
"""
EudraVigilance Proxy — routes MoltBrowser hub tool calls for EU pharmacovigilance data.

Usage:
    echo '{"tool": "search-reports", "args": {"drug": "metformin"}}' | python3 eudravigilance_proxy.py

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.

EudraVigilance has no public API — all tools are intelligent stubs that return
well-structured responses describing what the live version would return.
"""

import json
import sys

DATA_SOURCE = "eudravigilance.ema.europa.eu"
IMPLEMENTATION_NOTES = "Requires EudraVigilance API integration"


def _read_input() -> dict:
    """Read and parse a JSON object from stdin."""
    raw = sys.stdin.read().strip()
    if not raw:
        return None
    return json.loads(raw)


def _stub_response(tool_name: str, args: dict, description: str) -> dict:
    """Build a standard stub response."""
    return {
        "status": "stub",
        "tool": tool_name,
        "description": description,
        "parameters_received": args,
        "data_source": DATA_SOURCE,
        "implementation_notes": IMPLEMENTATION_NOTES,
    }


def search_reports(args: dict) -> dict:
    """
    Tool: search-reports

    Searches EudraVigilance for Individual Case Safety Reports (ICSRs) related
    to a drug substance. The live version queries the EudraVigilance database
    and returns aggregated line listings of suspected adverse reaction reports
    from the EEA.
    """
    drug = args.get("drug", args.get("substance", "")).strip()
    if not drug:
        return {"status": "error", "message": "drug is required"}

    return _stub_response(
        "search-reports",
        args,
        "Returns EudraVigilance ICSR line listings for the specified drug, "
        "including report type (spontaneous/study/other), case reference number, "
        "EV gateway receipt date, primary source country, reporter qualification "
        "(healthcare professional/consumer), patient age group, patient sex, "
        "suspect/interacting drug names, MedDRA reaction preferred terms, "
        "seriousness criteria (death, life-threatening, hospitalization, "
        "disability, congenital anomaly, other medically important), "
        "and outcome (recovered, not yet recovered, fatal, unknown).",
    )


def get_signal_summary(args: dict) -> dict:
    """
    Tool: get-signal-summary

    Retrieves signal detection summary statistics for a drug-event combination
    from EudraVigilance. The live version returns disproportionality metrics
    (PRR, ROR, IC) computed from the EudraVigilance database.
    """
    drug = args.get("drug", args.get("substance", "")).strip()
    if not drug:
        return {"status": "error", "message": "drug is required"}

    reaction = args.get("reaction", args.get("event", "")).strip()

    return _stub_response(
        "get-signal-summary",
        args,
        "Returns signal detection statistics for the specified drug-event "
        "combination from EudraVigilance, including total number of ICSRs, "
        "number of cases for the specific drug-event pair, expected count, "
        "Proportional Reporting Ratio (PRR) with 95% CI, Reporting Odds Ratio "
        "(ROR) with 95% CI, Information Component (IC) with IC025 lower bound, "
        "chi-squared value, signal status (new/ongoing/closed), and date of "
        "last assessment.",
    )


def get_case_counts(args: dict) -> dict:
    """
    Tool: get-case-counts

    Retrieves aggregated case counts for a drug from EudraVigilance, broken
    down by System Organ Class (SOC), seriousness, age group, sex, and
    reporter type. The live version returns the same data available on the
    EudraVigilance public dashboard (adrreports.eu).
    """
    drug = args.get("drug", args.get("substance", "")).strip()
    if not drug:
        return {"status": "error", "message": "drug is required"}

    group_by = args.get("group_by", "soc").strip()

    return _stub_response(
        "get-case-counts",
        args,
        "Returns aggregated ICSR case counts for the specified drug from "
        "EudraVigilance, grouped by the requested dimension. Available "
        "groupings: 'soc' (System Organ Class with case count per SOC), "
        "'seriousness' (serious vs non-serious with subcategories), "
        "'age_group' (neonate/infant/child/adolescent/adult/elderly/not specified), "
        "'sex' (male/female/not specified), 'reporter' (healthcare professional/"
        "consumer/not specified), 'year' (case counts by reporting year for "
        "trend analysis). Each group includes total count and percentage of "
        "all reports.",
    )


def get_geographical_distribution(args: dict) -> dict:
    """
    Tool: get-geographical-distribution

    Retrieves the geographical distribution of EudraVigilance reports for a drug,
    broken down by EEA country. The live version returns per-country case counts
    from the adrreports.eu dashboard.
    """
    drug = args.get("drug", args.get("substance", "")).strip()
    if not drug:
        return {"status": "error", "message": "drug is required"}

    return _stub_response(
        "get-geographical-distribution",
        args,
        "Returns geographical distribution of EudraVigilance ICSRs for the "
        "specified drug, including per-country case counts for all EEA member "
        "states, total EEA count, total non-EEA count, top 5 reporting "
        "countries by volume, reporting rate per million population where "
        "available, and breakdown by EEA vs non-EEA origin.",
    )


TOOL_DISPATCH = {
    "search-reports": search_reports,
    "get-signal-summary": get_signal_summary,
    "get-case-counts": get_case_counts,
    "get-geographical-distribution": get_geographical_distribution,
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
