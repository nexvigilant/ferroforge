#!/usr/bin/env python3
"""
FDA Safety Proxy — routes MoltBrowser hub tool calls to openFDA endpoints
for safety communications, MedWatch alerts, boxed warnings, and labeling changes.

Usage:
    echo '{"tool": "get-boxed-warning", "args": {"drug_name": "metformin"}}' | python3 fda_safety_proxy.py

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.
"""

import json
import sys
import urllib.parse
import urllib.request
import urllib.error

ENFORCEMENT_URL = "https://api.fda.gov/drug/enforcement.json"
EVENT_URL = "https://api.fda.gov/drug/event.json"
LABEL_URL = "https://api.fda.gov/drug/label.json"
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


def search_safety_communications(args: dict) -> dict:
    """
    Tool: search-safety-communications

    Search FDA drug safety communications via the enforcement endpoint.
    Returns recall/enforcement actions that serve as safety communications.
    """
    drug_name = _resolve_drug(args)
    if not drug_name:
        return {"status": "error", "message": "drug_name is required (also accepts: drug, name, substance, query)", "count": 0, "results": []}

    year = args.get("year", None)
    limit = int(args.get("limit", DEFAULT_LIMIT))
    limit = max(1, min(limit, 100))

    search_parts = [f'openfda.generic_name:"{_quote(drug_name)}"+openfda.brand_name:"{_quote(drug_name)}"']

    if year:
        search_parts.append(f'report_date:[{year}0101+TO+{year}1231]')

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
            "report_date": record.get("report_date"),
            "recall_initiation_date": record.get("recall_initiation_date"),
            "recalling_firm": record.get("recalling_firm"),
            "voluntary_mandated": record.get("voluntary_mandated"),
            "brand_name": openfda.get("brand_name", [None])[0] if openfda.get("brand_name") else None,
        })

    return {
        "status": "ok",
        "query": {"drug_name": drug_name, "year": year, "limit": limit},
        "total_matching": total,
        "count": len(results),
        "results": results,
    }


def get_medwatch_alerts(args: dict) -> dict:
    """
    Tool: get-medwatch-alerts

    Get MedWatch-style safety alerts by querying FAERS for serious adverse
    events, counted by receive date. Shows volume of serious reports over time.
    """
    drug_name = _resolve_drug(args)
    if not drug_name:
        return {"status": "error", "message": "drug_name is required", "data": {}}

    limit = int(args.get("limit", DEFAULT_LIMIT))
    limit = max(1, min(limit, 100))

    search_expr = f'patient.drug.openfda.generic_name:"{_quote(drug_name)}"+AND+serious:1'
    url = f"{EVENT_URL}?search={search_expr}&count=receivedate"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "data": {}}

    raw = data.get("results", [])

    # Also get total serious count
    total_url = f"{EVENT_URL}?search={search_expr}&limit=1"
    total_serious = 0
    try:
        total_data = _fetch(total_url)
        total_serious = total_data.get("meta", {}).get("results", {}).get("total", 0)
    except RuntimeError:
        pass

    # Get top reactions associated with serious events
    reaction_url = f"{EVENT_URL}?search={search_expr}&count=patient.reaction.reactionmeddrapt.exact"
    top_reactions = []
    try:
        reaction_data = _fetch(reaction_url)
        for item in reaction_data.get("results", [])[:20]:
            top_reactions.append({
                "reaction": item.get("term"),
                "count": item.get("count", 0),
            })
    except RuntimeError:
        pass

    # Return recent date entries
    timeline = [{"date": item.get("time", ""), "count": item.get("count", 0)} for item in raw]

    return {
        "status": "ok",
        "query": {"drug_name": drug_name},
        "data": {
            "total_serious_reports": total_serious,
            "timeline_entries": len(timeline),
            "timeline": timeline[-limit:],
            "top_serious_reactions": top_reactions,
        },
    }


