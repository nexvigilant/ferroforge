#!/usr/bin/env python3
"""
EMA Proxy — routes tool calls to European Medicines Agency public JSON data files.

EMA publishes static JSON dumps updated twice daily (06:00 and 18:00 CET):
  https://www.ema.europa.eu/en/documents/report/<name>_en.json

Usage:
    echo '{"tool": "search-medicines", "arguments": {"query": "metformin"}}' | python3 ema_proxy.py

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.
"""

import json
import sys
import urllib.request
import urllib.error

# EMA public JSON data file URLs
MEDICINES_URL = "https://www.ema.europa.eu/en/documents/report/medicines-output-medicines_json-report_en.json"
REFERRALS_URL = "https://www.ema.europa.eu/en/documents/report/referrals-output-json-report_en.json"
PSUSA_URL = "https://www.ema.europa.eu/en/documents/report/medicines-output-periodic_safety_update_report_single_assessments-output-json-report_en.json"
EPAR_DOCS_URL = "https://www.ema.europa.eu/en/documents/report/documents-output-epar_documents_json-report_en.json"
DHPC_URL = "https://www.ema.europa.eu/en/documents/report/dhpc-output-json-report_en.json"

REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_LIMIT = 20

# In-process cache: URL -> parsed JSON (avoids re-fetching within a single dispatch)
_cache: dict[str, list] = {}


def _fetch_json_list(url: str) -> list:
    """Fetch a JSON data file and return the list of records. Caches per-process."""
    if url in _cache:
        return _cache[url]

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "NexVigilant-FerroForge/1.0 (ferroforge@nexvigilant.com)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc

    # EMA JSON files are either a bare list or a dict with a data key
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        for key in ("data", "results", "medicines", "referrals", "psusa"):
            if key in data and isinstance(data[key], list):
                records = data[key]
                break
        else:
            records = [data]
    else:
        records = []

    _cache[url] = records
    return records


def _match(value: str, query: str) -> bool:
    """Case-insensitive substring match."""
    return query.lower() in value.lower() if value and query else False


def _get_field(rec: dict, *keys: str) -> str:
    """Return the first non-empty value from a list of candidate keys."""
    for k in keys:
        val = rec.get(k)
        if val:
            return str(val)
    return ""


def _extract_medicine(rec: dict) -> dict:
    """Extract a lean medicine summary from an EMA medicines record."""
    return {
        "medicine_name": _get_field(rec, "name_of_medicine", "medicine_name") or None,
        "active_substance": _get_field(rec, "active_substance") or None,
        "inn": _get_field(rec, "international_non_proprietary_name_common_name") or None,
        "therapeutic_area": _get_field(rec, "therapeutic_area_mesh") or None,
        "therapeutic_indication": (_get_field(rec, "therapeutic_indication") or "")[:500] or None,
        "authorisation_status": _get_field(rec, "medicine_status") or None,
        "atc_code": _get_field(rec, "atc_code_human") or None,
        "pharmacotherapeutic_group": _get_field(rec, "pharmacotherapeutic_group_human") or None,
        "marketing_authorisation_holder": _get_field(rec, "marketing_authorisation_developer_applicant_holder") or None,
        "marketing_authorisation_date": _get_field(rec, "marketing_authorisation_date") or None,
        "ema_product_number": _get_field(rec, "ema_product_number") or None,
        "category": _get_field(rec, "category") or None,
        "orphan_medicine": rec.get("orphan_medicine"),
        "additional_monitoring": rec.get("additional_monitoring"),
        "url": rec.get("medicine_url"),
    }


def search_medicines(args: dict) -> dict:
    """
    Tool: search-medicines

    Search EU-authorised medicines by name, active substance, or therapeutic area.
    Queries the EMA medicines JSON data file (updated twice daily).
    """
    query = (args.get("query") or args.get("product") or args.get("drug_name") or "").strip()
    therapeutic_area = (args.get("therapeutic_area") or "").strip()
    auth_status = (args.get("authorisation_status") or "").strip()
    limit = int(args.get("limit", DEFAULT_LIMIT))
    limit = max(1, min(limit, 100))

    if not query and not therapeutic_area:
        return {"status": "error", "message": "query or therapeutic_area is required", "count": 0, "results": []}

    try:
        records = _fetch_json_list(MEDICINES_URL)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "count": 0, "results": []}

    matches = []
    for rec in records:
        name = _get_field(rec, "name_of_medicine", "medicine_name")
        substance = _get_field(rec, "active_substance")
        inn = _get_field(rec, "international_non_proprietary_name_common_name")
        area = _get_field(rec, "therapeutic_area_mesh")
        status = _get_field(rec, "medicine_status")

        if query and not (_match(name, query) or _match(substance, query) or _match(inn, query)):
            continue
        if therapeutic_area and not _match(area, therapeutic_area):
            continue
        if auth_status and not _match(status, auth_status):
            continue

        matches.append(_extract_medicine(rec))
        if len(matches) >= limit:
            break

    return {
        "status": "ok",
        "query": {"query": query or None, "therapeutic_area": therapeutic_area or None, "authorisation_status": auth_status or None},
        "total_in_database": len(records),
        "count": len(matches),
        "results": matches,
    }


