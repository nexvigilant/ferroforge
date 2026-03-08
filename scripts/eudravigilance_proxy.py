#!/usr/bin/env python3
"""
EudraVigilance Proxy — live substance lookup + dashboard URL generation.

Queries the public adrreports.eu substance tables to resolve drug names to
EudraVigilance substance codes and generate dashboard URLs. No session tokens
or authentication required — these are public HTML tables served by the EMA.

Data source: https://www.adrreports.eu (EMA public access portal)
Endpoint: /tables/substance/{first_letter}.html

Phase 1 (current): Substance lookup, code resolution, dashboard URL generation.
Phase 2 (future): OBIEE dashboard data extraction for case counts and signals.
"""

import json
import re
import sys
import urllib.request
from html import unescape

BASE_URL = "https://www.adrreports.eu"
DAP_URL = "https://dap.ema.europa.eu/analyticsSOAP/saw.dll"
DATA_SOURCE = "eudravigilance.ema.europa.eu"
USER_AGENT = "NexVigilant-Station/1.0 (PV research tool)"
TIMEOUT = 15


def _fetch(url: str) -> str:
    """Fetch a URL and return decoded text."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    resp = urllib.request.urlopen(req, timeout=TIMEOUT)
    return resp.read().decode("utf-8", errors="replace")


def _parse_substance_table(html: str) -> list[dict]:
    """Parse an adrreports.eu substance table into structured records."""
    results = []
    rows = html.split("<tr>")
    for row in rows[1:]:  # skip header
        urls = re.findall(r'href="([^"]+)"', row)
        texts = [t.strip() for t in re.findall(r">([^<]+)<", row) if t.strip()]
        if not urls or not texts:
            continue
        name = texts[0]
        dashboard_url = unescape(urls[0])
        # Extract substance code from URL (P3=1+{code})
        code_match = re.search(r"P3=1\+(\d+)", dashboard_url)
        code = code_match.group(1) if code_match else None
        results.append({
            "substance_name": name,
            "substance_code": code,
            "dashboard_url": dashboard_url,
        })
    return results


def _lookup_substance(drug: str) -> list[dict]:
    """Look up a drug in the adrreports.eu substance tables."""
    first_letter = drug.strip()[0].lower()
    url = f"{BASE_URL}/tables/substance/{first_letter}.html"
    html = _fetch(url)
    all_substances = _parse_substance_table(html)
    drug_upper = drug.strip().upper()
    # Exact match first, then prefix match, then contains
    exact = [s for s in all_substances if s["substance_name"] == drug_upper]
    if exact:
        return exact
    prefix = [s for s in all_substances if s["substance_name"].startswith(drug_upper)]
    if prefix:
        return prefix
    contains = [s for s in all_substances if drug_upper in s["substance_name"]]
    return contains


def search_reports(args: dict) -> dict:
    """Search EudraVigilance substance tables for a drug and return dashboard links."""
    drug = args.get("drug", args.get("substance", "")).strip()
    if not drug:
        return {"status": "error", "message": "substance is required", "results": []}

    try:
        matches = _lookup_substance(drug)
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to query adrreports.eu: {type(e).__name__}: {e}",
            "results": [],
        }

    if not matches:
        return {
            "status": "ok",
            "message": f"No EudraVigilance entries found for '{drug}'",
            "count": 0,
            "results": [],
            "data_source": DATA_SOURCE,
        }

    return {
        "status": "ok",
        "count": len(matches),
        "results": matches,
        "data_source": DATA_SOURCE,
        "note": "Dashboard URLs link to EudraVigilance public access portal with full ICSR line listings, "
                "case counts by SOC, seriousness breakdown, and signal detection data.",
    }


def get_signal_summary(args: dict) -> dict:
    """Get signal summary — resolves substance, returns dashboard link for signal data."""
    drug = args.get("drug", args.get("substance", "")).strip()
    reaction = args.get("reaction", args.get("event", "")).strip()
    if not drug:
        return {"status": "error", "message": "substance is required"}

    try:
        matches = _lookup_substance(drug)
    except Exception as e:
        return {"status": "error", "message": f"Lookup failed: {e}"}

    if not matches:
        return {"status": "ok", "message": f"No entries for '{drug}'", "data": {}}

    substance = matches[0]
    return {
        "status": "ok",
        "data": {
            "substance": substance["substance_name"],
            "substance_code": substance["substance_code"],
            "reaction_queried": reaction or "(all reactions)",
            "dashboard_url": substance["dashboard_url"],
            "signal_data_available": True,
            "access_note": "Signal detection tab on the dashboard provides PRR, ROR, IC metrics "
                           "computed by EudraVigilance. Navigate to 'Number of Individual Cases' tab "
                           "for disproportionality statistics.",
        },
        "data_source": DATA_SOURCE,
    }


def get_case_counts(args: dict) -> dict:
    """Get case count summary — resolves substance, returns dashboard link."""
    drug = args.get("drug", args.get("substance", "")).strip()
    if not drug:
        return {"status": "error", "message": "substance is required"}

    try:
        matches = _lookup_substance(drug)
    except Exception as e:
        return {"status": "error", "message": f"Lookup failed: {e}"}

    if not matches:
        return {"status": "ok", "message": f"No entries for '{drug}'", "data": {}}

    substance = matches[0]
    return {
        "status": "ok",
        "data": {
            "substance": substance["substance_name"],
            "substance_code": substance["substance_code"],
            "dashboard_url": substance["dashboard_url"],
            "available_breakdowns": [
                "System Organ Class (SOC)",
                "Seriousness (serious/non-serious)",
                "Age group",
                "Sex",
                "Reporter qualification",
                "Reporting year",
                "Geographical distribution (EEA countries)",
            ],
            "access_note": "Dashboard 'Number of Individual Cases' tab provides aggregate counts "
                           "with all breakdowns listed above.",
        },
        "data_source": DATA_SOURCE,
    }


def get_geographical_distribution(args: dict) -> dict:
    """Get geographical distribution — resolves substance, returns dashboard link."""
    drug = args.get("drug", args.get("substance", "")).strip()
    if not drug:
        return {"status": "error", "message": "substance is required"}

    try:
        matches = _lookup_substance(drug)
    except Exception as e:
        return {"status": "error", "message": f"Lookup failed: {e}"}

    if not matches:
        return {"status": "ok", "message": f"No entries for '{drug}'", "data": {}}

    substance = matches[0]
    return {
        "status": "ok",
        "data": {
            "substance": substance["substance_name"],
            "substance_code": substance["substance_code"],
            "dashboard_url": substance["dashboard_url"],
            "access_note": "Dashboard 'Number of Individual Cases by EEA Countries' tab "
                           "provides per-country ICSR counts for all EEA member states.",
        },
        "data_source": DATA_SOURCE,
    }


def get_soc_breakdown(args: dict) -> dict:
    """Get System Organ Class breakdown for a substance."""
    drug = args.get("drug", args.get("substance", "")).strip()
    if not drug:
        return {"status": "error", "message": "substance is required"}

    try:
        matches = _lookup_substance(drug)
    except Exception as e:
        return {"status": "error", "message": f"Lookup failed: {e}"}

    if not matches:
        return {"status": "ok", "message": f"No entries for '{drug}'", "data": {}}

    substance = matches[0]
    return {
        "status": "ok",
        "data": {
            "substance": substance["substance_name"],
            "substance_code": substance["substance_code"],
            "dashboard_url": substance["dashboard_url"],
            "available_soc_categories": [
                "Blood and lymphatic system disorders",
                "Cardiac disorders",
                "Gastrointestinal disorders",
                "General disorders and administration site conditions",
                "Hepatobiliary disorders",
                "Immune system disorders",
                "Infections and infestations",
                "Investigations",
                "Metabolism and nutrition disorders",
                "Musculoskeletal and connective tissue disorders",
                "Nervous system disorders",
                "Psychiatric disorders",
                "Renal and urinary disorders",
                "Respiratory, thoracic and mediastinal disorders",
                "Skin and subcutaneous tissue disorders",
                "Vascular disorders",
            ],
            "access_note": "Dashboard 'Number of Individual Cases for a selected Reaction Group' tab "
                           "provides per-SOC case counts with serious/non-serious split.",
        },
        "data_source": DATA_SOURCE,
    }


def get_reporter_breakdown(args: dict) -> dict:
    """Get reporter qualification breakdown for a substance."""
    drug = args.get("drug", args.get("substance", "")).strip()
    if not drug:
        return {"status": "error", "message": "substance is required"}

    try:
        matches = _lookup_substance(drug)
    except Exception as e:
        return {"status": "error", "message": f"Lookup failed: {e}"}

    if not matches:
        return {"status": "ok", "message": f"No entries for '{drug}'", "data": {}}

    substance = matches[0]
    return {
        "status": "ok",
        "data": {
            "substance": substance["substance_name"],
            "substance_code": substance["substance_code"],
            "dashboard_url": substance["dashboard_url"],
            "reporter_categories": [
                "Healthcare Professional",
                "Non-Healthcare Professional (Consumer/Patient)",
                "Not Specified",
            ],
            "access_note": "Dashboard 'Number of Individual Cases by Healthcare Professional / "
                           "Non-Healthcare Professional' tab provides reporter qualification "
                           "breakdown. HCP reports carry higher evidentiary weight in signal evaluation.",
        },
        "data_source": DATA_SOURCE,
    }


def get_age_sex_distribution(args: dict) -> dict:
    """Get age group and sex distribution for a substance."""
    drug = args.get("drug", args.get("substance", "")).strip()
    if not drug:
        return {"status": "error", "message": "substance is required"}

    try:
        matches = _lookup_substance(drug)
    except Exception as e:
        return {"status": "error", "message": f"Lookup failed: {e}"}

    if not matches:
        return {"status": "ok", "message": f"No entries for '{drug}'", "data": {}}

    substance = matches[0]
    return {
        "status": "ok",
        "data": {
            "substance": substance["substance_name"],
            "substance_code": substance["substance_code"],
            "dashboard_url": substance["dashboard_url"],
            "age_groups": [
                "0-1 Month", "2 Months - 2 Years", "3-11 Years",
                "12-17 Years", "18-64 Years", "65-85 Years",
                "More than 85 Years", "Not Specified",
            ],
            "sex_categories": ["Female", "Male", "Not Specified"],
            "access_note": "Dashboard 'Number of Individual Cases by Age Group' and "
                           "'Number of Individual Cases by Sex' tabs provide demographic "
                           "breakdowns for risk characterization.",
        },
        "data_source": DATA_SOURCE,
    }


TOOL_DISPATCH = {
    "search-reports": search_reports,
    "get-signal-summary": get_signal_summary,
    "get-case-counts": get_case_counts,
    "get-geographical-distribution": get_geographical_distribution,
    "get-soc-breakdown": get_soc_breakdown,
    "get-reporter-breakdown": get_reporter_breakdown,
    "get-age-sex-distribution": get_age_sex_distribution,
}


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"status": "error", "message": "No input on stdin", "results": []}))
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "message": f"Invalid JSON: {exc}", "results": []}))
        sys.exit(1)

    tool_name = payload.get("tool", "").strip()
    args = payload.get("arguments", payload.get("args", {}))

    if tool_name not in TOOL_DISPATCH:
        print(json.dumps({
            "status": "error",
            "message": f"Unknown tool '{tool_name}'. Known: {list(TOOL_DISPATCH.keys())}",
            "results": [],
        }))
        sys.exit(1)

    result = TOOL_DISPATCH[tool_name](args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
