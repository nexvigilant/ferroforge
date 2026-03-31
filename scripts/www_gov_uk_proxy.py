#!/usr/bin/env python3
"""
MHRA UK Drug Safety Proxy — NexVigilant Station

Domain: www.gov.uk
Tools: 7 (search-yellow-card-reports, get-drug-safety-updates, get-safety-alerts,
       get-par-summary, search-cprd-signals, get-black-triangle-status, get-rmp-uk)

MHRA/gov.uk uses the GOV.UK Content API for some searches. Yellow Card and
CPRD are form-based. Tools return live data where APIs exist, reference URLs
otherwise.

Usage:
    echo '{"tool": "get-drug-safety-updates", "args": {"drug_name": "metformin"}}' | python3 www_gov_uk_proxy.py
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "NexVigilant-Station/1.0 (station@nexvigilant.com)"
GOVUK_SEARCH_API = "https://www.gov.uk/api/search.json"
REQUEST_TIMEOUT = 15
_RETRY_CODES = {429, 503}
_MAX_RETRIES = 3
MAX_TEXT = 2000


def _fetch(url: str) -> dict:
    """HTTP GET with retry."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in _RETRY_CODES and attempt < _MAX_RETRIES - 1:
                time.sleep(0.2 * (3 ** attempt))
                last_exc = exc
                continue
            error_body = {}
            try:
                error_body = json.loads(exc.read().decode("utf-8"))
            except Exception:
                pass
            raise RuntimeError(
                f"HTTP {exc.code}: {error_body.get('error', {}).get('message', exc.reason)}"
            ) from exc
        except urllib.error.URLError as exc:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(0.2 * (3 ** attempt))
                last_exc = exc
                continue
            raise RuntimeError(f"Network error: {exc.reason}") from exc
    raise RuntimeError(f"Failed after {_MAX_RETRIES} retries: {last_exc}")


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _drug(args: dict) -> str:
    return (args.get("drug_name") or args.get("drug") or args.get("query")
            or args.get("name") or args.get("substance") or "").strip()


def _trunc(text, limit=MAX_TEXT):
    if not text:
        return ""
    s = str(text)
    return s[:limit] + "..." if len(s) > limit else s


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def search_yellow_card_reports(args: dict) -> dict:
    """Search MHRA Yellow Card ADR reporting system references."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "MHRA Yellow Card Scheme",
        "drug": drug,
        "resources": [
            {
                "name": "Yellow Card Interactive Drug Analysis Profiles (iDAPs)",
                "url": f"https://info.mhra.gov.uk/drug-analysis-profiles/dap.html?drug=./{_quote(drug)}&agency=MHRA",
            },
            {
                "name": "Yellow Card Reports",
                "url": "https://yellowcard.mhra.gov.uk/",
            },
            {
                "name": "Report a Side Effect",
                "url": "https://yellowcard.mhra.gov.uk/report",
            },
        ],
        "note": "The Yellow Card scheme is the UK system for collecting ADR reports. Interactive Drug Analysis Profiles (iDAPs) show reported reactions by SOC. No public REST API.",
    }


def get_drug_safety_updates(args: dict) -> dict:
    """Get MHRA Drug Safety Update articles via GOV.UK Search API."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    limit = min(int(args.get("limit", 10)), 100)
    # GOV.UK Search API — filter to drug safety updates
    url = (f"{GOVUK_SEARCH_API}?q={_quote(drug)}"
           f"&filter_format=drug_safety_update&count={limit}")
    try:
        data = _fetch(url)
        results = data.get("results", [])
        updates = []
        for r in results[:limit]:
            updates.append({
                "title": _trunc(r.get("title", ""), 500),
                "description": _trunc(r.get("description", ""), 500),
                "url": "https://www.gov.uk" + r.get("link", ""),
                "public_timestamp": r.get("public_timestamp", ""),
            })
        return {
            "status": "ok",
            "source": "MHRA Drug Safety Updates",
            "drug": drug,
            "count": len(updates),
            "updates": updates,
        }
    except RuntimeError as e:
        return {
            "status": "ok",
            "type": "reference",
            "source": "MHRA Drug Safety Updates",
            "drug": drug,
            "error_detail": str(e),
            "resources": [
                {"name": "Drug Safety Update", "url": "https://www.gov.uk/drug-safety-update"},
            ],
        }


