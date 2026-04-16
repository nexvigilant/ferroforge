#!/usr/bin/env python3
"""
Generic Regional Regulator Proxy — NexVigilant Station

Serves 9 regional pharmaceutical regulators with identical 5-tool signatures:
    search-drug-registry, get-safety-alerts, get-recall-actions,
    get-pharmacovigilance-reports, get-regulatory-classification

Regulators:
    - BPOM Indonesia          (www.pom.go.id)
    - CDSCO India             (www.cdsco.gov.in)
    - FDA Philippines         (www.fda.gov.ph)
    - FDA Thailand            (www.fda.moph.go.th)
    - MFDS Korea              (www.mfds.go.kr)
    - NMPA China              (www.nmpa.gov.cn)
    - Roszdravnadzor Russia   (roszdravnadzor.gov.ru)
    - SAHPRA South Africa     (www.sahpra.org.za)
    - SFDA Saudi Arabia       (www.sfda.gov.sa)
    - TFDA Taiwan             (www.fda.gov.tw)

None of these agencies expose stable public REST APIs for pharmacovigilance
data. All tools return structured reference responses with direct URLs.

Domain context is inferred from the tool name prefix (e.g.,
"www_nmpa_gov_cn_search_drug_registry" → domain "www.nmpa.gov.cn").

Usage:
    echo '{"tool": "www_nmpa_gov_cn_search-drug-registry", "args": {"drug_name": "metformin"}}' | \\
        python3 generic_regulator_proxy.py
"""

import json
import sys
import urllib.parse


def ensure_str(val) -> str:
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


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _drug(args: dict) -> str:
    return (args.get("drug_name") or args.get("drug") or args.get("query")
            or args.get("name") or args.get("substance") or "").strip()


# ---------------------------------------------------------------------------
# Regulator registry: domain → (agency full name, base URL, native terminology)
# ---------------------------------------------------------------------------

