#!/usr/bin/env python3
"""
BfArM Germany Proxy — NexVigilant Station

Domain: www.bfarm.de
Tools: 6 (search-uaw-reports, get-rote-hand-briefe, get-risiko-information,
       search-arzneimittel-register, get-stufenplan-status, get-fachinformation)

BfArM (Bundesinstitut für Arzneimittel und Medizinprodukte) does not expose
a public REST API for UAW-Datenbank or regulatory communications. All tools
return structured reference responses with direct URLs to German regulatory
resources.

Usage:
    echo '{"tool": "get-rote-hand-briefe", "args": {"drug_name": "metformin"}}' | python3 www_bfarm_de_proxy.py
"""

import json
import sys
import urllib.parse


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


USER_AGENT = "NexVigilant-Station/1.0 (station@nexvigilant.com)"
BASE_URL = "https://www.bfarm.de"


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _drug(args: dict) -> str:
    return (args.get("drug_name") or args.get("drug") or args.get("query")
            or args.get("name") or args.get("substance") or "").strip()


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def search_uaw_reports(args: dict) -> dict:
    """Search UAW-Datenbank (German national adverse drug reaction database)."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "BfArM — UAW-Datenbank",
        "drug": drug,
        "resources": [
            {
                "name": "UAW Database (Public Query)",
                "url": "https://nebenwirkungen.bund.de/",
                "note": "Public query interface for German spontaneous ADR reports.",
            },
            {
                "name": "BfArM Pharmacovigilance",
                "url": f"{BASE_URL}/EN/Drugs/Pharmacovigilance/_node.html",
            },
            {
                "name": "BfArM Search",
                "url": f"{BASE_URL}/SiteGlobals/Forms/Suche/EN/Expertensuche_Formular.html?resourceId=12&input_={_quote(drug)}",
            },
        ],
        "note": "UAW-Datenbank (Unerwünschte Arzneimittelwirkungen) is the German national ADR database. Public interface at nebenwirkungen.bund.de supports query by active substance with frequency and reporter-type breakdown. German equivalent to Yellow Card/FAERS for nationally-authorised drugs.",
    }


def get_rote_hand_briefe(args: dict) -> dict:
    """Get Rote-Hand-Briefe (Dear Healthcare Professional letters)."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "BfArM — Rote-Hand-Briefe",
        "drug": drug,
        "resources": [
            {
                "name": "Rote-Hand-Briefe Directory",
                "url": f"{BASE_URL}/DE/Arzneimittel/Pharmakovigilanz/Risikoinformationen/Rote-Hand-Briefe/_node.html",
            },
            {
                "name": "BfArM Risk Information Search",
                "url": f"{BASE_URL}/SiteGlobals/Forms/Suche/EN/Expertensuche_Formular.html?resourceId=12&input_=Rote+Hand+{_quote(drug)}",
            },
        ],
        "note": "Rote-Hand-Briefe (Red Hand Letters) are urgent safety communications from marketing authorisation holders to German prescribers, coordinated through BfArM. Named for the red hand symbol indicating urgent safety information. German equivalent of EMA DHPC.",
    }


def get_risiko_information(args: dict) -> dict:
    """Get BfArM Risiko-Information (risk information bulletins)."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "BfArM — Risiko-Information",
        "drug": drug,
        "resources": [
            {
                "name": "Risk Information Bulletins",
                "url": f"{BASE_URL}/DE/Arzneimittel/Pharmakovigilanz/Risikoinformationen/_node.html",
            },
            {
                "name": "Risk Assessment Publications",
                "url": f"{BASE_URL}/DE/Arzneimittel/Pharmakovigilanz/Bewertungen/_node.html",
            },
        ],
        "note": "Risiko-Information covers Germany-specific safety signals, benefit-risk reassessments, and BfArM-issued risk communications beyond centralised EMA signals. Published as part of German national pharmacovigilance activities.",
    }


def search_arzneimittel_register(args: dict) -> dict:
    """Search German national drug authorisation register."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "BfArM — Arzneimittel-Informationssystem",
        "drug": drug,
        "resources": [
            {
                "name": "AMIS (Drug Information System)",
                "url": "https://www.pharmnet-bund.de/dynamic/de/am-info-system/index.html",
                "note": "Public German drug register (PharmNet.Bund) — searchable by product name, active substance, and authorisation number.",
            },
            {
                "name": "BfArM Authorised Products",
                "url": f"{BASE_URL}/EN/Drugs/licensing/_node.html",
            },
        ],
        "note": "The Arzneimittel-Informationssystem (AMIS) is the German national drug authorisation register covering products authorised via the national, mutual recognition, and decentralised procedures. Not a substitute for EMA centralised register which covers centrally-authorised products.",
    }


def get_stufenplan_status(args: dict) -> dict:
    """Check Stufenplan (staged risk assessment procedure) status."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "BfArM — Stufenplan",
        "drug": drug,
        "resources": [
            {
                "name": "Stufenplan Procedure Overview",
                "url": f"{BASE_URL}/DE/Arzneimittel/Pharmakovigilanz/Stufenplan/_node.html",
            },
            {
                "name": "Stufenplan Publications",
                "url": f"{BASE_URL}/SiteGlobals/Forms/Suche/EN/Expertensuche_Formular.html?resourceId=12&input_=Stufenplan+{_quote(drug)}",
            },
        ],
        "note": "Stufenplan is the German formal staged procedure for evaluating emerging safety signals. Stufe I (information gathering), Stufe II (formal risk assessment with regulatory action). Public Stufenplan notifications are published when regulatory action is decided.",
    }


def get_fachinformation(args: dict) -> dict:
    """Get German Fachinformation (SmPC equivalent) from BfArM."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "BfArM — Fachinformation",
        "drug": drug,
        "resources": [
            {
                "name": "Fachinfo.de (Fachinformation Register)",
                "url": f"https://www.fachinfo.de/suche/fi/{_quote(drug)}",
                "note": "Public German SmPC register operated by Rote Liste Service GmbH.",
            },
            {
                "name": "BfArM Product Information",
                "url": f"{BASE_URL}/EN/Drugs/licensing/MRPDCP/_node.html",
            },
        ],
        "note": "Fachinformation is the German SmPC equivalent — professional product information for licensed drugs. Available through fachinfo.de aggregation service and directly from BfArM for nationally-authorised products.",
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

DISPATCH = {
    "search-uaw-reports": search_uaw_reports,
    "get-rote-hand-briefe": get_rote_hand_briefe,
    "get-risiko-information": get_risiko_information,
    "search-arzneimittel-register": search_arzneimittel_register,
    "get-stufenplan-status": get_stufenplan_status,
    "get-fachinformation": get_fachinformation,
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
