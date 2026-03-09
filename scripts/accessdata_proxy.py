#!/usr/bin/env python3
"""
FDA AccessData Proxy — routes MoltBrowser hub tool calls to openFDA endpoints
for drug approvals, Orange Book, REMS, and recall data.

Usage:
    echo '{"tool": "search-approvals", "args": {"drug_name": "metformin"}}' | python3 accessdata_proxy.py

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.
"""

import json
import sys
import urllib.parse
import urllib.request
import urllib.error

DRUGSFDA_URL = "https://api.fda.gov/drug/drugsfda.json"
LABEL_URL = "https://api.fda.gov/drug/label.json"
ENFORCEMENT_URL = "https://api.fda.gov/drug/enforcement.json"
DEFAULT_LIMIT = 10
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


def _resolve_drug(args: dict) -> str:
    """Resolve drug name from any known alias. Agents use varied parameter names."""
    return (args.get("drug_name") or args.get("drug") or args.get("name")
            or args.get("substance") or args.get("product")
            or args.get("query") or "").strip()


def search_approvals(args: dict) -> dict:
    """
    Tool: search-approvals

    Search FDA drug approval records from Drugs@FDA via openFDA.
    Returns application numbers, sponsor names, and approval dates.
    """
    drug_name = _resolve_drug(args)
    if not drug_name:
        return {"status": "error", "message": "drug_name is required", "count": 0, "results": []}

    application_type = args.get("application_type", "").strip()
    limit = int(args.get("limit", DEFAULT_LIMIT))
    limit = max(1, min(limit, 100))

    search_parts = [f'openfda.generic_name:"{_quote(drug_name)}"+openfda.brand_name:"{_quote(drug_name)}"']

    if application_type:
        search_parts = [f'openfda.application_number:"{_quote(application_type)}*"']
        search_parts.append(f'openfda.generic_name:"{_quote(drug_name)}"+openfda.brand_name:"{_quote(drug_name)}"')

    search_expr = "+AND+".join(search_parts)
    url = f"{DRUGSFDA_URL}?search={search_expr}&limit={limit}"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "count": 0, "results": []}

    total = data.get("meta", {}).get("results", {}).get("total", 0)
    raw_results = data.get("results", [])

    results = []
    for record in raw_results:
        openfda = record.get("openfda", {})
        products = record.get("products", [])
        submissions = record.get("submissions", [])

        latest_approval = None
        for sub in submissions:
            if sub.get("submission_status") == "AP":
                sub_date = sub.get("submission_status_date", "")
                if latest_approval is None or sub_date > latest_approval:
                    latest_approval = sub_date

        results.append({
            "application_number": record.get("application_number"),
            "sponsor_name": record.get("sponsor_name"),
            "brand_name": openfda.get("brand_name", [None])[0] if openfda.get("brand_name") else None,
            "generic_name": openfda.get("generic_name", [None])[0] if openfda.get("generic_name") else None,
            "product_count": len(products),
            "submission_count": len(submissions),
            "latest_approval_date": latest_approval,
        })

    return {
        "status": "ok",
        "query": {"drug_name": drug_name, "application_type": application_type or None},
        "total_matching": total,
        "count": len(results),
        "results": results,
    }


def get_approval_history(args: dict) -> dict:
    """
    Tool: get-approval-history

    Get full approval timeline for a drug including supplements.
    Accepts application_number (e.g. "NDA021202") or drug_name for lookup.
    """
    application_number = args.get("application_number", "").strip()
    drug_name = _resolve_drug(args)

    if not application_number and not drug_name:
        return {"status": "error", "message": "application_number or drug_name is required", "data": {}}

    if application_number:
        search_expr = f'application_number:"{_quote(application_number)}"'
    else:
        search_expr = f'openfda.generic_name:"{_quote(drug_name)}"+openfda.brand_name:"{_quote(drug_name)}"'

    url = f"{DRUGSFDA_URL}?search={search_expr}&limit=1"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "data": {}}

    raw_results = data.get("results", [])
    if not raw_results:
        return {"status": "ok", "message": "No approval records found", "data": {}}

    record = raw_results[0]
    submissions = record.get("submissions", [])

    timeline = []
    for sub in submissions:
        timeline.append({
            "submission_type": sub.get("submission_type"),
            "submission_number": sub.get("submission_number"),
            "submission_status": sub.get("submission_status"),
            "submission_status_date": sub.get("submission_status_date"),
            "submission_class_code": sub.get("submission_class_code"),
            "submission_class_code_description": sub.get("submission_class_code_description"),
        })

    timeline.sort(key=lambda x: x.get("submission_status_date") or "")

    return {
        "status": "ok",
        "data": {
            "application_number": record.get("application_number"),
            "sponsor_name": record.get("sponsor_name"),
            "products": record.get("products", []),
            "submission_count": len(timeline),
            "timeline": timeline,
        },
    }


