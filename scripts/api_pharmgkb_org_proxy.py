#!/usr/bin/env python3
"""
PharmGKB Pharmacogenomics Proxy — NexVigilant Station

Domain: api.pharmgkb.org
Base URL: https://api.pharmgkb.org/v1/data

Reads JSON from stdin, dispatches to handler, writes JSON to stdout.
No external dependencies — stdlib only.
"""

import json
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

BASE_URL = "https://api.pharmgkb.org/v1/data"
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


def search_drugs(args: dict) -> dict:
    """Handler for search-drugs."""
    query = args.get("query", "")
    limit = min(int(args.get("limit", 10)), 100)
    url = f"{BASE_URL}/chemical?view=min&name={_quote(query)}"
    data = _fetch(url)
    items = data.get("data", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    results = []
    for item in items[:limit]:
        results.append({
            "pharmgkb_id": item.get("id", ""),
            "name": item.get("name", ""),
            "generic_names": item.get("genericNames", []),
            "trade_names": (item.get("tradeNames") or [])[:5],
            "types": item.get("types", []),
            "cross_references": [xr.get("resource", "") + ":" + xr.get("resourceId", "") for xr in (item.get("crossReferences") or [])[:5]],
        })
    return {"status": "ok", "count": len(results), "results": results}


def get_drug_labels(args: dict) -> dict:
    """Handler for get-drug-labels."""
    drug_name = _resolve_drug(args)
    url = f"{BASE_URL}/label?view=min&relatedChemicals.name={_quote(drug_name)}"
    data = _fetch(url)
    items = data.get("data", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    results = []
    for item in items[:20]:
        results.append({
            "label_id": item.get("id", ""),
            "name": item.get("name", ""),
            "source": item.get("source", ""),
            "testing_level": item.get("testingLevel", ""),
            "prescribing_markdown": (item.get("prescribingMarkdown") or "")[:500],
        })
    return {"status": "ok", "drug_name": drug_name, "count": len(results), "results": results}


def get_drug_genes(args: dict) -> dict:
    """Handler for get-drug-genes."""
    drug_name = _resolve_drug(args)
    url = f"{BASE_URL}/relationship?view=min&entity1.name={_quote(drug_name)}&entity2Type=Gene"
    data = _fetch(url)
    items = data.get("data", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    results = []
    for item in items[:30]:
        entity2 = item.get("entity2", {})
        results.append({
            "gene_id": entity2.get("id", ""),
            "gene_name": entity2.get("name", ""),
            "types": item.get("types", []),
            "evidence_count": item.get("evidenceCount", 0),
        })
    return {"status": "ok", "drug_name": drug_name, "count": len(results), "results": results}


def get_clinical_annotations(args: dict) -> dict:
    """Handler for get-clinical-annotations."""
    gene = args.get("gene", "").strip()
    drug_name = args.get("drug_name", "").strip()
    url = f"{BASE_URL}/clinicalAnnotation?view=min&relatedGenes.symbol={_quote(gene)}"
    if drug_name:
        url += f"&relatedChemicals.name={_quote(drug_name)}"
    data = _fetch(url)
    items = data.get("data", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    results = []
    for item in items[:25]:
        results.append({
            "annotation_id": item.get("id", ""),
            "level_of_evidence": item.get("levelOfEvidence", ""),
            "phenotype_category": item.get("phenotypeCategory", ""),
            "chemicals": [c.get("name", "") for c in (item.get("relatedChemicals") or [])],
            "genes": [g.get("symbol", "") for g in (item.get("relatedGenes") or [])],
        })
    return {"status": "ok", "gene": gene, "count": len(results), "results": results}


def get_dosing_guidelines(args: dict) -> dict:
    """Handler for get-dosing-guidelines."""
    drug_name = _resolve_drug(args)
    url = f"{BASE_URL}/guideline?view=min&relatedChemicals.name={_quote(drug_name)}"
    data = _fetch(url)
    items = data.get("data", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    results = []
    for item in items[:20]:
        results.append({
            "guideline_id": item.get("id", ""),
            "name": item.get("name", ""),
            "source": item.get("source", ""),
            "summary_markdown": (item.get("summaryMarkdown") or "")[:500],
            "chemicals": [c.get("name", "") for c in (item.get("relatedChemicals") or [])],
            "genes": [g.get("symbol", "") for g in (item.get("relatedGenes") or [])],
        })
    return {"status": "ok", "drug_name": drug_name, "count": len(results), "results": results}


def search_variants(args: dict) -> dict:
    """Handler for search-variants."""
    query = args.get("query", "")
    limit = min(int(args.get("limit", 10)), 100)
    url = f"{BASE_URL}/variant?view=min&symbol={_quote(query)}"
    data = _fetch(url)
    items = data.get("data", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    results = []
    for item in items[:limit]:
        results.append({
            "variant_id": item.get("id", ""),
            "name": item.get("name", ""),
            "symbol": item.get("symbol", ""),
            "genes": [g.get("symbol", "") for g in (item.get("relatedGenes") or [])],
        })
    return {"status": "ok", "count": len(results), "results": results}


def get_variant_annotations(args: dict) -> dict:
    """Handler for get-variant-annotations."""
    variant_id = args.get("variant_id", "").strip()
    url = f"{BASE_URL}/clinicalAnnotation?view=min&location.variantId={_quote(variant_id)}"
    data = _fetch(url)
    items = data.get("data", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    results = []
    for item in items[:25]:
        results.append({
            "annotation_id": item.get("id", ""),
            "level_of_evidence": item.get("levelOfEvidence", ""),
            "phenotype_category": item.get("phenotypeCategory", ""),
            "chemicals": [c.get("name", "") for c in (item.get("relatedChemicals") or [])],
            "genes": [g.get("symbol", "") for g in (item.get("relatedGenes") or [])],
        })
    return {"status": "ok", "variant_id": variant_id, "count": len(results), "results": results}



# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

DISPATCH = {
    "search-drugs": search_drugs,
    "get-drug-labels": get_drug_labels,
    "get-drug-genes": get_drug_genes,
    "get-clinical-annotations": get_clinical_annotations,
    "get-dosing-guidelines": get_dosing_guidelines,
    "search-variants": search_variants,
    "get-variant-annotations": get_variant_annotations,
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
