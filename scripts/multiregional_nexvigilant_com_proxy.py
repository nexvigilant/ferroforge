#!/usr/bin/env python3
"""
Multi-Regional PV Safety Assessment Proxy — NexVigilant Station

Domain: multiregional.nexvigilant.com
Fan-out safety queries across 11 national PV agencies.
Lateral linkage (peer agencies) + horizontal linkage (cross-tier data).
"""

import json
import os
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



sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

AGENCIES = {
    "fda": {"name": "FDA (United States)", "country": "US", "prefix": "api_fda_gov", "tool": "search_adverse_events", "data": ["adverse_events", "labeling", "recalls", "approvals"], "w": 0.22},
    "ema": {"name": "EMA (European Union)", "country": "EU", "prefix": "www_ema_europa_eu", "tool": "search_medicines", "data": ["epar", "signals", "psur", "rmp"], "w": 0.20},
    "pmda": {"name": "PMDA (Japan)", "country": "JP", "prefix": "www_pmda_go_jp", "tool": "search_safety_information", "data": ["safety_info", "adr", "approvals", "rmp"], "w": 0.12},
    "health_canada": {"name": "Health Canada", "country": "CA", "prefix": "recalls_rappels_canada_ca", "tool": "search_recalls", "data": ["recalls", "safety_reviews", "adr", "risk_comms"], "w": 0.10},
    "mhra": {"name": "MHRA (United Kingdom)", "country": "GB", "prefix": "www_gov_uk", "tool": "search_yellow_card_reports", "data": ["yellow_card", "dsu", "alerts", "par"], "w": 0.08},
    "tga": {"name": "TGA (Australia)", "country": "AU", "prefix": "www_tga_gov_au", "tool": "search_daen_reports", "data": ["daen", "alerts", "pi", "recalls"], "w": 0.07},
    "anvisa": {"name": "ANVISA (Brazil)", "country": "BR", "prefix": "anvisa_gov_br", "tool": "search_drug_registry", "data": ["notivisa", "recalls", "alerts"], "w": 0.06},
    "swissmedic": {"name": "Swissmedic (Switzerland)", "country": "CH", "prefix": "www_swissmedic_ch", "tool": "search_safety_signals", "data": ["signals", "auth", "dhpc"], "w": 0.04},
    "hsa": {"name": "HSA (Singapore)", "country": "SG", "prefix": "www_hsa_gov_sg", "tool": "search_adverse_reactions", "data": ["adr", "alerts", "registration"], "w": 0.04},
    "medsafe": {"name": "Medsafe (New Zealand)", "country": "NZ", "prefix": "www_medsafe_govt_nz", "tool": "search_adverse_reactions", "data": ["carm", "prescriber_update", "data_sheets"], "w": 0.04},
    "cofepris": {"name": "COFEPRIS (Mexico)", "country": "MX", "prefix": "cofepris_gob_mx", "tool": "search_drug_registry", "data": ["pv_reports", "recalls", "alerts"], "w": 0.03},
}


def _drug(a: dict) -> str:
    return (a.get("drug_name") or a.get("drug") or a.get("query") or "").strip()


