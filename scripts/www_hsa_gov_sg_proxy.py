#!/usr/bin/env python3
"""
HSA Singapore Drug Safety Proxy — NexVigilant Station

Domain: www.hsa.gov.sg
Reference proxy — structured URLs for Singapore Health Sciences Authority resources.
"""

import json
import sys
import urllib.parse

BASE = "https://www.hsa.gov.sg"


def _q(v: str) -> str:
    return urllib.parse.quote(str(v), safe="")


def _drug(a: dict) -> str:
    return (a.get("drug_name") or a.get("drug") or a.get("query") or a.get("name") or "").strip()


def search_adverse_reactions(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    return {
        "status": "ok", "source": "HSA Singapore ADR Database", "drug": drug,
        "resources": [
            {"name": "ADR Reporting & Search", "url": f"{BASE}/content/hsa/en/Health_Products_Regulation/Safety_Information_and_Product_Recalls/Adverse_Event_Reporting.html"},
            {"name": "HSA Safety Alerts", "url": f"{BASE}/announcements/safety-alert"},
        ],
        "note": f"HSA does not offer a public ADR REST API. Search '{drug}' via the web portal.",
    }


def get_safety_alerts(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    return {
        "status": "ok", "source": "HSA Safety Alerts", "drug": drug,
        "resources": [
            {"name": "Safety Alerts", "url": f"{BASE}/announcements/safety-alert"},
            {"name": "Dear Healthcare Professional Letters", "url": f"{BASE}/content/hsa/en/Health_Products_Regulation/Safety_Information_and_Product_Recalls/Dear_Healthcare_Professional_Letters.html"},
        ],
    }


def get_product_registration(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    return {
        "status": "ok", "source": "HSA Product Registration", "drug": drug,
        "resources": [
            {"name": "PRISM e-Service", "url": "https://eservice.hsa.gov.sg/prism/common/enquirepublic/SearchDRBProduct.do"},
        ],
        "note": f"Search PRISM for '{drug}' to check Singapore registration status.",
    }


def get_therapeutic_product_recalls(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    return {
        "status": "ok", "source": "HSA Product Recalls", "drug": drug,
        "resources": [{"name": "Product Recalls", "url": f"{BASE}/announcements/product-recall"}],
    }


DISPATCH = {
    "search-adverse-reactions": search_adverse_reactions,
    "get-safety-alerts": get_safety_alerts,
    "get-product-registration": get_product_registration,
    "get-therapeutic-product-recalls": get_therapeutic_product_recalls,
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
    tool = p.get("tool", "").strip()
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