REGULATORS = {
    "www.pom.go.id": {
        "agency": "BPOM (Badan Pengawas Obat dan Makanan)",
        "country": "Indonesia",
        "base": "https://www.pom.go.id",
        "registry_path": "/drug-registration",
        "safety_path": "/berita/public-warning",
        "recall_path": "/berita/public-warning",
        "pv_path": "/farmakovigilans",
        "class_path": "/klasifikasi-obat",
        "adr_portal": "https://e-meso.pom.go.id/",
        "notes": "BPOM is the Indonesian National Agency of Drug and Food Control. E-MESO is the online ADR reporting portal.",
    },
    "www.cdsco.gov.in": {
        "agency": "CDSCO (Central Drugs Standard Control Organization)",
        "country": "India",
        "base": "https://cdsco.gov.in",
        "registry_path": "/opencms/opencms/en/Home/",
        "safety_path": "/opencms/opencms/en/Notifications/Alerts/",
        "recall_path": "/opencms/opencms/en/Notifications/Public-Notice/",
        "pv_path": "/opencms/opencms/en/Pharmacovigilance/PvPI/",
        "class_path": "/opencms/opencms/en/Drugs/Schedules/",
        "adr_portal": "https://www.ipc.gov.in/PvPI/pv_home.html",
        "notes": "CDSCO operates under the Indian Ministry of Health. PvPI (Pharmacovigilance Programme of India) runs the national ADR reporting system through the Indian Pharmacopoeia Commission.",
    },
    "www.fda.gov.ph": {
        "agency": "FDA Philippines",
        "country": "Philippines",
        "base": "https://www.fda.gov.ph",
        "registry_path": "/list-of-registered-drugs/",
        "safety_path": "/advisories/",
        "recall_path": "/advisories/",
        "pv_path": "/pharmacovigilance/",
        "class_path": "/regulations/",
        "adr_portal": "https://www.fda.gov.ph/pharmacovigilance-online-reporting/",
        "notes": "Philippine FDA operates under the Department of Health. Pharmacovigilance reporting via online portal or paper form.",
    },
    "www.fda.moph.go.th": {
        "agency": "Thai FDA",
        "country": "Thailand",
        "base": "https://www.fda.moph.go.th",
        "registry_path": "/",
        "safety_path": "/safety-alerts",
        "recall_path": "/recall",
        "pv_path": "/pharmacovigilance",
        "class_path": "/",
        "adr_portal": "https://thaihpvc.fda.moph.go.th/",
        "notes": "Thai FDA operates under the Ministry of Public Health. HPVC (Health Product Vigilance Center) runs the national ADR reporting system.",
    },
    "www.mfds.go.kr": {
        "agency": "MFDS (Ministry of Food and Drug Safety)",
        "country": "South Korea",
        "base": "https://www.mfds.go.kr",
        "registry_path": "/eng/index.do",
        "safety_path": "/eng/brd/m_18/list.do",
        "recall_path": "/eng/brd/m_18/list.do",
        "pv_path": "/eng/index.do",
        "class_path": "/eng/index.do",
        "adr_portal": "https://open.mfds.go.kr/",
        "notes": "MFDS is the Korean drug regulatory authority. Korea Institute of Drug Safety & Risk Management (KIDS) processes ADR reports.",
    },
    "www.nmpa.gov.cn": {
        "agency": "NMPA (National Medical Products Administration)",
        "country": "China",
        "base": "https://www.nmpa.gov.cn",
        "registry_path": "/datasearch/home-index.html",
        "safety_path": "/xxgk/ggtg/ypggtg/",
        "recall_path": "/xxgk/ggtg/ypggtg/",
        "pv_path": "/zhuanti/ypqxgg/",
        "class_path": "/xxgk/fgwj/",
        "adr_portal": "https://www.cdr-adr.org.cn/",
        "notes": "NMPA (formerly CFDA) is the Chinese drug regulator. CDR-ADR (Center for Drug Reevaluation) operates the national ADR database.",
    },
    "roszdravnadzor.gov.ru": {
        "agency": "Roszdravnadzor (Federal Service for Surveillance in Healthcare)",
        "country": "Russia",
        "base": "https://roszdravnadzor.gov.ru",
        "registry_path": "/services/misearch",
        "safety_path": "/drugs/monitpringlp",
        "recall_path": "/drugs/nkip",
        "pv_path": "/drugs/monitpringlp",
        "class_path": "/services/misearch",
        "adr_portal": "https://external.roszdravnadzor.ru/",
        "notes": "Roszdravnadzor is the Russian Federal Service for Surveillance in Healthcare. ARCADe is the automated information system for ADR monitoring.",
    },
    "www.sahpra.org.za": {
        "agency": "SAHPRA (South African Health Products Regulatory Authority)",
        "country": "South Africa",
        "base": "https://www.sahpra.org.za",
        "registry_path": "/approved-products/",
        "safety_path": "/safety-information-and-alerts/",
        "recall_path": "/recalls/",
        "pv_path": "/pharmacovigilance/",
        "class_path": "/scheduling-status/",
        "adr_portal": "https://www.sahpra.org.za/pharmacovigilance/",
        "notes": "SAHPRA is the South African medicines regulator (successor to MCC). National Pharmacovigilance Centre receives ADR reports.",
    },
    "www.sfda.gov.sa": {
        "agency": "SFDA (Saudi Food and Drug Authority)",
        "country": "Saudi Arabia",
        "base": "https://www.sfda.gov.sa",
        "registry_path": "/en/drugs-list",
        "safety_path": "/en/safety-communications",
        "recall_path": "/en/recalls",
        "pv_path": "/en/pharmacovigilance",
        "class_path": "/en/drugs-list",
        "adr_portal": "https://ade.sfda.gov.sa/",
        "notes": "SFDA is the Saudi drug regulator. National Pharmacovigilance Center (NPC) operates the ADE online reporting portal.",
    },
    "www.fda.gov.tw": {
        "agency": "TFDA (Taiwan Food and Drug Administration)",
        "country": "Taiwan",
        "base": "https://www.fda.gov.tw",
        "registry_path": "/ENG/index.aspx",
        "safety_path": "/ENG/newsList.aspx?nodeID=1038",
        "recall_path": "/ENG/newsList.aspx?nodeID=1038",
        "pv_path": "/ENG/index.aspx",
        "class_path": "/ENG/index.aspx",
        "adr_portal": "https://adr.fda.gov.tw/",
        "notes": "TFDA operates under Taiwan's Ministry of Health and Welfare. National ADR Reporting Center processes pharmacovigilance reports.",
    },
}