def get_boxed_warning(args: dict) -> dict:
    """
    Tool: get-boxed-warning

    Get the current boxed warning text for a drug from its FDA-approved label.
    Returns the boxed_warning section if present.
    """
    drug_name = _resolve_drug(args)
    if not drug_name:
        return {"status": "error", "message": "drug_name is required", "data": {}}

    search_expr = f'openfda.generic_name:"{_quote(drug_name)}"+openfda.brand_name:"{_quote(drug_name)}"'
    url = f"{LABEL_URL}?search={search_expr}&limit=5"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "data": {}}

    raw_results = data.get("results", [])
    if not raw_results:
        return {"status": "ok", "message": "No label records found", "data": {"has_boxed_warning": False}}

    warnings_found = []
    for label in raw_results:
        openfda = label.get("openfda", {})
        boxed = label.get("boxed_warning", [])

        if not boxed:
            continue

        boxed_text = " ".join(boxed) if isinstance(boxed, list) else str(boxed)

        warnings_found.append({
            "brand_name": openfda.get("brand_name", [None])[0] if openfda.get("brand_name") else None,
            "generic_name": openfda.get("generic_name", [None])[0] if openfda.get("generic_name") else None,
            "set_id": label.get("set_id"),
            "effective_time": label.get("effective_time"),
            "boxed_warning_text": boxed_text[:5000],
        })

    has_warning = len(warnings_found) > 0

    return {
        "status": "ok",
        "query": {"drug_name": drug_name},
        "data": {
            "has_boxed_warning": has_warning,
            "warning_count": len(warnings_found),
            "warnings": warnings_found,
        },
    }


def get_safety_labeling_changes(args: dict) -> dict:
    """
    Tool: get-safety-labeling-changes

    Get recent safety-related labeling changes (SLCs) for a drug.
    Searches drug labels and counts by effective_time to show change frequency.
    Optionally filters by label section.
    """
    drug_name = _resolve_drug(args)
    if not drug_name:
        return {"status": "error", "message": "drug_name is required", "data": {}}

    section = args.get("section", "").strip().lower()
    limit = int(args.get("limit", DEFAULT_LIMIT))
    limit = max(1, min(limit, 100))

    search_expr = f'openfda.generic_name:"{_quote(drug_name)}"+openfda.brand_name:"{_quote(drug_name)}"'

    # Count by effective_time for timeline
    count_url = f"{LABEL_URL}?search={search_expr}&count=effective_time"
    try:
        count_data = _fetch(count_url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "data": {}}

    change_timeline = count_data.get("results", [])

    # Fetch recent labels with detail
    detail_url = f"{LABEL_URL}?search={search_expr}&limit={limit}"
    try:
        detail_data = _fetch(detail_url)
    except RuntimeError:
        detail_data = {"results": []}

    # Map section filter to openFDA field names
    section_fields = {
        "warnings": ["warnings", "warnings_and_cautions"],
        "contraindications": ["contraindications"],
        "adverse reactions": ["adverse_reactions"],
        "boxed warning": ["boxed_warning"],
        "drug interactions": ["drug_interactions"],
        "precautions": ["precautions"],
    }

    labels = []
    for label in detail_data.get("results", []):
        openfda = label.get("openfda", {})

        entry = {
            "effective_time": label.get("effective_time"),
            "set_id": label.get("set_id"),
            "version": label.get("version"),
            "brand_name": openfda.get("brand_name", [None])[0] if openfda.get("brand_name") else None,
            "generic_name": openfda.get("generic_name", [None])[0] if openfda.get("generic_name") else None,
        }

        if section and section in section_fields:
            # Return only the requested section
            fields = section_fields[section]
            section_text = ""
            for field in fields:
                content = label.get(field, [])
                if content:
                    section_text = " ".join(content) if isinstance(content, list) else str(content)
                    break
            entry["section"] = section
            entry["section_text"] = section_text[:3000] if section_text else None
            entry["has_section"] = bool(section_text)
        else:
            # Return which safety sections exist
            entry["sections_present"] = {
                "boxed_warning": bool(label.get("boxed_warning")),
                "warnings": bool(label.get("warnings") or label.get("warnings_and_cautions")),
                "contraindications": bool(label.get("contraindications")),
                "adverse_reactions": bool(label.get("adverse_reactions")),
                "drug_interactions": bool(label.get("drug_interactions")),
                "precautions": bool(label.get("precautions")),
            }

        labels.append(entry)

    return {
        "status": "ok",
        "query": {"drug_name": drug_name, "section": section or None},
        "data": {
            "change_timeline_count": len(change_timeline),
            "change_timeline": change_timeline[-50:],
            "recent_labels": labels,
        },
    }


