#!/usr/bin/env python3
"""
EMA Medicines Proxy — routes MoltBrowser hub tool calls to medicines.health.europa.eu.

Usage:
    echo '{"tool": "search-medicines", "args": {"query": "metformin"}}' | python3 ema_proxy.py

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.

Currently implemented as intelligent stubs. Each tool returns a well-structured
response describing what the live version would return from the EMA medicines
database API.
"""

import json
import sys

DATA_SOURCE = "medicines.health.europa.eu"
IMPLEMENTATION_NOTES = "Requires EMA API integration"


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


def search_medicines(args: dict) -> dict:
    """
    Tool: search-medicines

    Searches the EMA medicines database for authorized medicinal products.
    The live version queries medicines.health.europa.eu and returns a list of
    matching products with their authorization status, ATC code, active
    substance, therapeutic area, and marketing authorization holder.
    """
    query = args.get("query", "").strip()
    if not query:
        return {"status": "error", "message": "query is required"}

    return _stub_response(
        "search-medicines",
        args,
        "Returns a list of EMA-authorized medicinal products matching the query, "
        "including product name, active substance, ATC code, therapeutic area, "
        "authorization status (authorized/withdrawn/suspended/refused), "
        "marketing authorization holder, and authorization date.",
    )


def get_epar(args: dict) -> dict:
    """
    Tool: get-epar

    Retrieves the European Public Assessment Report (EPAR) summary for a
    specific medicine. The live version returns the EPAR document metadata,
    product information summary, benefit-risk assessment, and conditions of
    authorization from the EMA website.
    """
    product = args.get("product", "").strip()
    if not product:
        return {"status": "error", "message": "product is required"}

    return _stub_response(
        "get-epar",
        args,
        "Returns the EPAR summary for the specified product, including "
        "therapeutic indication, posology, contraindications, benefit-risk "
        "conclusion, conditions of authorization, date of authorization, "
        "and links to the full EPAR document and product information.",
    )


def get_safety_signals(args: dict) -> dict:
    """
    Tool: get-safety-signals

    Retrieves safety signals assessed by the PRAC (Pharmacovigilance Risk
    Assessment Committee) for a given substance or product. The live version
    returns signal assessments including the signal source, PRAC recommendation,
    and current status.
    """
    substance = args.get("substance", args.get("product", "")).strip()
    if not substance:
        return {"status": "error", "message": "substance or product is required"}

    return _stub_response(
        "get-safety-signals",
        args,
        "Returns PRAC safety signal assessments for the specified substance, "
        "including signal description, MedDRA preferred term, signal source "
        "(spontaneous reports, literature, clinical trial), date detected, "
        "PRAC recommendation (routine/priority/urgent), current status "
        "(ongoing/closed/confirmed), and outcome actions taken.",
    )


def get_referral(args: dict) -> dict:
    """
    Tool: get-referral

    Retrieves referral procedures (Article 20, 31, or 107i) related to a
    substance or product. The live version returns referral details including
    the legal basis, scope, CHMP/PRAC opinion, and outcome.
    """
    substance = args.get("substance", args.get("product", "")).strip()
    if not substance:
        return {"status": "error", "message": "substance or product is required"}

    return _stub_response(
        "get-referral",
        args,
        "Returns EMA referral procedure details for the specified substance, "
        "including referral type (Article 20/31/107i), legal basis, scope of "
        "review, start date, CHMP/PRAC opinion date, outcome "
        "(maintained/restricted/suspended/revoked), conditions imposed, "
        "and links to assessment reports.",
    )


def get_psur_assessment(args: dict) -> dict:
    """
    Tool: get-psur-assessment

    Retrieves PSUR (Periodic Safety Update Report) assessment outcomes for a
    substance. The live version returns the PSUR single assessment (PSUSA)
    procedure details, PRAC recommendations, and any resulting label changes.
    """
    substance = args.get("substance", args.get("product", "")).strip()
    if not substance:
        return {"status": "error", "message": "substance or product is required"}

    return _stub_response(
        "get-psur-assessment",
        args,
        "Returns PSUR single assessment (PSUSA) outcomes for the specified "
        "substance, including PSUSA procedure number, data lock point, "
        "PRAC rapporteur, PRAC recommendation (maintain/vary/suspend/revoke), "
        "CMDh/CHMP position, dates of assessment, and whether product "
        "information changes were required.",
    )


def get_rmp_summary(args: dict) -> dict:
    """
    Tool: get-rmp-summary

    Retrieves the Risk Management Plan (RMP) summary for a product. The live
    version returns identified risks, potential risks, missing information,
    and risk minimization measures from the RMP.
    """
    product = args.get("product", "").strip()
    if not product:
        return {"status": "error", "message": "product is required"}

    return _stub_response(
        "get-rmp-summary",
        args,
        "Returns the RMP summary for the specified product, including "
        "important identified risks, important potential risks, missing "
        "information categories, pharmacovigilance activities (routine and "
        "additional), risk minimization measures (routine and additional), "
        "and post-authorization safety studies (PASS) if any.",
    )


TOOL_DISPATCH = {
    "search-medicines": search_medicines,
    "get-epar": get_epar,
    "get-safety-signals": get_safety_signals,
    "get-referral": get_referral,
    "get-psur-assessment": get_psur_assessment,
    "get-rmp-summary": get_rmp_summary,
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