def _resolve_domain(payload: dict) -> str | None:
    """Infer regulator domain from payload. Accepts explicit 'domain' arg or
    parses the tool prefix when dispatch.py strips the prefix before calling."""
    args = payload.get("arguments", payload.get("args", {}))
    if "domain" in args:
        return args["domain"]
    # Look for __domain injected by router
    if "_domain" in payload:
        return payload["_domain"]
    tool = ensure_str(payload.get("tool", ""))
    # Tool comes in as prefix-stripped or full-qualified.
    # Full form: www_nmpa_gov_cn_search-drug-registry
    # Try matching each known domain
    for dom in REGULATORS:
        prefix = dom.replace(".", "_").replace("-", "_") + "_"
        if tool.startswith(prefix):
            return dom
    return None


# ---------------------------------------------------------------------------
# Tool handlers (domain-parameterised)
# ---------------------------------------------------------------------------

def _reference(domain: str, section: str, drug: str, path_key: str,
               section_title: str, extra_resources: list = None) -> dict:
    reg = REGULATORS.get(domain)
    if not reg:
        return {"status": "error", "message": f"Unknown regulator domain: {domain}"}
    base = reg["base"]
    path = reg.get(path_key, "/")
    resources = [
        {
            "name": f"{section_title} — {reg['agency']}",
            "url": f"{base}{path}",
        },
        {
            "name": f"{reg['agency']} — home",
            "url": base,
        },
    ]
    if reg.get("adr_portal") and "safety" in path_key or "pv" in path_key:
        resources.append({
            "name": "National ADR Reporting Portal",
            "url": reg["adr_portal"],
        })
    if extra_resources:
        resources.extend(extra_resources)
    return {
        "status": "ok",
        "type": "reference",
        "source": f"{reg['agency']} — {section_title}",
        "country": reg["country"],
        "drug": drug,
        "resources": resources,
        "note": reg["notes"],
    }


def search_drug_registry(args: dict, domain: str) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return _reference(domain, "registry", drug, "registry_path", "Drug Registry Search")


def get_safety_alerts(args: dict, domain: str) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return _reference(domain, "safety", drug, "safety_path", "Safety Alerts & Communications")


def get_recall_actions(args: dict, domain: str) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return _reference(domain, "recall", drug, "recall_path", "Recall Actions")


def get_pharmacovigilance_reports(args: dict, domain: str) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return _reference(domain, "pv", drug, "pv_path", "Pharmacovigilance Reports")


def get_regulatory_classification(args: dict, domain: str) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "Missing required parameter: drug_name"}
    return _reference(domain, "class", drug, "class_path", "Regulatory Classification")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

DISPATCH = {
    "search-drug-registry": search_drug_registry,
    "get-safety-alerts": get_safety_alerts,
    "get-recall-actions": get_recall_actions,
    "get-pharmacovigilance-reports": get_pharmacovigilance_reports,
    "get-regulatory-classification": get_regulatory_classification,
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
    domain = _resolve_domain(payload)
    if not domain:
        print(json.dumps({"status": "error",
                          "message": "Could not resolve regulator domain from tool name or args. "
                                     f"Supported: {sorted(REGULATORS)}"}))
        sys.exit(1)
    tool_full = ensure_str(payload.get("tool", "")).strip()
    # Strip domain prefix if present
    prefix = domain.replace(".", "_").replace("-", "_") + "_"
    tool = tool_full[len(prefix):] if tool_full.startswith(prefix) else tool_full
    args = payload.get("arguments", payload.get("args", {}))
    if tool not in DISPATCH:
        print(json.dumps({"status": "error",
                          "message": f"Unknown tool '{tool}'. Available: {', '.join(sorted(DISPATCH))}"}))
        sys.exit(1)
    try:
        result = DISPATCH[tool](args, domain)
    except Exception as exc:
        result = {"status": "error", "message": str(exc)}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
