#!/usr/bin/env python3
"""
Health Canada Drug Safety Proxy — NexVigilant Station

Domain: recalls-rappels.canada.ca
Reference proxy with structured URLs for Health Canada drug safety resources.
Drug Product Database API used for product lookups where available.
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DPD_API = "https://health-products.canada.ca/api/drug"
REQUEST_TIMEOUT = 15
USER_AGENT = "NexVigilant-Station/1.0 (station@nexvigilant.com)"
_RETRY_CODES = {429, 503}
_MAX_RETRIES = 2


def _fetch_json(url: str):
    """HTTP GET returning parsed JSON, or None on failure."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(_MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                ct = resp.headers.get("Content-Type", "")
                if "json" not in ct and "javascript" not in ct:
                    return None
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError):
            if attempt < _MAX_RETRIES - 1:
                time.sleep(0.3)
                continue
            return None
    return None


def _q(v: str) -> str:
    return urllib.parse.quote(str(v), safe="")


def _drug(args: dict) -> str:
    return (args.get("drug_name") or args.get("drug") or args.get("query")
            or args.get("name") or args.get("substance") or "").strip()


def search_recalls(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    return {
        "status": "ok",
        "source": "Health Canada Recalls & Safety Alerts",
        "drug": drug,
        "resources": [
            {"name": "Recalls & Safety Alerts Search", "url": f"https://recalls-rappels.canada.ca/en/search/site?search_api_fulltext={_q(drug)}"},
            {"name": "Drug & Health Product Recalls", "url": "https://www.canada.ca/en/health-canada/services/drugs-health-products/medeffect-canada/safety-reviews.html"},
        ],
        "note": f"Search for '{drug}' in the Health Canada recalls database. Filter by 'Health Products' category.",
    }


def get_safety_reviews(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    return {
        "status": "ok",
        "source": "Health Canada Summary Safety Reviews",
        "drug": drug,
        "resources": [
            {"name": "Summary Safety Reviews", "url": "https://www.canada.ca/en/health-canada/services/drugs-health-products/medeffect-canada/safety-reviews.html"},
            {"name": "Search SSRs", "url": f"https://hpr-rps.hres.ca/reg-content/summary-safety-review.php?lang=en&q={_q(drug)}"},
        ],
        "note": "Summary Safety Reviews are Health Canada's formal safety evaluations. Published when a potential safety issue is identified.",
    }


def search_adverse_reactions(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    reaction = args.get("reaction", "")
    return {
        "status": "ok",
        "source": "Canada Vigilance Adverse Reaction Online Database",
        "drug": drug,
        "reaction_filter": reaction or None,
        "resources": [
            {"name": "Canada Vigilance Database", "url": "https://www.canada.ca/en/health-canada/services/drugs-health-products/medeffect-canada/adverse-reaction-database.html"},
            {"name": "Direct Search", "url": "https://cvp-pcv.hc-sc.gc.ca/arq-rei/index-eng.jsp"},
            {"name": "MedEffect Canada", "url": "https://www.canada.ca/en/health-canada/services/drugs-health-products/medeffect-canada.html"},
        ],
        "note": f"Search Canada Vigilance for '{drug}' adverse reaction reports." + (f" Filter by reaction: '{reaction}'." if reaction else ""),
    }


def get_risk_communications(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    return {
        "status": "ok",
        "source": "Health Canada Risk Communications",
        "drug": drug,
        "resources": [
            {"name": "Advisories, Warnings & Recalls", "url": f"https://recalls-rappels.canada.ca/en/search/site?search_api_fulltext={_q(drug)}"},
            {"name": "Health Professional Risk Communications", "url": "https://www.canada.ca/en/health-canada/services/drugs-health-products/medeffect-canada/advisories-warnings.html"},
            {"name": "Dear Healthcare Professional Letters", "url": "https://www.canada.ca/en/health-canada/services/drugs-health-products/medeffect-canada/advisories-warnings/dear-health-care-professional-letters.html"},
        ],
    }


def get_drug_product_database(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    url = f"{DPD_API}/drugproduct/?brandname={_q(drug)}&lang=en&type=json"
    data = _fetch_json(url)
    if data and isinstance(data, list) and len(data) > 0:
        products = [
            {
                "din": p.get("drug_identification_number", ""),
                "brand_name": p.get("brand_name", ""),
                "company": p.get("company_name", ""),
                "class": p.get("class_name", ""),
                "status": p.get("status", ""),
            }
            for p in data[:15]
        ]
        return {"status": "ok", "source": "Drug Product Database (DPD)", "drug": drug, "count": len(products), "products": products}
    return {
        "status": "ok",
        "type": "reference",
        "source": "Drug Product Database",
        "drug": drug,
        "resources": [{"name": "DPD Online Query", "url": "https://health-products.canada.ca/dpd-bdpp/index-eng.jsp"}],
        "note": f"No results found via API for '{drug}'. Try the web interface.",
    }


def get_natural_health_products(args: dict) -> dict:
    query = _drug(args)
    if not query:
        return {"status": "error", "message": "query is required"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "Licensed Natural Health Products Database",
        "query": query,
        "resources": [{"name": "LNHPD Search", "url": "https://health-products.canada.ca/lnhpd-bdpsnh/index-eng.jsp"}],
    }


def get_clinical_trial_database(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "Health Canada Clinical Trials Database",
        "drug": drug,
        "resources": [
            {"name": "Clinical Trials Database", "url": "https://health-products.canada.ca/ctdb-bdec/index-eng.jsp"},
            {"name": "Search by Drug", "url": f"https://health-products.canada.ca/ctdb-bdec/search-recherche.do?brandName={_q(drug)}&lang=eng"},
        ],
    }


DISPATCH = {
    "search-recalls": search_recalls,
    "get-safety-reviews": get_safety_reviews,
    "search-adverse-reactions": search_adverse_reactions,
    "get-risk-communications": get_risk_communications,
    "get-drug-product-database": get_drug_product_database,
    "get-natural-health-products": get_natural_health_products,
    "get-clinical-trial-database": get_clinical_trial_database,
}


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"status": "error", "message": "No input on stdin"}))
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "message": f"Invalid JSON: {exc}"}))
        return
    tool = payload.get("tool", "").strip()
    args = payload.get("arguments", payload.get("args", {}))
    handler = DISPATCH.get(tool)
    if not handler:
        print(json.dumps({"status": "error", "message": f"Unknown tool '{tool}'. Available: {', '.join(sorted(DISPATCH))}"}))
        return
    try:
        result = handler(args)
    except Exception as exc:
        result = {"status": "error", "message": str(exc)}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