def get_recall_classification(args: dict) -> dict:
    """
    Tool: get-recall-classification

    Get recall classification breakdown for a drug. FDA classifies recalls:
    Class I (serious health consequences/death), Class II (temporary/reversible),
    Class III (unlikely adverse health consequences).
    """
    drug_name = _resolve_drug(args)
    if not drug_name:
        return {"status": "error", "message": "drug_name is required (also accepts: drug, name, substance, query)", "data": {}}

    limit = int(args.get("limit", 25))
    limit = max(1, min(limit, 100))

    search_expr = f'openfda.generic_name:"{_quote(drug_name)}"+openfda.brand_name:"{_quote(drug_name)}"'

    # Count by classification
    count_url = f"{ENFORCEMENT_URL}?search={search_expr}&count=classification.exact"
    try:
        count_data = _fetch(count_url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "data": {}}

    classification_counts = {}
    for item in count_data.get("results", []):
        classification_counts[item.get("term", "Unknown")] = item.get("count", 0)

    # Count by status (Ongoing, Completed, Terminated)
    status_url = f"{ENFORCEMENT_URL}?search={search_expr}&count=status.exact"
    status_counts = {}
    try:
        status_data = _fetch(status_url)
        for item in status_data.get("results", []):
            status_counts[item.get("term", "Unknown")] = item.get("count", 0)
    except RuntimeError:
        pass

    # Count by voluntary_mandated
    vol_url = f"{ENFORCEMENT_URL}?search={search_expr}&count=voluntary_mandated.exact"
    voluntary_counts = {}
    try:
        vol_data = _fetch(vol_url)
        for item in vol_data.get("results", []):
            voluntary_counts[item.get("term", "Unknown")] = item.get("count", 0)
    except RuntimeError:
        pass

    total = sum(classification_counts.values())

    return {
        "status": "ok",
        "query": {"drug_name": drug_name},
        "data": {
            "total_recalls": total,
            "by_classification": classification_counts,
            "by_status": status_counts,
            "by_voluntary_mandated": voluntary_counts,
            "classification_definitions": {
                "Class I": "Dangerous or defective — reasonable probability of serious adverse health consequences or death",
                "Class II": "May cause temporary or medically reversible adverse health consequences",
                "Class III": "Not likely to cause adverse health consequences",
            },
        },
    }


