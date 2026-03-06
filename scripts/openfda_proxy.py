#!/usr/bin/env python3
"""
openFDA FAERS Proxy — routes MoltBrowser hub tool calls to api.fda.gov.

Usage:
    echo '{"tool": "search-adverse-events", "args": {"drug_name": "aspirin"}}' | python3 openfda_proxy.py

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.
"""

import json
import sys
import urllib.parse
import urllib.request
import urllib.error

BASE_URL = "https://api.fda.gov/drug/event.json"
DEFAULT_LIMIT = 10
DEFAULT_COUNT_FIELD = "patient.reaction.reactionmeddrapt.exact"
REQUEST_TIMEOUT_SECONDS = 15


def _fetch(url: str) -> dict:
    """Execute an HTTP GET and return parsed JSON. Raises on HTTP/network errors."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "NexVigilant-FerroForge/1.0 (ferroforge@nexvigilant.com)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        # openFDA returns JSON error bodies on 4xx/5xx — surface them
        error_body = {}
        try:
            error_body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            pass
        raise RuntimeError(
            f"HTTP {exc.code}: {error_body.get('error', {}).get('message', exc.reason)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def _quote(value: str) -> str:
    """URL-encode a query value for openFDA search expressions."""
    return urllib.parse.quote(value, safe="")


def search_adverse_events(args: dict) -> dict:
    """
    Tool: search-adverse-events

    Builds a FAERS search query and returns matching adverse event reports.
    Result set includes safetyreportid, receivedate, patient drug list, and
    reaction list for each report.
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required", "count": 0, "results": []}

    reaction = args.get("reaction", "").strip()
    serious = args.get("serious", None)
    limit = int(args.get("limit", DEFAULT_LIMIT))
    limit = max(1, min(limit, 100))  # clamp to openFDA bounds

    # Build search expression
    search_parts = [f'patient.drug.openfda.generic_name:"{_quote(drug_name)}"']

    if reaction:
        search_parts.append(f'patient.reaction.reactionmeddrapt:"{_quote(reaction)}"')

    if serious is True or serious == "true" or serious == 1:
        search_parts.append("serious:1")

    search_expr = "+AND+".join(search_parts)
    url = f"{BASE_URL}?search={search_expr}&limit={limit}"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "count": 0, "results": []}

    total = data.get("meta", {}).get("results", {}).get("total", 0)
    raw_results = data.get("results", [])

    # Extract the most useful fields from each report to keep payload lean
    results = []
    for report in raw_results:
        patient = report.get("patient", {})

        drugs = [
            d.get("openfda", {}).get("generic_name", ["unknown"])[0]
            if d.get("openfda", {}).get("generic_name")
            else d.get("medicinalproduct", "unknown")
            for d in patient.get("drug", [])
        ]

        reactions = [
            r.get("reactionmeddrapt", "unknown")
            for r in patient.get("reaction", [])
        ]

        results.append({
            "safetyreportid": report.get("safetyreportid"),
            "receivedate": report.get("receivedate"),
            "serious": report.get("serious"),
            "seriousnessother": report.get("seriousnessother"),
            "drugs": drugs,
            "reactions": reactions,
            "country": report.get("occurcountry"),
        })

    return {
        "status": "ok",
        "query": {
            "drug_name": drug_name,
            "reaction": reaction or None,
            "serious": serious,
            "limit": limit,
        },
        "total_matching": total,
        "count": len(results),
        "results": results,
    }


def get_drug_counts(args: dict) -> dict:
    """
    Tool: get-drug-counts

    Returns a ranked frequency table of the requested count_field for a drug.
    Defaults to counting by MedDRA reaction preferred term, giving a quick
    signal profile for the drug.
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required", "count": 0, "results": []}

    count_field = args.get("count_field", DEFAULT_COUNT_FIELD).strip()
    if not count_field:
        count_field = DEFAULT_COUNT_FIELD

    search_expr = f'patient.drug.openfda.generic_name:"{_quote(drug_name)}"'
    url = f"{BASE_URL}?search={search_expr}&count={count_field}"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "count": 0, "results": []}

    raw_results = data.get("results", [])

    return {
        "status": "ok",
        "query": {
            "drug_name": drug_name,
            "count_field": count_field,
        },
        "count": len(raw_results),
        "results": raw_results,  # already [{term, count}] from openFDA
    }


TOOL_DISPATCH = {
    "search-adverse-events": search_adverse_events,
    "get-drug-counts": get_drug_counts,
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
