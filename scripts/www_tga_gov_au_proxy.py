#!/usr/bin/env python3
"""
TGA Australia Drug Safety Proxy — NexVigilant Station

Domain: www.tga.gov.au
Tools: 6 (search-daen-reports, get-safety-alerts, get-product-information,
       get-adr-reports, search-artg, get-recalls)

TGA uses form-based interfaces (DAEN, ARTG). Tools that can hit searchable
endpoints do so; others return structured reference URLs.

Usage:
    echo '{"tool": "search-artg", "args": {"query": "metformin"}}' | python3 www_tga_gov_au_proxy.py
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


import json

def ensure_str(val) -> str:
    """Coerce any input to string safely to prevent AttributeError."""
    if val is None:
        return ""
    if isinstance(val, (int, float, bool)):
        return str(val)
    if isinstance(val, (list, dict)):
        try:
            return json.dumps(val)
        except Exception:
            return str(val)
    return str(val)

def get_int_param(args: dict, key: str, default: int, min_val: int = None, max_val: int = None) -> int:
    """Safely parse integer parameter with optional clamping."""
    val = args.get(key)
    if val is None:
        return default
    try:
        res = int(val)
    except (ValueError, TypeError):
        return default
    if min_val is not None:
        res = max(res, min_val)
    if max_val is not None:
        res = min(res, max_val)
    return res



USER_AGENT = "NexVigilant-Station/1.0 (station@nexvigilant.com)"
BASE_URL = "https://www.tga.gov.au"
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

def search_daen_reports(args: dict) -> dict:
    """Search the Database of Adverse Event Notifications (DAEN)."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name or query"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "TGA Australia — DAEN",
        "drug": drug,
        "resources": [
            {
                "name": "DAEN — Medicines",
                "url": "https://apps.tga.gov.au/PROD/DAEN/daen-report.aspx",
                "note": "Form-based search. Enter medicine name to find adverse event reports.",
            },
            {
                "name": "DAEN — Medical Devices",
                "url": "https://apps.tga.gov.au/PROD/DAEN/daen-entry.aspx",
            },
        ],
        "note": "The DAEN is form-based with no public REST API. Search by medicine name to view adverse event notification counts by reaction, outcome, and reporter type.",
    }


def get_safety_alerts(args: dict) -> dict:
    """Get TGA safety alerts and advisories."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "TGA Australia — Safety Alerts",
        "drug": drug,
        "resources": [
            {
                "name": "Safety Alerts",
                "url": f"{BASE_URL}/news/safety-alerts",
            },
            {
                "name": "Safety Communications",
                "url": f"{BASE_URL}/safety/safety-communications",
            },
            {
                "name": "Search TGA",
                "url": f"{BASE_URL}/search?query={_quote(drug)}&collection=tga-artg&profile=_default&num_ranks=10",
            },
        ],
        "note": "TGA publishes safety alerts, advisory statements, and Dear Healthcare Professional letters. Search the TGA site for drug-specific communications.",
    }


def get_product_information(args: dict) -> dict:
    """Get TGA product information (PI) document references."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "TGA Australia — Product Information",
        "drug": drug,
        "resources": [
            {
                "name": "Product Information (PI) Search",
                "url": f"https://www.ebs.tga.gov.au/ebs/picmi/picmirepository.nsf/PICMI?OpenForm&t=PI&q={_quote(drug)}",
            },
            {
                "name": "Consumer Medicine Information (CMI)",
                "url": f"https://www.ebs.tga.gov.au/ebs/picmi/picmirepository.nsf/PICMI?OpenForm&t=CMI&q={_quote(drug)}",
            },
        ],
        "note": "Product Information documents are the Australian equivalent of prescribing information / SmPC. Searchable by brand or active ingredient.",
    }


def get_adr_reports(args: dict) -> dict:
    """Get adverse drug reaction reporting references for TGA."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "TGA Australia — ADR Reporting",
        "drug": drug,
        "resources": [
            {
                "name": "Report a Problem",
                "url": f"{BASE_URL}/safety/report-problem",
            },
            {
                "name": "DAEN Search",
                "url": "https://apps.tga.gov.au/PROD/DAEN/daen-report.aspx",
            },
            {
                "name": "Medicines Safety Update",
                "url": f"{BASE_URL}/publication/medicines-safety-update",
            },
        ],
        "note": "TGA encourages reporting of suspected ADRs. The DAEN provides aggregate adverse event notification data.",
    }


def search_artg(args: dict) -> dict:
    """Search the Australian Register of Therapeutic Goods (ARTG)."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name or query"}
    # TGA has a searchable ARTG page
    search_url = f"{BASE_URL}/resources/artg?search={_quote(drug)}"
    return {
        "status": "ok",
        "type": "reference",
        "source": "TGA Australia — ARTG",
        "query": drug,
        "resources": [
            {
                "name": "ARTG Search",
                "url": search_url,
            },
            {
                "name": "ARTG Public Summary",
                "url": f"https://www.tga.gov.au/resources/artg",
            },
        ],
        "note": "The ARTG lists all therapeutic goods legally supplied in Australia. Search by product name, active ingredient, or ARTG number.",
    }


def get_recalls(args: dict) -> dict:
    """Get TGA product recall information."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "TGA Australia — Recalls",
        "drug": drug,
        "resources": [
            {
                "name": "Medicine Recalls",
                "url": f"{BASE_URL}/safety/recalls/medicines",
            },
            {
                "name": "Search Recalls",
                "url": f"{BASE_URL}/search?query={_quote(drug)}&collection=tga-recall",
            },
            {
                "name": "Shortages",
                "url": f"{BASE_URL}/safety/shortages",
            },
        ],
        "note": "TGA maintains a register of recalled therapeutic goods including medicines, medical devices, and biologicals.",
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

DISPATCH = {
    "search-daen-reports": search_daen_reports,
    "get-safety-alerts": get_safety_alerts,
    "get-product-information": get_product_information,
    "get-adr-reports": get_adr_reports,
    "search-artg": search_artg,
    "get-recalls": get_recalls,
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
    tool = ensure_str(payload.get("tool", "")).strip()
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
