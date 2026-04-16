#!/usr/bin/env python3
"""
AEMPS Spain Proxy — NexVigilant Station

Domain: www.aemps.gob.es
Tools: 6 (search-fedra-reports, get-nota-informativa-seguridad,
       search-cima-register, get-ficha-tecnica, get-aemps-rmp,
       get-alertas-farmacologicas)

AEMPS (Agencia Española de Medicamentos y Productos Sanitarios) does not
expose a public REST API for FEDRA or regulatory communications. CIMA
(authorised medicines register) has a public HTML search but no stable
JSON API. All tools return structured reference responses with direct URLs.

Usage:
    echo '{"tool": "get-ficha-tecnica", "args": {"drug_name": "metformin"}}' | python3 www_aemps_gob_es_proxy.py
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
BASE_URL = "https://www.aemps.gob.es"
CIMA_URL = "https://cima.aemps.es"


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _drug(args: dict) -> str:
    return (args.get("drug_name") or args.get("drug") or args.get("query")
            or args.get("name") or args.get("substance") or "").strip()


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def search_fedra_reports(args: dict) -> dict:
    """Search FEDRA adverse reaction reports (Spanish pharmacovigilance)."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "AEMPS — FEDRA (Sistema Español de Farmacovigilancia)",
        "drug": drug,
        "resources": [
            {
                "name": "FEDRA System Overview",
                "url": f"{BASE_URL}/la-aemps/que-hacemos/farmacovigilancia/",
            },
            {
                "name": "Pharmacovigilance Reporting",
                "url": f"{BASE_URL}/la-aemps/que-hacemos/farmacovigilancia/notificacion/",
            },
            {
                "name": "AEMPS Search",
                "url": f"{BASE_URL}/buscador/?searchText={_quote(drug)}",
            },
        ],
        "note": "FEDRA aggregates ADR reports from the Spanish Pharmacovigilance System. Individual case data is not publicly searchable; aggregate reports appear in periodic safety bulletins.",
    }


def get_nota_informativa_seguridad(args: dict) -> dict:
    """Get AEMPS Notas Informativas de Seguridad (safety information notes)."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "AEMPS — Notas Informativas de Seguridad",
        "drug": drug,
        "resources": [
            {
                "name": "Safety Information Notes (MUH)",
                "url": f"{BASE_URL}/informa-de/seguridad-de-medicamentos/notas-informativas/",
            },
            {
                "name": "Search Safety Notes",
                "url": f"{BASE_URL}/buscador/?searchText={_quote(drug)}+nota+seguridad",
            },
        ],
        "note": "Notas Informativas de Seguridad are Spanish regulatory safety communications. AEMPS publishes both MUH (human medicines) and MVET (veterinary) notices.",
    }


def search_cima_register(args: dict) -> dict:
    """Search CIMA — Spanish authorised medicines register."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "AEMPS — CIMA (Centro de Información Online de Medicamentos)",
        "drug": drug,
        "resources": [
            {
                "name": "CIMA Search",
                "url": f"{CIMA_URL}/cima/publico/lista.html?nombre={_quote(drug)}",
            },
            {
                "name": "CIMA Home",
                "url": f"{CIMA_URL}/",
            },
        ],
        "note": "CIMA is the public Spanish authorised medicines register. Search returns product name, authorisation holder, presentation, and links to Ficha Técnica (SmPC) and Prospecto (patient leaflet).",
    }


def get_ficha_tecnica(args: dict) -> dict:
    """Get Ficha Técnica (Spanish SmPC) and Prospecto (patient leaflet)."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "AEMPS — CIMA Ficha Técnica",
        "drug": drug,
        "resources": [
            {
                "name": "Ficha Técnica Search (CIMA)",
                "url": f"{CIMA_URL}/cima/publico/lista.html?nombre={_quote(drug)}",
            },
            {
                "name": "Direct PDF pattern",
                "url": f"{CIMA_URL}/cima/dochtml/ft/{{registration_number}}/FichaTecnica_{{registration_number}}.html",
                "note": "Replace {registration_number} with Spanish national authorisation number from CIMA search.",
            },
        ],
        "note": "Ficha Técnica is the Spanish equivalent of SmPC; Prospecto is the patient information leaflet. Both available as HTML and PDF from CIMA, keyed by Spanish registration number.",
    }


def get_aemps_rmp(args: dict) -> dict:
    """Get Spain-specific Risk Management Plan additional measures."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "AEMPS — Spain-specific Risk Management Plan",
        "drug": drug,
        "resources": [
            {
                "name": "AEMPS Risk Management",
                "url": f"{BASE_URL}/informa-de/seguridad-de-medicamentos/",
            },
            {
                "name": "Centralised EMA RMP (primary)",
                "url": "https://www.ema.europa.eu/en/medicines",
                "note": "For EMA-centralised products, the EMA RMP applies with Spain-specific additional measures layered on top.",
            },
        ],
        "note": "Spain implements EMA centralised RMPs and may add national additional risk minimisation measures (e.g., prescriber education programs, controlled distribution). National RMP elements are published in Notas Informativas when updated.",
    }


def get_alertas_farmacologicas(args: dict) -> dict:
    """Get AEMPS alertas farmacológicas (urgent safety communications and recalls)."""
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "AEMPS — Alertas Farmacológicas",
        "drug": drug,
        "resources": [
            {
                "name": "Alertas Farmacológicas",
                "url": f"{BASE_URL}/informa-de/defectos-de-calidad-y-recalls/alertas-y-retiradas-calidad/",
            },
            {
                "name": "Search Alerts",
                "url": f"{BASE_URL}/buscador/?searchText={_quote(drug)}+alerta",
            },
        ],
        "note": "Alertas Farmacológicas cover urgent quality defects, recalls, and safety communications. Classified by severity (Class I, II, III) following international recall conventions.",
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

DISPATCH = {
    "search-fedra-reports": search_fedra_reports,
    "get-nota-informativa-seguridad": get_nota_informativa_seguridad,
    "search-cima-register": search_cima_register,
    "get-ficha-tecnica": get_ficha_tecnica,
    "get-aemps-rmp": get_aemps_rmp,
    "get-alertas-farmacologicas": get_alertas_farmacologicas,
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
