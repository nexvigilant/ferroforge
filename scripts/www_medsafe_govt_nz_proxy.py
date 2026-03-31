#!/usr/bin/env python3
"""
Medsafe New Zealand Proxy — NexVigilant Station

Domain: www.medsafe.govt.nz
Reference proxy — structured URLs for NZ Medicines and Medical Devices Safety Authority.
"""

import json
import sys
import urllib.parse


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



BASE = "https://www.medsafe.govt.nz"


def _q(v: str) -> str:
    return urllib.parse.quote(str(v), safe="")


def _drug(a: dict) -> str:
    return (a.get("drug_name") or a.get("drug") or a.get("query") or a.get("name") or "").strip()


def search_adverse_reactions(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    return {
        "status": "ok", "source": "CARM Adverse Reaction Reports (NZ)", "drug": drug,
        "resources": [
            {"name": "CARM (Centre for Adverse Reactions Monitoring)", "url": f"{BASE}/safety/carm.asp"},
            {"name": "Report an ADR", "url": f"{BASE}/safety/report-a-problem.asp"},
        ],
        "note": f"CARM collects adverse reaction reports for NZ. No public REST API — search for '{drug}' via the web interface or request data from CARM directly.",
    }


def get_prescriber_update(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    return {
        "status": "ok", "source": "Medsafe Prescriber Update", "drug": drug,
        "resources": [
            {"name": "Prescriber Update Articles", "url": f"{BASE}/profs/PUArticles.asp"},
            {"name": "Search Prescriber Update", "url": f"{BASE}/searchResults.asp?q={_q(drug)}&collection=medsafe-profs"},
        ],
        "note": "Prescriber Update is Medsafe's quarterly bulletin with safety articles for health professionals.",
    }


def get_data_sheet(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    return {
        "status": "ok", "source": "Medsafe Data Sheets (NZ PI)", "drug": drug,
        "resources": [
            {"name": "Data Sheet Search", "url": f"{BASE}/profs/Datasheet/dsform.asp"},
            {"name": "Search Results", "url": f"{BASE}/searchResults.asp?q={_q(drug)}&collection=medsafe-datasheet"},
        ],
        "note": "New Zealand approved data sheets are equivalent to Product Information documents.",
    }


def get_safety_communications(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    return {
        "status": "ok", "source": "Medsafe Safety Communications", "drug": drug,
        "resources": [
            {"name": "Safety Information", "url": f"{BASE}/safety/safety-info.asp"},
            {"name": "Alerts & Communications", "url": f"{BASE}/hot/alerts.asp"},
            {"name": "Media Releases", "url": f"{BASE}/hot/media.asp"},
        ],
    }


DISPATCH = {
    "search-adverse-reactions": search_adverse_reactions,
    "get-prescriber-update": get_prescriber_update,
    "get-data-sheet": get_data_sheet,
    "get-safety-communications": get_safety_communications,
}


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"status": "error", "message": "No input"}))
        return
    try:
        p = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        return
    tool = ensure_str(p.get("tool", "")).strip()
    args = p.get("arguments", p.get("args", {}))
    h = DISPATCH.get(tool)
    if not h:
        print(json.dumps({"status": "error", "message": f"Unknown tool '{tool}'"}))
        return
    try:
        print(json.dumps(h(args)))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))


if __name__ == "__main__":
    main()
