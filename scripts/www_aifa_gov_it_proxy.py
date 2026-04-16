#!/usr/bin/env python3
"""
AIFA Italy Proxy — NexVigilant Station

Domain: www.aifa.gov.it
Tools: 6 (search-farmacovigilanza-reports, get-note-aifa, get-dear-doctor-letter,
       search-medicinali-register, get-aifa-rmp, get-monitored-drugs-list)

AIFA (Agenzia Italiana del Farmaco) does not expose a public REST API for
Rete Nazionale di Farmacovigilanza or Note AIFA. All tools return structured
reference responses with direct URLs to Italian regulatory resources.

Usage:
    echo '{"tool": "get-note-aifa", "args": {"drug_name": "metformin"}}' | python3 www_aifa_gov_it_proxy.py
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
BASE_URL = "https://www.aifa.gov.it"


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _drug(args: dict) -> str:
    return (args.get("drug_name") or args.get("drug") or args.get("query")
            or args.get("name") or args.get("substance") or "").strip()


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def search_farmacovigilanza_reports(args: dict) -> dict:
    """Search Italian National Pharmacovigilance Network adverse reaction reports."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "AIFA — Rete Nazionale di Farmacovigilanza",
        "drug": drug,
        "resources": [
            {
                "name": "Italian Pharmacovigilance Network",
                "url": f"{BASE_URL}/farmacovigilanza",
            },
            {
                "name": "ADR Reporting (VigiFarmaco)",
                "url": "https://www.vigifarmaco.it/",
                "note": "Italian national ADR reporting portal operated by Mario Negri Institute on behalf of AIFA.",
            },
            {
                "name": "AIFA Search",
                "url": f"{BASE_URL}/web/guest/aifa-search?query={_quote(drug)}",
            },
        ],
        "note": "Rete Nazionale di Farmacovigilanza (RNF) is the Italian national ADR database. Individual case data is not publicly searchable; aggregate data appears in AIFA periodic safety reports and the Italian Bulletin of Pharmacovigilance.",
    }


def get_note_aifa(args: dict) -> dict:
    """Get Note AIFA — Italian prescribing restrictions and reimbursement conditions."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "AIFA — Note AIFA",
        "drug": drug,
        "resources": [
            {
                "name": "Note AIFA Directory",
                "url": f"{BASE_URL}/note-aifa",
            },
            {
                "name": "Search Note AIFA",
                "url": f"{BASE_URL}/web/guest/aifa-search?query=nota+AIFA+{_quote(drug)}",
            },
        ],
        "note": "Note AIFA define Italian-specific prescribing constraints including reimbursement conditions (SSN coverage), authorised indications beyond SmPC, and specialist-only prescribing rules. These are Italy-specific constraints that may not appear in EMA centralised labelling.",
    }


def get_dear_doctor_letter(args: dict) -> dict:
    """Get AIFA Dear Healthcare Professional letters (Nota Informativa Importante)."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "AIFA — Nota Informativa Importante (NII)",
        "drug": drug,
        "resources": [
            {
                "name": "NII — Dear Healthcare Professional Letters",
                "url": f"{BASE_URL}/nii",
            },
            {
                "name": "Search NII",
                "url": f"{BASE_URL}/web/guest/aifa-search?query=nota+informativa+importante+{_quote(drug)}",
            },
        ],
        "note": "Nota Informativa Importante (NII) are Italian Dear Healthcare Professional letters — urgent safety communications from marketing authorisation holders to Italian prescribers. Distributed through AIFA and professional societies.",
    }


def search_medicinali_register(args: dict) -> dict:
    """Search Italian authorised medicinal products register."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "AIFA — Banca Dati dei Medicinali",
        "drug": drug,
        "resources": [
            {
                "name": "Italian Medicines Database",
                "url": "https://farmaci.agenziafarmaco.gov.it/bancadatifarmaci/",
            },
            {
                "name": "Search by name",
                "url": f"https://farmaci.agenziafarmaco.gov.it/bancadatifarmaci/cerca-farmaco?filtro={_quote(drug)}",
            },
        ],
        "note": "Banca Dati dei Medicinali is the public register of authorised medicinal products in Italy. Provides authorisation number (AIC), marketing holder, presentation, and SmPC/patient leaflet downloads.",
    }


def get_aifa_rmp(args: dict) -> dict:
    """Get Italy-specific Risk Management Plan elements."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "AIFA — Italy-specific Risk Management Plan",
        "drug": drug,
        "resources": [
            {
                "name": "AIFA Risk Management",
                "url": f"{BASE_URL}/risk-management-plan",
            },
            {
                "name": "Registri AIFA (Drug Registries)",
                "url": f"{BASE_URL}/registri-e-piani-terapeutici",
                "note": "Italy operates drug-specific registries for high-cost or high-risk products requiring enhanced monitoring beyond EMA RMP.",
            },
            {
                "name": "Centralised EMA RMP (primary)",
                "url": "https://www.ema.europa.eu/en/medicines",
            },
        ],
        "note": "Italy implements EMA centralised RMPs and may add national additional risk minimisation measures including AIFA Registri (patient-level monitoring registries) and Piani Terapeutici (therapeutic plans requiring specialist prescription).",
    }


def get_monitored_drugs_list(args: dict) -> dict:
    """Get AIFA list of drugs under additional monitoring."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "AIFA — Farmaci Sottoposti a Monitoraggio Addizionale",
        "drug": drug,
        "resources": [
            {
                "name": "Additional Monitoring List",
                "url": f"{BASE_URL}/farmaci-sottoposti-monitoraggio-addizionale",
            },
            {
                "name": "EMA Additional Monitoring (primary)",
                "url": "https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/pharmacovigilance/medicines-under-additional-monitoring",
                "note": "Italy's list is aligned with the EMA additional monitoring list; products are marked with an inverted black triangle.",
            },
        ],
        "note": "Farmaci Sottoposti a Monitoraggio Addizionale is the Italian implementation of EMA additional monitoring. Includes new active substances, biosimilars, conditional approvals, and products with imposed post-authorisation safety studies.",
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

DISPATCH = {
    "search-farmacovigilanza-reports": search_farmacovigilanza_reports,
    "get-note-aifa": get_note_aifa,
    "get-dear-doctor-letter": get_dear_doctor_letter,
    "search-medicinali-register": search_medicinali_register,
    "get-aifa-rmp": get_aifa_rmp,
    "get-monitored-drugs-list": get_monitored_drugs_list,
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