def get_safety_alerts(args: dict) -> dict:
    """Get MHRA safety alerts via GOV.UK Search API."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    limit = min(int(args.get("limit", 10)), 100)
    url = (f"{GOVUK_SEARCH_API}?q={_quote(drug)}"
           f"&filter_format=medical_safety_alert&count={limit}")
    try:
        data = _fetch(url)
        results = data.get("results", [])
        alerts = []
        for r in results[:limit]:
            alerts.append({
                "title": _trunc(r.get("title", ""), 500),
                "description": _trunc(r.get("description", ""), 500),
                "url": "https://www.gov.uk" + r.get("link", ""),
                "public_timestamp": r.get("public_timestamp", ""),
                "alert_type": r.get("alert_type", ""),
            })
        return {
            "status": "ok",
            "source": "MHRA Safety Alerts",
            "drug": drug,
            "count": len(alerts),
            "alerts": alerts,
        }
    except RuntimeError as e:
        return {
            "status": "ok",
            "type": "reference",
            "source": "MHRA Safety Alerts",
            "drug": drug,
            "error_detail": str(e),
            "resources": [
                {"name": "Drug & Device Alerts", "url": "https://www.gov.uk/drug-device-alerts"},
            ],
        }


def get_par_summary(args: dict) -> dict:
    """Get Public Assessment Report (PAR) references for a drug."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    # Search GOV.UK for PAR documents
    url = (f"{GOVUK_SEARCH_API}?q={_quote(drug)}+public+assessment+report"
           f"&filter_organisations=medicines-and-healthcare-products-regulatory-agency&count=10")
    try:
        data = _fetch(url)
        results = data.get("results", [])
        pars = []
        for r in results[:10]:
            pars.append({
                "title": _trunc(r.get("title", ""), 500),
                "url": "https://www.gov.uk" + r.get("link", ""),
                "public_timestamp": r.get("public_timestamp", ""),
            })
        return {
            "status": "ok",
            "source": "MHRA Public Assessment Reports",
            "drug": drug,
            "count": len(pars),
            "reports": pars,
        }
    except RuntimeError as e:
        return {
            "status": "ok",
            "type": "reference",
            "source": "MHRA PARs",
            "drug": drug,
            "error_detail": str(e),
            "resources": [
                {"name": "Search PARs on GOV.UK", "url": f"https://www.gov.uk/search/all?keywords={_quote(drug)}+PAR&organisations%5B%5D=medicines-and-healthcare-products-regulatory-agency"},
            ],
        }


def search_cprd_signals(args: dict) -> dict:
    """Search CPRD signal detection references."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "CPRD — Clinical Practice Research Datalink",
        "drug": drug,
        "resources": [
            {
                "name": "CPRD Homepage",
                "url": "https://cprd.com/",
            },
            {
                "name": "CPRD Research Studies",
                "url": "https://cprd.com/research-papers",
            },
        ],
        "note": "CPRD is a UK primary care real-world evidence database. Access requires a research licence. No public query API.",
    }


def get_black_triangle_status(args: dict) -> dict:
    """Get Black Triangle (intensive monitoring) status for a drug."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "MHRA Black Triangle Scheme",
        "drug": drug,
        "resources": [
            {
                "name": "Black Triangle Products List",
                "url": "https://assets.publishing.service.gov.uk/media/65e8cd98e1bdec001aab5c0c/BT_list.pdf",
            },
            {
                "name": "About Black Triangle",
                "url": "https://www.gov.uk/guidance/the-black-triangle-scheme",
            },
        ],
        "note": "Black Triangle products are under intensive monitoring by MHRA. The inverted black triangle symbol appears on packaging and labelling. Check the published list for current status.",
    }


def get_rmp_uk(args: dict) -> dict:
    """Get UK Risk Management Plan references for a drug."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "MHRA UK Risk Management Plans",
        "drug": drug,
        "resources": [
            {
                "name": "RMP Guidance",
                "url": "https://www.gov.uk/guidance/guidance-on-the-risk-management-plan-rmp",
            },
            {
                "name": "Search MHRA Publications",
                "url": f"https://www.gov.uk/search/all?keywords={_quote(drug)}+risk+management+plan&organisations%5B%5D=medicines-and-healthcare-products-regulatory-agency",
            },
        ],
        "note": "UK RMPs follow the EU-RMP format. Published RMP summaries may be available in PARs or EPARs.",
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

DISPATCH = {
    "search-yellow-card-reports": search_yellow_card_reports,
    "get-drug-safety-updates": get_drug_safety_updates,
    "get-safety-alerts": get_safety_alerts,
    "get-par-summary": get_par_summary,
    "search-cprd-signals": search_cprd_signals,
    "get-black-triangle-status": get_black_triangle_status,
    "get-rmp-uk": get_rmp_uk,
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