def get_epar(args: dict) -> dict:
    """
    Tool: get-epar

    Get European Public Assessment Report summary for a medicine.
    Searches the medicines database for the product, then fetches EPAR document
    metadata from the EPAR documents feed.
    """
    medicine_name = (args.get("medicine_name") or args.get("product") or args.get("drug_name") or "").strip()
    if not medicine_name:
        return {"status": "error", "message": "medicine_name is required", "data": {}}

    try:
        medicines = _fetch_json_list(MEDICINES_URL)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "data": {}}

    medicine_info = None
    for rec in medicines:
        name = _get_field(rec, "name_of_medicine", "medicine_name")
        substance = _get_field(rec, "active_substance")
        if _match(name, medicine_name) or _match(substance, medicine_name):
            medicine_info = _extract_medicine(rec)
            break

    if not medicine_info:
        return {
            "status": "ok",
            "message": f"No medicine found matching '{medicine_name}'",
            "data": {"found": False},
        }

    # Search EPAR documents for this medicine
    epar_docs = []
    try:
        docs = _fetch_json_list(EPAR_DOCS_URL)
        for doc in docs:
            doc_medicine = _get_field(doc, "name_of_medicine", "medicine_name", "name")
            if _match(doc_medicine, medicine_name):
                epar_docs.append({
                    "title": _get_field(doc, "title", "document_title") or None,
                    "type": _get_field(doc, "type", "document_type", "category") or None,
                    "language": doc.get("language"),
                    "url": doc.get("url"),
                    "created_date": _get_field(doc, "created_date", "createdDate", "first_published") or None,
                    "modified_date": _get_field(doc, "modified_date", "modifiedDate", "revision_date") or None,
                })
    except RuntimeError:
        pass

    return {
        "status": "ok",
        "query": {"medicine_name": medicine_name},
        "data": {
            "found": True,
            "medicine": medicine_info,
            "epar_documents_count": len(epar_docs),
            "epar_documents": epar_docs[:20],
        },
    }


def get_safety_signals(args: dict) -> dict:
    """
    Tool: get-safety-signals

    Get PRAC safety signal assessments from the DHPC (Direct Healthcare
    Professional Communications) feed, which captures safety signals that
    resulted in communications to healthcare professionals.
    """
    substance = (args.get("substance") or args.get("product") or args.get("drug_name") or "").strip()
    year = args.get("year")

    try:
        records = _fetch_json_list(DHPC_URL)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "data": {}}

    matches = []
    for rec in records:
        rec_substance = _get_field(rec, "active_substances", "active_substance")
        rec_medicine = _get_field(rec, "name_of_medicine")
        rec_date = _get_field(rec, "dissemination_date", "first_published_date")

        if substance and not (_match(rec_substance, substance) or _match(rec_medicine, substance)):
            continue
        if year and str(year) not in str(rec_date):
            continue

        matches.append({
            "medicine_name": rec_medicine or None,
            "active_substance": rec_substance or None,
            "dhpc_type": rec.get("dhpc_type") or None,
            "regulatory_outcome": rec.get("regulatory_outcome") or None,
            "procedure_number": rec.get("procedure_number") or None,
            "therapeutic_area": rec.get("therapeutic_area_mesh") or None,
            "dissemination_date": _get_field(rec, "dissemination_date") or None,
            "url": rec.get("dhpc_url") or None,
        })

    return {
        "status": "ok",
        "query": {"substance": substance or None, "year": year},
        "data": {
            "total_dhpc_records": len(records),
            "matching_count": len(matches),
            "signals": matches[:50],
        },
    }


