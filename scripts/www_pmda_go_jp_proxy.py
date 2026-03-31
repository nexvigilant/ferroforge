#!/usr/bin/env python3
"""
PMDA Japan Proxy — NexVigilant Station

Domain: www.pmda.go.jp
Tools: 6 (search-safety-information, get-adverse-reactions, get-drug-approval,
       get-rmp-summary, get-reevaluation-results, search-relief-cases)

PMDA does not offer a public REST API. All tools return structured reference
responses with direct URLs to the appropriate PMDA pages.

Usage:
    echo '{"tool": "search-safety-information", "args": {"drug_name": "semaglutide"}}' | python3 www_pmda_go_jp_proxy.py
"""

import json
import sys
import urllib.parse

USER_AGENT = "NexVigilant-Station/1.0 (station@nexvigilant.com)"
BASE_URL = "https://www.pmda.go.jp"


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _drug(args: dict) -> str:
    return (args.get("drug_name") or args.get("drug") or args.get("query")
            or args.get("name") or args.get("substance") or "").strip()


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def search_safety_information(args: dict) -> dict:
    """Search PMDA safety information pages for a drug."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "PMDA Japan — Safety Information",
        "drug": drug,
        "resources": [
            {
                "name": "Safety Information (English)",
                "url": f"{BASE_URL}/english/safety/info-services/drugs/calling-attention/safety-info/0001.html",
            },
            {
                "name": "Pharmaceuticals Search (Japanese)",
                "url": "https://www.pmda.go.jp/PmdaSearch/iyakuSearch/",
            },
        ],
        "note": "PMDA does not offer a public REST API. The English portal has limited coverage; the Japanese portal is comprehensive.",
    }


def get_adverse_reactions(args: dict) -> dict:
    """Get PMDA adverse drug reaction report references."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "PMDA Japan — ADR Reports",
        "drug": drug,
        "resources": [
            {
                "name": "ADR Reports (English)",
                "url": f"{BASE_URL}/english/safety/info-services/drugs/adr-info/0001.html",
            },
            {
                "name": "JADER Database (bulk CSV)",
                "url": f"{BASE_URL}/safety/info-services/drugs/adr-info/suspected-adr/0003.html",
            },
        ],
        "note": "JADER (Japanese Adverse Drug Event Report) database contains spontaneous ADR reports. Bulk CSV downloads available.",
    }


def get_drug_approval(args: dict) -> dict:
    """Get PMDA drug approval information references."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "PMDA Japan — Drug Approvals",
        "drug": drug,
        "resources": [
            {
                "name": "New Drug Approvals (English)",
                "url": f"{BASE_URL}/english/review-services/reviews/approved-information/drugs/0001.html",
            },
            {
                "name": "Review Reports (English)",
                "url": f"{BASE_URL}/english/review-services/reviews/approved-information/drugs/0002.html",
            },
            {
                "name": "Drug Search (Japanese)",
                "url": "https://www.pmda.go.jp/PmdaSearch/iyakuSearch/",
            },
        ],
        "note": "English summaries available for recent approvals.",
    }


def get_rmp_summary(args: dict) -> dict:
    """Get PMDA Risk Management Plan summary references."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "PMDA Japan — Risk Management Plans",
        "drug": drug,
        "resources": [
            {
                "name": "RMP List (Japanese)",
                "url": f"{BASE_URL}/safety/info-services/drugs/items-information/rmp/0001.html",
            },
            {
                "name": "RMP Guidance (English)",
                "url": f"{BASE_URL}/english/safety/info-services/drugs/items-information/rmp/0001.html",
            },
        ],
        "note": "RMPs follow ICH E2E principles. Documents published in Japanese; English summaries may exist for some products.",
    }


def get_reevaluation_results(args: dict) -> dict:
    """Get PMDA drug reevaluation results references."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "PMDA Japan — Reevaluation Results",
        "drug": drug,
        "resources": [
            {
                "name": "Reevaluation Results (English)",
                "url": f"{BASE_URL}/english/review-services/reviews/approved-information/drugs/0003.html",
            },
            {
                "name": "Post-Marketing Studies (Japanese)",
                "url": f"{BASE_URL}/safety/info-services/drugs/calling-attention/iyaku-jyouhou/0001.html",
            },
        ],
        "note": "Japan requires post-marketing reevaluation. Results include efficacy/safety confirmations and usage condition changes.",
    }


def search_relief_cases(args: dict) -> dict:
    """Search PMDA adverse health effects relief system references."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "PMDA Japan — Relief System",
        "drug": drug,
        "resources": [
            {
                "name": "Relief System Overview (English)",
                "url": f"{BASE_URL}/english/relief-services/adr-sufferers/0001.html",
            },
            {
                "name": "Relief Case Statistics (Japanese)",
                "url": f"{BASE_URL}/relief-services/adr-sufferers/0001.html",
            },
        ],
        "note": "PMDA operates Japan's ADR Relief System, providing benefits to patients who suffer serious ADRs from properly used pharmaceuticals.",
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

DISPATCH = {
    "search-safety-information": search_safety_information,
    "get-adverse-reactions": get_adverse_reactions,
    "get-drug-approval": get_drug_approval,
    "get-rmp-summary": get_rmp_summary,
    "get-reevaluation-results": get_reevaluation_results,
    "search-relief-cases": search_relief_cases,
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
