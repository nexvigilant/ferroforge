#!/usr/bin/env python3
"""
UniProt Protein Knowledge Base Proxy — NexVigilant Station

Domain: rest.uniprot.org
Base URL: https://rest.uniprot.org

Reads JSON from stdin, dispatches to handler, writes JSON to stdout.
No external dependencies — stdlib only.
"""

import json
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

BASE_URL = "https://rest.uniprot.org"
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


def search_proteins(args: dict) -> dict:
    """Handler for search-proteins."""
    query = args.get("query", "")
    limit = min(int(args.get("limit", 10)), 100)
    url = f"{BASE_URL}/uniprotkb/search?query={_quote(query)}&format=json&size={limit}&fields=accession,id,protein_name,gene_names,organism_name,length"
    data = _fetch(url)
    results = []
    for entry in data.get("results", [])[:limit]:
        protein_name = ""
        pn = entry.get("proteinDescription", {})
        rec = pn.get("recommendedName") or {}
        if rec.get("fullName"):
            protein_name = rec["fullName"].get("value", "")
        genes = [g.get("geneName", {}).get("value", "") for g in (entry.get("genes") or [])]
        results.append({
            "accession": entry.get("primaryAccession", ""),
            "entry_name": entry.get("uniProtkbId", ""),
            "protein_name": protein_name,
            "genes": genes,
            "organism": entry.get("organism", {}).get("scientificName", ""),
            "length": entry.get("sequence", {}).get("length", 0),
        })
    return {"status": "ok", "count": len(results), "results": results}


def get_protein(args: dict) -> dict:
    """Handler for get-protein."""
    accession = args.get("accession", "").strip()
    url = f"{BASE_URL}/uniprotkb/{_quote(accession)}.json"
    data = _fetch(url)
    protein_name = ""
    pn = data.get("proteinDescription", {})
    rec = pn.get("recommendedName") or {}
    if rec.get("fullName"):
        protein_name = rec["fullName"].get("value", "")
    genes = [g.get("geneName", {}).get("value", "") for g in (data.get("genes") or [])]
    function_texts = []
    for comment in (data.get("comments") or []):
        if comment.get("commentType") == "FUNCTION":
            for t in (comment.get("texts") or []):
                function_texts.append(t.get("value", "")[:500])
    subcell = []
    for comment in (data.get("comments") or []):
        if comment.get("commentType") == "SUBCELLULAR LOCATION":
            for loc in (comment.get("subcellularLocations") or []):
                loc_val = (loc.get("location") or {}).get("value", "")
                if loc_val:
                    subcell.append(loc_val)
    go_terms = []
    for xref in (data.get("uniProtKBCrossReferences") or []):
        if xref.get("database") == "GO":
            props = {p["key"]: p["value"] for p in (xref.get("properties") or [])}
            go_terms.append({"id": xref.get("id", ""), "term": props.get("GoTerm", "")})
    return {
        "status": "ok",
        "accession": data.get("primaryAccession", ""),
        "protein_name": protein_name,
        "genes": genes,
        "organism": data.get("organism", {}).get("scientificName", ""),
        "function": function_texts,
        "subcellular_location": subcell,
        "go_terms": go_terms[:20],
        "length": data.get("sequence", {}).get("length", 0),
    }


def get_protein_variants(args: dict) -> dict:
    """Handler for get-protein-variants."""
    accession = args.get("accession", "").strip()
    url = f"{BASE_URL}/uniprotkb/{_quote(accession)}.json"
    data = _fetch(url)
    variants = []
    for feat in (data.get("features") or []):
        if feat.get("type") in ("Natural variant", "Mutagenesis"):
            desc = ""
            for ev in (feat.get("evidences") or []):
                desc += ev.get("source", {}).get("name", "") + " "
            variants.append({
                "type": feat.get("type", ""),
                "location_start": feat.get("location", {}).get("start", {}).get("value"),
                "location_end": feat.get("location", {}).get("end", {}).get("value"),
                "description": (feat.get("description") or "")[:300],
                "alternativeSequence": feat.get("alternativeSequence", {}),
            })
    return {"status": "ok", "accession": accession, "count": len(variants), "results": variants[:50]}


def get_protein_interactions(args: dict) -> dict:
    """Handler for get-protein-interactions."""
    accession = args.get("accession", "").strip()
    url = f"{BASE_URL}/uniprotkb/{_quote(accession)}.json"
    data = _fetch(url)
    interactions = []
    for comment in (data.get("comments") or []):
        if comment.get("commentType") == "INTERACTION":
            for inter in (comment.get("interactions") or []):
                interactant = inter.get("interactantTwo", {})
                interactions.append({
                    "interactant_accession": interactant.get("uniProtkbAccession", ""),
                    "gene_name": interactant.get("geneName", ""),
                    "experiments": inter.get("numberOfExperiments", 0),
                })
    return {"status": "ok", "accession": accession, "count": len(interactions), "results": interactions}


def get_protein_disease(args: dict) -> dict:
    """Handler for get-protein-disease."""
    accession = args.get("accession", "").strip()
    url = f"{BASE_URL}/uniprotkb/{_quote(accession)}.json"
    data = _fetch(url)
    diseases = []
    for comment in (data.get("comments") or []):
        if comment.get("commentType") == "DISEASE":
            disease = comment.get("disease", {})
            diseases.append({
                "disease_id": disease.get("diseaseId", ""),
                "acronym": disease.get("acronym", ""),
                "description": (disease.get("description") or "")[:500],
                "reference": disease.get("diseaseCrossReference", {}),
            })
    return {"status": "ok", "accession": accession, "count": len(diseases), "results": diseases}


def get_protein_pharmacology(args: dict) -> dict:
    """Handler for get-protein-pharmacology."""
    accession = args.get("accession", "").strip()
    url = f"{BASE_URL}/uniprotkb/{_quote(accession)}.json"
    data = _fetch(url)
    pharma = []
    for comment in (data.get("comments") or []):
        if comment.get("commentType") == "PHARMACEUTICAL":
            for t in (comment.get("texts") or []):
                pharma.append({"text": t.get("value", "")[:500]})
    # Also extract binding sites from features
    binding = []
    for feat in (data.get("features") or []):
        if feat.get("type") == "Binding site":
            binding.append({
                "start": feat.get("location", {}).get("start", {}).get("value"),
                "end": feat.get("location", {}).get("end", {}).get("value"),
                "ligand": (feat.get("ligand") or {}).get("name", ""),
                "description": (feat.get("description") or "")[:300],
            })
    # DrugBank cross-references
    drugbank = []
    for xref in (data.get("uniProtKBCrossReferences") or []):
        if xref.get("database") == "DrugBank":
            props = {p["key"]: p["value"] for p in (xref.get("properties") or [])}
            drugbank.append({"id": xref.get("id", ""), "drug_name": props.get("GenericName", "")})
    return {
        "status": "ok",
        "accession": accession,
        "pharmaceutical": pharma,
        "binding_sites": binding[:20],
        "drugbank_entries": drugbank,
    }



# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

DISPATCH = {
    "search-proteins": search_proteins,
    "get-protein": get_protein,
    "get-protein-variants": get_protein_variants,
    "get-protein-interactions": get_protein_interactions,
    "get-protein-disease": get_protein_disease,
    "get-protein-pharmacology": get_protein_pharmacology,
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