def get_serious_outcomes(args: dict) -> dict:
    """
    Tool: get-serious-outcomes

    Get serious outcome distribution from FAERS for a drug — death,
    hospitalization, life-threatening, disability, congenital anomaly.
    """
    drug_name = _resolve_drug(args)
    if not drug_name:
        return {"status": "error", "message": "drug_name is required", "data": {}}

    base_search = f'patient.drug.openfda.generic_name:"{_quote(drug_name)}"'

    # Total reports
    total_url = f"{EVENT_URL}?search={base_search}&limit=1"
    total_reports = 0
    try:
        total_data = _fetch(total_url)
        total_reports = total_data.get("meta", {}).get("results", {}).get("total", 0)
    except RuntimeError:
        pass

    # Serious reports
    serious_url = f"{EVENT_URL}?search={base_search}+AND+serious:1&limit=1"
    serious_count = 0
    try:
        serious_data = _fetch(serious_url)
        serious_count = serious_data.get("meta", {}).get("results", {}).get("total", 0)
    except RuntimeError:
        pass

    # Individual outcome fields
    outcomes = {}
    outcome_fields = {
        "death": "seriousnessdeath",
        "hospitalization": "seriousnesshospitalization",
        "life_threatening": "seriousnesslifethreatening",
        "disability": "seriousnessdisabling",
        "congenital_anomaly": "seriousnesscongenitalanomali",
        "other_serious": "seriousnessother",
    }

    for label, field in outcome_fields.items():
        url = f"{EVENT_URL}?search={base_search}+AND+{field}:1&limit=1"
        try:
            data = _fetch(url)
            outcomes[label] = data.get("meta", {}).get("results", {}).get("total", 0)
        except RuntimeError:
            outcomes[label] = 0

    return {
        "status": "ok",
        "query": {"drug_name": drug_name},
        "data": {
            "total_reports": total_reports,
            "serious_reports": serious_count,
            "non_serious_reports": total_reports - serious_count,
            "serious_percentage": round(serious_count / total_reports * 100, 1) if total_reports else 0,
            "outcome_breakdown": outcomes,
        },
    }


def get_rems_info(args: dict) -> dict:
    """
    Tool: get-rems-info

    Get REMS (Risk Evaluation and Mitigation Strategy) information for a drug
    from FDA-approved labeling. Checks for REMS-related content in drug labels.
    """
    drug_name = _resolve_drug(args)
    if not drug_name:
        return {"status": "error", "message": "drug_name is required", "data": {}}

    search_expr = f'openfda.generic_name:"{_quote(drug_name)}"+openfda.brand_name:"{_quote(drug_name)}"'
    url = f"{LABEL_URL}?search={search_expr}&limit=5"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "data": {}}

    raw_results = data.get("results", [])
    if not raw_results:
        return {"status": "ok", "message": "No label records found", "data": {"has_rems": False}}

    rems_found = []
    for label in raw_results:
        openfda = label.get("openfda", {})

        # REMS-related sections
        rems_text = label.get("risk_evaluation_and_mitigation_strategy", [])
        medication_guide = label.get("medication_guide", [])
        patient_package = label.get("patient_medication_information", [])

        if not rems_text and not medication_guide:
            continue

        entry = {
            "brand_name": openfda.get("brand_name", [None])[0] if openfda.get("brand_name") else None,
            "generic_name": openfda.get("generic_name", [None])[0] if openfda.get("generic_name") else None,
            "set_id": label.get("set_id"),
            "has_rems": bool(rems_text),
            "has_medication_guide": bool(medication_guide),
            "has_patient_info": bool(patient_package),
        }

        if rems_text:
            text = " ".join(rems_text) if isinstance(rems_text, list) else str(rems_text)
            entry["rems_text"] = text[:3000]

        if medication_guide:
            text = " ".join(medication_guide) if isinstance(medication_guide, list) else str(medication_guide)
            entry["medication_guide_excerpt"] = text[:2000]

        rems_found.append(entry)

    return {
        "status": "ok",
        "query": {"drug_name": drug_name},
        "data": {
            "has_rems": len(rems_found) > 0,
            "labels_with_rems": len(rems_found),
            "results": rems_found,
            "note": "REMS are FDA-required risk management programs for drugs with serious "
                    "safety concerns. Components may include: Medication Guide, Communication Plan, "
                    "Elements to Assure Safe Use (ETASU), Implementation System.",
        },
    }


TOOL_DISPATCH = {
    "search-safety-communications": search_safety_communications,
    "get-medwatch-alerts": get_medwatch_alerts,
    "get-boxed-warning": get_boxed_warning,
    "get-safety-labeling-changes": get_safety_labeling_changes,
    "get-recall-classification": get_recall_classification,
    "get-serious-outcomes": get_serious_outcomes,
    "get-rems-info": get_rems_info,
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