def assess_global_safety(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    event = args.get("event", "")
    agencies = []
    for key, ag in AGENCIES.items():
        tool_name = f"{ag['prefix']}_{ag['tool']}"
        call_args = {"drug_name": drug}
        if event and key == "fda":
            call_args["reaction"] = event
        agencies.append({
            "agency": ag["name"], "country": ag["country"],
            "station_tool": tool_name, "call_with": call_args,
            "data_types": ag["data"], "weight": ag["w"],
        })
    return {
        "status": "ok", "source": "Multi-Regional PV Safety Assessment",
        "drug": drug, "event": event or None, "agencies_count": len(agencies),
        "instruction": "Call each station_tool with call_with params. Score each 0/0.5/1. Compute weighted concordance.",
        "agencies": agencies,
        "global_sources": [
            {"source": "VigiAccess (WHO)", "tool": "vigiaccess_org_search_reports", "call_with": {"medicine": drug}},
            {"source": "OpenVigil", "tool": "open_vigil_fr_compute_disproportionality", "call_with": {"drug": drug, "event": event} if event else {"drug": drug}},
        ],
    }


def compare_regulatory_actions(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    tools = [
        {"agency": "FDA", "tool": "www_fda_gov_get_safety_labeling_changes", "type": "labeling_changes"},
        {"agency": "EMA", "tool": "www_ema_europa_eu_get_safety_signals", "type": "safety_signals"},
        {"agency": "Health Canada", "tool": "recalls_rappels_canada_ca_get_risk_communications", "type": "risk_communications"},
        {"agency": "MHRA", "tool": "www_gov_uk_get_drug_safety_updates", "type": "drug_safety_updates"},
        {"agency": "PMDA", "tool": "www_pmda_go_jp_search_safety_information", "type": "safety_information"},
        {"agency": "TGA", "tool": "www_tga_gov_au_get_safety_alerts", "type": "safety_alerts"},
        {"agency": "Swissmedic", "tool": "www_swissmedic_ch_get_dhpc_letters", "type": "dhpc"},
        {"agency": "ANVISA", "tool": "anvisa_gov_br_get_safety_alerts", "type": "safety_alerts"},
    ]
    return {
        "status": "ok", "source": "Cross-Jurisdictional Regulatory Action Comparison",
        "drug": drug,
        "tools_to_call": [{"agency": t["agency"], "tool": t["tool"], "call_with": {"drug_name": drug}, "action_type": t["type"]} for t in tools],
        "analysis": {"temporal": "Which agency acted first?", "scope": "Same action or divergent?", "severity": "Any escalation beyond peers?"},
    }


def map_signal_propagation(args: dict) -> dict:
    drug = _drug(args)
    event = args.get("event", "")
    if not drug or not event:
        return {"status": "error", "message": "Both drug_name and event are required"}
    return {
        "status": "ok", "source": "Signal Propagation Map", "drug": drug, "event": event,
        "phases": [
            {"phase": "1_detection", "desc": "Initial signal in spontaneous DBs", "tools": [
                {"src": "FAERS", "tool": "api_fda_gov_search_adverse_events", "args": {"drug_name": drug, "reaction": event}},
                {"src": "EudraVigilance", "tool": "eudravigilance_ema_europa_eu_search_reports", "args": {"drug": drug}},
                {"src": "VigiAccess", "tool": "vigiaccess_org_search_reports", "args": {"medicine": drug}},
            ]},
            {"phase": "2_validation", "desc": "Disproportionality + literature", "tools": [
                {"src": "PRR", "tool": "calculate_nexvigilant_com_compute_prr"},
                {"src": "OpenVigil", "tool": "open_vigil_fr_compute_disproportionality", "args": {"drug": drug, "event": event}},
                {"src": "PubMed", "tool": "pubmed_ncbi_nlm_nih_gov_search_signal_literature", "args": {"query": f"{drug} {event}"}},
            ]},
            {"phase": "3_regulatory", "desc": "Per-agency regulatory response", "tools": [
                {"src": "FDA", "tool": "www_fda_gov_get_safety_labeling_changes", "args": {"drug_name": drug}},
                {"src": "EMA", "tool": "www_ema_europa_eu_get_safety_signals", "args": {"drug_name": drug}},
                {"src": "Health Canada", "tool": "recalls_rappels_canada_ca_get_risk_communications", "args": {"drug_name": drug}},
                {"src": "MHRA", "tool": "www_gov_uk_get_drug_safety_updates", "args": {"drug_name": drug}},
                {"src": "PMDA", "tool": "www_pmda_go_jp_search_safety_information", "args": {"drug_name": drug}},
                {"src": "TGA", "tool": "www_tga_gov_au_get_safety_alerts", "args": {"drug_name": drug}},
            ]},
            {"phase": "4_labeling", "desc": "Product information convergence", "tools": [
                {"src": "US label", "tool": "dailymed_nlm_nih_gov_get_adverse_reactions", "args": {"drug_name": drug}},
                {"src": "EU SmPC", "tool": "www_ema_europa_eu_get_epar", "args": {"drug_name": drug}},
                {"src": "NZ data sheet", "tool": "www_medsafe_govt_nz_get_data_sheet", "args": {"drug_name": drug}},
            ]},
        ],
    }


def get_regional_coverage(args: dict) -> dict:
    drug = _drug(args)
    if not drug:
        return {"status": "error", "message": "drug_name is required"}
    return {
        "status": "ok", "source": "Regional Coverage Map", "drug": drug,
        "agencies": [{"agency": ag["name"], "country": ag["country"], "check_tool": f"{ag['prefix']}_{ag['tool']}", "data_types": ag["data"]} for ag in AGENCIES.values()],
    }


def compute_global_concordance(args: dict) -> dict:
    drug = _drug(args)
    event = args.get("event", "")
    if not drug or not event:
        return {"status": "error", "message": "Both drug_name and event are required"}
    return {
        "status": "ok", "source": "Global Concordance", "drug": drug, "event": event,
        "weights": {ag["name"]: ag["w"] for ag in AGENCIES.values()},
        "scoring": "per_agency: 1.0=confirmed, 0.5=data_exists_inconclusive, 0.0=no_data",
        "formula": "concordance = sum(w_i * score_i) / sum(w_i for agencies with data)",
        "thresholds": {"strong": ">=0.70", "moderate": "0.40-0.69", "weak": "0.20-0.39", "insufficient": "<0.20"},
        "steps": ["1. assess-global-safety", "2. call each agency tool", "3. score 0/0.5/1", "4. apply weights", "5. threshold"],
    }


DISPATCH = {
    "assess-global-safety": assess_global_safety,
    "compare-regulatory-actions": compare_regulatory_actions,
    "map-signal-propagation": map_signal_propagation,
    "get-regional-coverage": get_regional_coverage,
    "compute-global-concordance": compute_global_concordance,
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
        print(json.dumps({"status": "error", "message": f"Unknown '{tool}'"}))
        return
    try:
        print(json.dumps(h(args)))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))


if __name__ == "__main__":
    main()
