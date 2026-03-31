#!/usr/bin/env python3
"""
Swissmedic Switzerland Proxy — NexVigilant Station

Domain: www.swissmedic.ch
Tools: 5 (search-safety-signals, get-authorization-info, get-dhpc-letters,
       get-periodic-safety-updates, search-vigilance-reports)

Swissmedic does not offer a public REST API. All tools return structured
reference responses with direct URLs.

Usage:
    echo '{"tool": "get-dhpc-letters", "args": {"drug_name": "metformin"}}' | python3 www_swissmedic_ch_proxy.py
"""

import json
import sys
import urllib.parse

USER_AGENT = "NexVigilant-Station/1.0 (station@nexvigilant.com)"
BASE_URL = "https://www.swissmedic.ch"


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _drug(args: dict) -> str:
    return (args.get("drug_name") or args.get("drug") or args.get("query")
            or args.get("name") or args.get("substance") or "").strip()


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def search_safety_signals(args: dict) -> dict:
    """Search Swissmedic safety signal communications."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "Swissmedic — Safety Signals",
        "drug": drug,
        "resources": [
            {
                "name": "Safety-relevant Information",
                "url": f"{BASE_URL}/en/human/post-authorisation/vigilance/safety-relevant-information.html",
            },
            {
                "name": "Swissmedic Search",
                "url": f"{BASE_URL}/en/search.html#q={_quote(drug)}&t=all",
            },
        ],
        "note": "Swissmedic publishes safety-relevant information including signal assessments. No public REST API.",
    }


def get_authorization_info(args: dict) -> dict:
    """Get Swissmedic drug authorization information."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "Swissmedic — Authorization",
        "drug": drug,
        "resources": [
            {
                "name": "Authorized Medicines (AIPS)",
                "url": f"https://www.swissmedicinfo.ch/?Lang=EN",
                "note": "Swiss drug information portal — search by product name for full prescribing info.",
            },
            {
                "name": "Swissmedic Public Summary SwissPAR",
                "url": f"{BASE_URL}/en/human/authorisations/swiss-par.html",
            },
            {
                "name": "New Authorizations",
                "url": f"{BASE_URL}/en/human/authorisations/new-authorisations.html",
            },
        ],
        "note": "SwissPAR (Swiss Public Assessment Report) provides regulatory assessment summaries. Product information available at swissmedicinfo.ch.",
    }


def get_dhpc_letters(args: dict) -> dict:
    """Get Direct Healthcare Professional Communications (DHPC) from Swissmedic."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "Swissmedic — DHPC Letters",
        "drug": drug,
        "resources": [
            {
                "name": "DHPC Letters",
                "url": f"{BASE_URL}/en/human/post-authorisation/vigilance/direct-healthcare-professional-communications-dhpc.html",
            },
            {
                "name": "Search DHPCs",
                "url": f"{BASE_URL}/en/search.html#q={_quote(drug)}+DHPC&t=all",
            },
        ],
        "note": "DHPCs are sent by marketing authorization holders to healthcare professionals about important new safety information. Searchable on the Swissmedic website.",
    }


def get_periodic_safety_updates(args: dict) -> dict:
    """Get periodic safety update references from Swissmedic."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "Swissmedic — Periodic Safety Updates",
        "drug": drug,
        "resources": [
            {
                "name": "Pharmacovigilance Overview",
                "url": f"{BASE_URL}/en/human/post-authorisation/vigilance.html",
            },
            {
                "name": "PSUR Assessment (via EMA PSUSA)",
                "url": "https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/pharmacovigilance/periodic-safety-update-reports-psurs",
                "note": "Switzerland participates in the EU single PSUR assessment (PSUSA) procedure for many products.",
            },
        ],
        "note": "Swissmedic participates in EU PSUR single assessment where applicable. PSUR conclusions are not individually published on the Swissmedic site.",
    }


def search_vigilance_reports(args: dict) -> dict:
    """Search Swissmedic vigilance reporting resources."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name or query"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "Swissmedic — Vigilance Reports",
        "drug": drug,
        "resources": [
            {
                "name": "Vigilance Annual Reports",
                "url": f"{BASE_URL}/en/human/post-authorisation/vigilance/annual-reports.html",
            },
            {
                "name": "Report an Adverse Event",
                "url": f"{BASE_URL}/en/human/post-authorisation/vigilance/reporting-adverse-reactions.html",
            },
            {
                "name": "ElViS (Electronic Vigilance System)",
                "url": "https://elvis.swissmedic.ch/",
                "note": "Online portal for submitting ADR reports to Swissmedic.",
            },
        ],
        "note": "Swissmedic publishes aggregated vigilance statistics in annual reports. Individual case data is not publicly searchable.",
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

DISPATCH = {
    "search-safety-signals": search_safety_signals,
    "get-authorization-info": get_authorization_info,
    "get-dhpc-letters": get_dhpc_letters,
    "get-periodic-safety-updates": get_periodic_safety_updates,
    "search-vigilance-reports": search_vigilance_reports,
}


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"status": "error", "message": "No input on stdin"}))
        sys.exit(1)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "message": f"Invalid JSON: {exc}"}))
        sys.exit(1)
    tool = payload.get("tool", "").strip()
    args = payload.get("arguments", payload.get("args", {}))
    if tool not in DISPATCH:
        print(json.dumps({"status": "error", "message": f"Unknown tool '{tool}'. Available: {', '.join(sorted(DISPATCH))}"}))
        sys.exit(1)
    try:
        result = DISPATCH[tool](args)
    except Exception as exc:
        result = {"status": "error", "message": str(exc)}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