def get_labeling_changes(args: dict) -> dict:
    """
    Tool: get-labeling-changes

    Get safety-related labeling changes for a drug by searching the drug label
    endpoint and counting by effective_time to show when labels changed.
    """
    drug_name = _resolve_drug(args)
    if not drug_name:
        return {"status": "error", "message": "drug_name is required", "data": {}}

    limit = int(args.get("limit", DEFAULT_LIMIT))
    limit = max(1, min(limit, 100))

    search_expr = f'openfda.generic_name:"{_quote(drug_name)}"+openfda.brand_name:"{_quote(drug_name)}"'

    # Get count by effective_time to show labeling change timeline
    count_url = f"{LABEL_URL}?search={search_expr}&count=effective_time"
    try:
        count_data = _fetch(count_url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "data": {}}

    change_dates = count_data.get("results", [])

    # Also fetch the most recent labels for detail
    detail_url = f"{LABEL_URL}?search={search_expr}&limit={limit}"
    try:
        detail_data = _fetch(detail_url)
    except RuntimeError:
        detail_data = {"results": []}

    labels = []
    for label in detail_data.get("results", []):
        openfda = label.get("openfda", {})
        labels.append({
            "effective_time": label.get("effective_time"),
            "set_id": label.get("set_id"),
            "version": label.get("version"),
            "brand_name": openfda.get("brand_name", [None])[0] if openfda.get("brand_name") else None,
            "has_warnings_changes": bool(label.get("warnings_and_cautions") or label.get("warnings")),
            "has_boxed_warning": bool(label.get("boxed_warning")),
        })

    return {
        "status": "ok",
        "query": {"drug_name": drug_name},
        "data": {
            "change_timeline_count": len(change_dates),
            "change_timeline": change_dates[-50:],  # last 50 date entries
            "recent_labels": labels,
        },
    }


def get_orange_book(args: dict) -> dict:
    """
    Tool: get-orange-book

    Get Orange Book patent and exclusivity data for a drug via the
    Drugs@FDA endpoint, which includes product-level patent/exclusivity info.
    """
    drug_name = _resolve_drug(args)
    if not drug_name:
        return {"status": "error", "message": "drug_name is required", "data": {}}

    search_expr = f'openfda.generic_name:"{_quote(drug_name)}"+openfda.brand_name:"{_quote(drug_name)}"'
    url = f"{DRUGSFDA_URL}?search={search_expr}&limit=5"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "data": {}}

    raw_results = data.get("results", [])
    if not raw_results:
        return {"status": "ok", "message": "No records found", "data": {}}

    entries = []
    for record in raw_results:
        openfda = record.get("openfda", {})
        products = record.get("products", [])

        product_details = []
        for prod in products:
            product_details.append({
                "brand_name": prod.get("brand_name"),
                "dosage_form": prod.get("dosage_form"),
                "route": prod.get("route"),
                "marketing_status": prod.get("marketing_status"),
                "te_code": prod.get("te_code"),
                "active_ingredients": prod.get("active_ingredients", []),
            })

        entries.append({
            "application_number": record.get("application_number"),
            "sponsor_name": record.get("sponsor_name"),
            "brand_name": openfda.get("brand_name", [None])[0] if openfda.get("brand_name") else None,
            "generic_name": openfda.get("generic_name", [None])[0] if openfda.get("generic_name") else None,
            "products": product_details,
        })

    return {
        "status": "ok",
        "query": {"drug_name": drug_name},
        "data": {
            "entry_count": len(entries),
            "entries": entries,
        },
    }


