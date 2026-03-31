#!/usr/bin/env python3
"""
ChEMBL Bioactivity Database Proxy — NexVigilant Station

Domain: www.ebi.ac.uk
Base URL: https://www.ebi.ac.uk/chembl/api/data

Reads JSON from stdin, dispatches to handler, writes JSON to stdout.
No external dependencies — stdlib only.
"""

import json
import sys
import time
import urllib.parse
import urllib.request
import urllib.error


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



BASE_URL = "https://www.ebi.ac.uk/chembl/api/data"
REQUEST_TIMEOUT = 20
_RETRY_CODES = {429, 503}
_MAX_RETRIES = 3


def _fetch(url: str) -> dict:
    """HTTP GET with retry on 429/503."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "NexVigilant-FerroForge/1.0 (ferroforge@nexvigilant.com)"},
    )
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
            raise RuntimeError(f"HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(0.2 * (3 ** attempt))
                last_exc = exc
                continue
            raise RuntimeError(f"Network error: {exc.reason}") from exc
    raise RuntimeError(f"Failed after {_MAX_RETRIES} retries: {last_exc}")


def _post(url: str, payload: dict) -> dict:
    """HTTP POST JSON with retry."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": "NexVigilant-FerroForge/1.0 (ferroforge@nexvigilant.com)",
            "Content-Type": "application/json",
        },
        method="POST",
    )
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
            raise RuntimeError(f"HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(0.2 * (3 ** attempt))
                last_exc = exc
                continue
            raise RuntimeError(f"Network error: {exc.reason}") from exc
    raise RuntimeError(f"Failed after {_MAX_RETRIES} retries: {last_exc}")


def _quote(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


def _resolve_drug(args: dict) -> str:
    """Resolve drug name from any known alias."""
    return (args.get("drug_name") or args.get("drug") or args.get("name")
            or args.get("substance") or args.get("product")
            or args.get("query") or "").strip()


# ---------------------------------------------------------------------------
# Tool handlers — EDIT THESE to wire real API calls
# ---------------------------------------------------------------------------


def search_compounds(args: dict) -> dict:
    """Handler for search-compounds."""
    query = args.get("query", "")
    limit = get_int_param(args, "limit", 10, max_val=100)
    url = f"{BASE_URL}/molecule/search.json?q={_quote(query)}&limit={limit}"
    data = _fetch(url)
    molecules = data.get("molecules", [])
    results = []
    for mol in molecules[:limit]:
        props = mol.get("molecule_properties") or {}
        results.append({
            "chembl_id": mol.get("molecule_chembl_id", ""),
            "pref_name": mol.get("pref_name", ""),
            "molecule_type": mol.get("molecule_type", ""),
            "max_phase": mol.get("max_phase", 0),
            "molecular_formula": props.get("full_molformula", ""),
            "molecular_weight": props.get("full_mwt", ""),
            "smiles": (mol.get("molecule_structures") or {}).get("canonical_smiles", ""),
        })
    return {"status": "ok", "count": len(results), "results": results}


def get_compound(args: dict) -> dict:
    """Handler for get-compound."""
    chembl_id = ensure_str(args.get("chembl_id", "")).strip().upper()
    url = f"{BASE_URL}/molecule/{_quote(chembl_id)}.json"
    mol = _fetch(url)
    props = mol.get("molecule_properties") or {}
    structs = mol.get("molecule_structures") or {}
    return {
        "status": "ok",
        "chembl_id": mol.get("molecule_chembl_id", ""),
        "pref_name": mol.get("pref_name", ""),
        "molecule_type": mol.get("molecule_type", ""),
        "max_phase": mol.get("max_phase", 0),
        "first_approval": mol.get("first_approval"),
        "oral": mol.get("oral", False),
        "parenteral": mol.get("parenteral", False),
        "topical": mol.get("topical", False),
        "molecular_formula": props.get("full_molformula", ""),
        "molecular_weight": props.get("full_mwt", ""),
        "alogp": props.get("alogp", ""),
        "hba": props.get("hba", ""),
        "hbd": props.get("hbd", ""),
        "psa": props.get("psa", ""),
        "ro5_violations": props.get("num_ro5_violations", ""),
        "smiles": structs.get("canonical_smiles", ""),
        "inchi_key": structs.get("standard_inchi_key", ""),
    }


def get_compound_bioactivities(args: dict) -> dict:
    """Handler for get-compound-bioactivities."""
    chembl_id = ensure_str(args.get("chembl_id", "")).strip().upper()
    limit = get_int_param(args, "limit", 25, max_val=100)
    url = f"{BASE_URL}/activity.json?molecule_chembl_id={_quote(chembl_id)}&limit={limit}"
    data = _fetch(url)
    activities = data.get("activities", [])
    results = []
    for act in activities[:limit]:
        results.append({
            "activity_id": act.get("activity_id"),
            "assay_chembl_id": act.get("assay_chembl_id", ""),
            "assay_type": act.get("assay_type", ""),
            "target_chembl_id": act.get("target_chembl_id", ""),
            "target_pref_name": act.get("target_pref_name", ""),
            "standard_type": act.get("standard_type", ""),
            "standard_value": act.get("standard_value", ""),
            "standard_units": act.get("standard_units", ""),
            "standard_relation": act.get("standard_relation", ""),
            "pchembl_value": act.get("pchembl_value", ""),
        })
    return {"status": "ok", "count": len(results), "chembl_id": chembl_id, "results": results}


def get_drug_mechanisms(args: dict) -> dict:
    """Handler for get-drug-mechanisms."""
    chembl_id = ensure_str(args.get("chembl_id", "")).strip().upper()
    url = f"{BASE_URL}/mechanism.json?molecule_chembl_id={_quote(chembl_id)}"
    data = _fetch(url)
    mechanisms = data.get("mechanisms", [])
    results = []
    for mech in mechanisms:
        results.append({
            "mechanism_of_action": mech.get("mechanism_of_action", ""),
            "action_type": mech.get("action_type", ""),
            "target_chembl_id": mech.get("target_chembl_id", ""),
            "target_name": mech.get("target_name", ""),
            "disease_efficacy": mech.get("disease_efficacy", False),
            "max_phase": mech.get("max_phase", 0),
        })
    return {"status": "ok", "count": len(results), "chembl_id": chembl_id, "results": results}


def search_targets(args: dict) -> dict:
    """Handler for search-targets."""
    query = args.get("query", "")
    limit = get_int_param(args, "limit", 10, max_val=100)
    url = f"{BASE_URL}/target/search.json?q={_quote(query)}&limit={limit}"
    data = _fetch(url)
    targets = data.get("targets", [])
    results = []
    for tgt in targets[:limit]:
        results.append({
            "target_chembl_id": tgt.get("target_chembl_id", ""),
            "pref_name": tgt.get("pref_name", ""),
            "target_type": tgt.get("target_type", ""),
            "organism": tgt.get("organism", ""),
            "species_group_flag": tgt.get("species_group_flag", False),
        })
    return {"status": "ok", "count": len(results), "results": results}


def get_target(args: dict) -> dict:
    """Handler for get-target."""
    chembl_id = ensure_str(args.get("chembl_id", "")).strip().upper()
    url = f"{BASE_URL}/target/{_quote(chembl_id)}.json"
    tgt = _fetch(url)
    components = []
    for comp in (tgt.get("target_components") or []):
        components.append({
            "component_id": comp.get("component_id"),
            "component_type": comp.get("component_type", ""),
            "accession": comp.get("accession", ""),
        })
    return {
        "status": "ok",
        "target_chembl_id": tgt.get("target_chembl_id", ""),
        "pref_name": tgt.get("pref_name", ""),
        "target_type": tgt.get("target_type", ""),
        "organism": tgt.get("organism", ""),
        "components": components,
    }


def get_drug_indications(args: dict) -> dict:
    """Handler for get-drug-indications."""
    chembl_id = ensure_str(args.get("chembl_id", "")).strip().upper()
    url = f"{BASE_URL}/drug_indication.json?molecule_chembl_id={_quote(chembl_id)}"
    data = _fetch(url)
    indications = data.get("drug_indications", [])
    results = []
    for ind in indications:
        results.append({
            "mesh_heading": ind.get("mesh_heading", ""),
            "mesh_id": ind.get("mesh_id", ""),
            "max_phase_for_ind": ind.get("max_phase_for_ind", 0),
            "efo_term": ind.get("efo_term", ""),
            "efo_id": ind.get("efo_id", ""),
        })
    return {"status": "ok", "count": len(results), "chembl_id": chembl_id, "results": results}



# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

DISPATCH = {
    "search-compounds": search_compounds,
    "get-compound": get_compound,
    "get-compound-bioactivities": get_compound_bioactivities,
    "get-drug-mechanisms": get_drug_mechanisms,
    "search-targets": search_targets,
    "get-target": get_target,
    "get-drug-indications": get_drug_indications,
}


def main():
    try:
        raw = sys.stdin.read()
        envelope = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        json.dump({"status": "error", "message": f"Invalid JSON: {exc}"}, sys.stdout)
        return

    tool = envelope.get("tool", "")
    args = envelope.get("arguments", envelope.get("args", {}))

    handler = DISPATCH.get(tool)
    if not handler:
        json.dump({"status": "error", "message": f"Unknown tool: {tool}"}, sys.stdout)
        return

    try:
        result = handler(args)
        json.dump(result, sys.stdout)
    except Exception as exc:
        json.dump({"status": "error", "message": str(exc)}, sys.stdout)


if __name__ == "__main__":
    main()
