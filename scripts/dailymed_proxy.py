#!/usr/bin/env python3
"""
DailyMed SPL Proxy — routes MoltBrowser hub tool calls to dailymed.nlm.nih.gov.

Usage:
    echo '{"tool": "search-drugs", "args": {"query": "aspirin", "limit": 5}}' | python3 dailymed_proxy.py
    echo '{"tool": "get-drug-label", "args": {"drug_name": "warfarin"}}' | python3 dailymed_proxy.py
    echo '{"tool": "get-adverse-reactions", "args": {"drug_name": "metformin"}}' | python3 dailymed_proxy.py

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.

DailyMed API base: https://dailymed.nlm.nih.gov/dailymed/services/
"""

import json
import sys
import urllib.parse
import urllib.request
import urllib.error

BASE_URL = "https://dailymed.nlm.nih.gov/dailymed/services"
OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"
REQUEST_TIMEOUT_SECONDS = 20
DEFAULT_LIMIT = 10


def _fetch(url: str) -> dict:
    """Execute an HTTP GET and return parsed JSON. Raises RuntimeError on failure."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "NexVigilant-FerroForge/1.0 (ferroforge@nexvigilant.com)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        error_body = {}
        try:
            error_body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            pass
        msg = error_body.get("message", exc.reason) if error_body else exc.reason
        raise RuntimeError(f"HTTP {exc.code}: {msg}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def _search_for_setid(drug_name: str) -> str | None:
    """
    Resolve a drug name to its first matching SPL setId via /v2/spls.json.
    Returns the setId string, or None if no results.
    """
    encoded = urllib.parse.quote(drug_name, safe="")
    url = f"{BASE_URL}/v2/spls.json?drug_name={encoded}&pagesize=1"
    try:
        data = _fetch(url)
    except RuntimeError:
        return None

    results = data.get("data", [])
    if not results:
        return None

    return results[0].get("setid")


def search_drugs(args: dict) -> dict:
    """
    Tool: search-drugs

    Searches DailyMed for SPL documents matching a drug name, ingredient, or labeler.
    Returns a list of matching products with their setId, title, and labeler.
    """
    query = args.get("query", "").strip()
    if not query:
        return {"status": "error", "message": "query is required", "count": 0, "results": []}

    limit = int(args.get("limit", DEFAULT_LIMIT))
    limit = max(1, min(limit, 100))

    encoded = urllib.parse.quote(query, safe="")
    url = f"{BASE_URL}/v2/spls.json?drug_name={encoded}&pagesize={limit}"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "count": 0, "results": []}

    raw = data.get("data", [])
    metadata = data.get("metadata", {})
    total = metadata.get("total_elements", len(raw))

    results = []
    for item in raw:
        results.append({
            "setid": item.get("setid"),
            "title": item.get("title"),
            "labeler": item.get("labeler"),
            "published": item.get("published"),
            "application_number": item.get("application_numbers", [None])[0] if item.get("application_numbers") else None,
        })

    return {
        "status": "ok",
        "query": {"query": query, "limit": limit},
        "total_matching": total,
        "count": len(results),
        "results": results,
    }


def get_drug_label(args: dict) -> dict:
    """
    Tool: get-drug-label

    Fetches structured product label (SPL) data for a drug by name.
    Uses two complementary endpoints:
    - DailyMed v2 /spls/{setid}/packaging.json for product/NDC/ingredient data
    - openFDA drug label API for clinical section text (indications, dosage, etc.)

    This two-source approach gives the most complete structured label data
    available without requiring HTML parsing.
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    # Step 1: resolve name → setId via DailyMed search
    setid = _search_for_setid(drug_name)
    if not setid:
        return {
            "status": "not_found",
            "message": f"No SPL found for drug '{drug_name}'",
            "drug_name": drug_name,
        }

    # Step 2: fetch packaging data (products, NDCs, active ingredients)
    packaging_data = {}
    url_pkg = f"{BASE_URL}/v2/spls/{setid}/packaging.json"
    try:
        pkg_resp = _fetch(url_pkg)
        pkg = pkg_resp.get("data", {})
        products = pkg.get("products", [])
        # Summarize: unique active ingredients and NDC counts per product
        packaging_data = {
            "title": pkg.get("title"),
            "published_date": pkg.get("published_date"),
            "product_count": len(products),
            "products": [
                {
                    "product_name": p.get("product_name"),
                    "product_name_generic": p.get("product_name_generic"),
                    "product_code": p.get("product_code"),
                    "active_ingredients": p.get("active_ingredients", []),
                    "ndc_count": len(p.get("packaging", [])),
                    "ndcs": [pkg_entry.get("ndc") for pkg_entry in p.get("packaging", [])],
                }
                for p in products
            ],
        }
    except RuntimeError:
        pass  # Packaging is supplementary

    # Step 3: fetch clinical section text from openFDA label API
    encoded = urllib.parse.quote(drug_name, safe="")
    url_label = f"{OPENFDA_LABEL_URL}?search=openfda.generic_name:{encoded}&limit=1"
    clinical_sections = {}
    openfda_meta = {}
    try:
        label_resp = _fetch(url_label)
        results = label_resp.get("results", [])
        if results:
            label = results[0]
            openfda = label.get("openfda", {})
            openfda_meta = {
                "brand_name": openfda.get("brand_name", [None])[0] if openfda.get("brand_name") else None,
                "generic_name": openfda.get("generic_name", [None])[0] if openfda.get("generic_name") else None,
                "manufacturer_name": openfda.get("manufacturer_name", [None])[0] if openfda.get("manufacturer_name") else None,
                "product_type": openfda.get("product_type", [None])[0] if openfda.get("product_type") else None,
                "route": openfda.get("route", []),
                "application_number": openfda.get("application_number", [None])[0] if openfda.get("application_number") else None,
            }
            # Collect the key clinical sections present in this label
            section_keys = [
                "indications_and_usage", "dosage_and_administration",
                "dosage_forms_and_strengths", "contraindications",
                "warnings_and_cautions", "adverse_reactions",
                "drug_interactions", "use_in_specific_populations",
                "boxed_warning", "mechanism_of_action",
            ]
            for key in section_keys:
                val = label.get(key)
                if isinstance(val, list) and val:
                    clinical_sections[key] = val[0][:500] + "..." if len(val[0]) > 500 else val[0]
    except RuntimeError:
        pass  # Clinical sections are supplementary

    return {
        "status": "ok",
        "drug_name": drug_name,
        "setid": setid,
        "openfda": openfda_meta,
        "packaging": packaging_data,
        "clinical_sections": clinical_sections,
        "sources": ["DailyMed v2 /packaging", "openFDA drug label API"],
    }