def get_rems(args: dict) -> dict:
    """
    Tool: get-rems

    Get Risk Evaluation and Mitigation Strategy (REMS) information for a drug
    by checking the drug label for REMS-related sections.
    """
    drug_name = _resolve_drug(args)
    if not drug_name:
        return {"status": "error", "message": "drug_name is required", "data": {}}

    search_expr = f'openfda.generic_name:"{_quote(drug_name)}"+openfda.brand_name:"{_quote(drug_name)}"'
    url = f"{LABEL_URL}?search={search_expr}&limit=3"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "data": {}}

    raw_results = data.get("results", [])
    if not raw_results:
        return {"status": "ok", "message": "No label records found", "data": {"has_rems": False}}

    rems_entries = []
    for label in raw_results:
        openfda = label.get("openfda", {})

        # Check multiple sections that may contain REMS information
        rems_text = ""
        medication_guide = label.get("medication_guide", [])
        patient_medication = label.get("patient_medication_information", [])
        risk_info = label.get("risk_evaluation_and_mitigation_strategy", [])
        warnings = label.get("warnings_and_cautions", label.get("warnings", []))

        if risk_info:
            rems_text = " ".join(risk_info) if isinstance(risk_info, list) else str(risk_info)

        # Check if REMS is mentioned in warnings
        warnings_text = ""
        if warnings:
            warnings_text = " ".join(warnings) if isinstance(warnings, list) else str(warnings)

        has_rems_section = bool(rems_text)
        has_rems_mention = "rems" in (warnings_text + rems_text).lower() or "risk evaluation" in (warnings_text + rems_text).lower()
        has_medication_guide = bool(medication_guide or patient_medication)

        rems_entries.append({
            "brand_name": openfda.get("brand_name", [None])[0] if openfda.get("brand_name") else None,
            "generic_name": openfda.get("generic_name", [None])[0] if openfda.get("generic_name") else None,
            "set_id": label.get("set_id"),
            "effective_time": label.get("effective_time"),
            "has_rems_section": has_rems_section,
            "has_rems_mention": has_rems_mention,
            "has_medication_guide": has_medication_guide,
            "rems_text": rems_text[:2000] if rems_text else None,
        })

    any_rems = any(e["has_rems_section"] or e["has_rems_mention"] for e in rems_entries)

    return {
        "status": "ok",
        "query": {"drug_name": drug_name},
        "data": {
            "has_rems": any_rems,
            "label_count": len(rems_entries),
            "labels": rems_entries,
        },
    }


def search_recalls(args: dict) -> dict:
    """
    Tool: search-recalls

    Search FDA drug recall and enforcement actions via the openFDA
    enforcement endpoint.
    """
    drug_name = _resolve_drug(args)
    if not drug_name:
        return {"status": "error", "message": "drug_name is required", "count": 0, "results": []}

    classification = args.get("classification", "").strip()
    reason = args.get("reason", "").strip()
    limit = int(args.get("limit", DEFAULT_LIMIT))
    limit = max(1, min(limit, 100))

    search_parts = [f'openfda.generic_name:"{_quote(drug_name)}"+openfda.brand_name:"{_quote(drug_name)}"']

    if classification:
        # Normalize "Class I" / "I" / "class i" to "Class I"
        cls_clean = classification.strip().upper().replace("CLASS ", "").replace("CLASS", "")
        cls_map = {"I": "Class I", "II": "Class II", "III": "Class III",
                    "1": "Class I", "2": "Class II", "3": "Class III"}
        cls_value = cls_map.get(cls_clean, classification)
        search_parts.append(f'classification:"{_quote(cls_value)}"')

    if reason:
        search_parts.append(f'reason_for_recall:"{_quote(reason)}"')

    search_expr = "+AND+".join(search_parts)
    url = f"{ENFORCEMENT_URL}?search={search_expr}&limit={limit}"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "count": 0, "results": []}

    total = data.get("meta", {}).get("results", {}).get("total", 0)
    raw_results = data.get("results", [])

    results = []
    for record in raw_results:
        openfda = record.get("openfda", {})
        results.append({
            "recall_number": record.get("recall_number"),
            "event_id": record.get("event_id"),
            "status": record.get("status"),
            "classification": record.get("classification"),
            "product_description": record.get("product_description"),
            "reason_for_recall": record.get("reason_for_recall"),
            "recall_initiation_date": record.get("recall_initiation_date"),
            "report_date": record.get("report_date"),
            "recalling_firm": record.get("recalling_firm"),
            "city": record.get("city"),
            "state": record.get("state"),
            "voluntary_mandated": record.get("voluntary_mandated"),
            "brand_name": openfda.get("brand_name", [None])[0] if openfda.get("brand_name") else None,
        })

    return {
        "status": "ok",
        "query": {
            "drug_name": drug_name,
            "classification": classification or None,
            "reason": reason or None,
            "limit": limit,
        },
        "total_matching": total,
        "count": len(results),
        "results": results,
    }


TOOL_DISPATCH = {
    "search-approvals": search_approvals,
    "get-approval-history": get_approval_history,
    "get-labeling-changes": get_labeling_changes,
    "get-orange-book": get_orange_book,
    "get-rems": get_rems,
    "search-recalls": search_recalls,
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