def get_referral(args: dict) -> dict:
    """
    Tool: get-referral

    Get details of Article 31/20 referral procedures from the EMA referrals feed.
    """
    substance = (args.get("substance") or args.get("product") or args.get("drug_name") or "").strip()
    if not substance:
        return {"status": "error", "message": "substance is required", "data": {}}

    try:
        records = _fetch_json_list(REFERRALS_URL)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "data": {}}

    matches = []
    for rec in records:
        rec_substance = _get_field(rec, "international_non_proprietary_name_inn_common_name", "active_substance")
        rec_name = _get_field(rec, "referral_name")

        if not (_match(rec_substance, substance) or _match(rec_name, substance)):
            continue

        matches.append({
            "referral_name": rec_name or None,
            "active_substance": rec_substance or None,
            "referral_type": rec.get("referral_type") or None,
            "current_status": rec.get("current_status") or None,
            "safety_referral": rec.get("safety_referral") or None,
            "reference_number": rec.get("reference_number") or None,
            "procedure_start_date": rec.get("procedure_start_date") or None,
            "prac_recommendation_date": rec.get("prac_recommendation_date") or None,
            "chmp_opinion_date": rec.get("chmp_cvmp_opinion_date") or None,
            "ec_decision_date": rec.get("european_commission_decision_date") or None,
            "url": rec.get("referral_url") or None,
        })

    return {
        "status": "ok",
        "query": {"substance": substance},
        "data": {
            "total_referrals_in_database": len(records),
            "matching_count": len(matches),
            "referrals": matches,
        },
    }


def get_psur_assessment(args: dict) -> dict:
    """
    Tool: get-psur-assessment

    Get Periodic Safety Update Report (PSUR/PSUSA) single assessment outcomes
    for an active substance.
    """
    substance = (args.get("substance") or args.get("product") or args.get("drug_name") or "").strip()
    if not substance:
        return {"status": "error", "message": "substance is required", "data": {}}

    try:
        records = _fetch_json_list(PSUSA_URL)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "data": {}}

    matches = []
    for rec in records:
        rec_substance = _get_field(rec, "active_substance", "active_substances_in_scope_of_procedure")

        if not _match(rec_substance, substance):
            continue

        matches.append({
            "active_substance": rec_substance or None,
            "procedure_number": rec.get("procedure_number") or None,
            "regulatory_outcome": rec.get("regulatory_outcome") or None,
            "related_medicines": rec.get("related_medicines") or None,
            "url": rec.get("psusa_url") or None,
        })

    return {
        "status": "ok",
        "query": {"substance": substance},
        "data": {
            "total_psusa_in_database": len(records),
            "matching_count": len(matches),
            "assessments": matches,
        },
    }


def get_rmp_summary(args: dict) -> dict:
    """
    Tool: get-rmp-summary

    Get Risk Management Plan summary for a medicine. Extracts RMP-related
    documents from the EPAR documents feed.
    """
    medicine_name = (args.get("medicine_name") or args.get("product") or args.get("drug_name") or "").strip()
    if not medicine_name:
        return {"status": "error", "message": "medicine_name is required", "data": {}}

    try:
        medicines = _fetch_json_list(MEDICINES_URL)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "data": {}}

    medicine_info = None
    for rec in medicines:
        name = _get_field(rec, "name_of_medicine", "medicine_name")
        substance = _get_field(rec, "active_substance")
        if _match(name, medicine_name) or _match(substance, medicine_name):
            medicine_info = _extract_medicine(rec)
            break

    if not medicine_info:
        return {
            "status": "ok",
            "message": f"No medicine found matching '{medicine_name}'",
            "data": {"found": False},
        }

    rmp_docs = []
    try:
        docs = _fetch_json_list(EPAR_DOCS_URL)
        rmp_keywords = ("risk management", "rmp", "risk minimisation", "risk minimization")
        for doc in docs:
            doc_medicine = _get_field(doc, "name_of_medicine", "medicine_name", "name")
            doc_title = _get_field(doc, "title", "document_title")
            doc_type = _get_field(doc, "type", "document_type", "category")

            if not _match(doc_medicine, medicine_name):
                continue

            searchable = f"{doc_title} {doc_type}".lower()
            if not any(kw in searchable for kw in rmp_keywords):
                continue

            rmp_docs.append({
                "title": doc_title or None,
                "type": doc_type or None,
                "language": doc.get("language"),
                "url": doc.get("url"),
                "created_date": _get_field(doc, "created_date", "createdDate", "first_published") or None,
            })
    except RuntimeError:
        pass

    return {
        "status": "ok",
        "query": {"medicine_name": medicine_name},
        "data": {
            "found": True,
            "medicine": medicine_info,
            "rmp_documents_count": len(rmp_docs),
            "rmp_documents": rmp_docs[:20],
        },
    }


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
    try:
        result = handler(args)
    except RuntimeError as exc:
        result = {"status": "error", "error": True, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        result = {
            "status": "error",
            "error": True,
            "message": f"Unexpected error in '{tool_name}': {type(exc).__name__}: {exc}",
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