def get_adverse_reactions(args: dict) -> dict:
    """
    Tool: get-adverse-reactions

    Extracts the Adverse Reactions section from a drug SPL using the openFDA
    drug label API (api.fda.gov/drug/label.json), which provides the same
    SPL content as DailyMed but in structured JSON form. The DailyMed v2
    sections endpoint returns HTML only; openFDA label is the correct path
    for machine-readable section content.

    Returns adverse_reactions text, boxed_warning if present, and the
    DailyMed setId for cross-reference.
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    # Step 1: resolve name → setId for cross-reference
    setid = _search_for_setid(drug_name)

    # Step 2: query openFDA drug label for structured section content
    encoded = urllib.parse.quote(drug_name, safe="")
    url = f"{OPENFDA_LABEL_URL}?search=openfda.generic_name:{encoded}&limit=1"
    try:
        data = _fetch(url)
    except RuntimeError:
        # Fallback: try brand name search
        url_brand = f"{OPENFDA_LABEL_URL}?search=openfda.brand_name:{encoded}&limit=1"
        try:
            data = _fetch(url_brand)
        except RuntimeError as exc2:
            return {
                "status": "error",
                "message": f"openFDA label lookup failed: {exc2}",
                "drug_name": drug_name,
                "setid": setid,
            }

    results = data.get("results", [])
    if not results:
        return {
            "status": "not_found",
            "message": f"No label found in openFDA for '{drug_name}'",
            "drug_name": drug_name,
            "setid": setid,
        }

    label = results[0]

    # Extract section fields — openFDA returns each as a list of strings
    def _first(field: str) -> str | None:
        val = label.get(field)
        if isinstance(val, list) and val:
            return val[0]
        return val

    adverse_reactions = _first("adverse_reactions")
    boxed_warning = _first("boxed_warning")
    warnings = _first("warnings_and_cautions") or _first("warnings")
    drug_interactions = _first("drug_interactions")

    if not adverse_reactions:
        return {
            "status": "not_found",
            "message": f"Adverse Reactions section not present in label for '{drug_name}'",
            "drug_name": drug_name,
            "setid": setid,
            "available_sections": [k for k in label if not k.startswith("openfda") and not k.startswith("spl")],
        }

    # Pull openFDA metadata for context
    openfda = label.get("openfda", {})

    return {
        "status": "ok",
        "drug_name": drug_name,
        "setid": setid,
        "brand_name": openfda.get("brand_name", [None])[0] if openfda.get("brand_name") else None,
        "generic_name": openfda.get("generic_name", [None])[0] if openfda.get("generic_name") else None,
        "adverse_reactions": adverse_reactions,
        "boxed_warning": boxed_warning,
        "warnings_and_cautions": warnings,
        "drug_interactions": drug_interactions,
        "source": "openFDA drug label API (SPL structured content)",
    }


TOOL_DISPATCH = {
    "search-drugs": search_drugs,
    "get-drug-label": get_drug_label,
    "get-adverse-reactions": get_adverse_reactions,
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
