#!/usr/bin/env python3
"""
Open Targets Platform Proxy — NexVigilant Station

Domain: platform-api.opentargets.org
Base URL: https://api.platform.opentargets.org/api/v4

Reads JSON from stdin, dispatches to handler, writes JSON to stdout.
No external dependencies — stdlib only.
"""

import json
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

BASE_URL = "https://api.platform.opentargets.org/api/v4"
GRAPHQL_URL = f"{BASE_URL}/graphql"
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


def _graphql(query: str, variables: dict) -> dict:
    """Execute a GraphQL query against Open Targets."""
    return _post(GRAPHQL_URL, {"query": query, "variables": variables})


def search_targets(args: dict) -> dict:
    """Handler for search-targets."""
    query = args.get("query", "")
    limit = min(int(args.get("limit", 10)), 100)
    gql = """
    query SearchTargets($q: String!, $size: Int!) {
      search(queryString: $q, entityNames: ["target"], page: {size: $size, index: 0}) {
        total
        hits { id name entity description }
      }
    }
    """
    data = _graphql(gql, {"q": query, "size": limit})
    search = data.get("data", {}).get("search", {})
    results = []
    for hit in search.get("hits", []):
        results.append({
            "target_id": hit.get("id", ""),
            "name": hit.get("name", ""),
            "description": (hit.get("description") or "")[:500],
        })
    return {"status": "ok", "total": search.get("total", 0), "count": len(results), "results": results}


def search_diseases(args: dict) -> dict:
    """Handler for search-diseases."""
    query = args.get("query", "")
    limit = min(int(args.get("limit", 10)), 100)
    gql = """
    query SearchDiseases($q: String!, $size: Int!) {
      search(queryString: $q, entityNames: ["disease"], page: {size: $size, index: 0}) {
        total
        hits { id name entity description }
      }
    }
    """
    data = _graphql(gql, {"q": query, "size": limit})
    search = data.get("data", {}).get("search", {})
    results = []
    for hit in search.get("hits", []):
        results.append({
            "disease_id": hit.get("id", ""),
            "name": hit.get("name", ""),
            "description": (hit.get("description") or "")[:500],
        })
    return {"status": "ok", "total": search.get("total", 0), "count": len(results), "results": results}


def get_associations(args: dict) -> dict:
    """Handler for get-associations."""
    target_id = args.get("target_id", "").strip()
    limit = min(int(args.get("limit", 25)), 100)
    gql = """
    query GetAssociations($id: String!, $size: Int!) {
      target(ensemblId: $id) {
        id approvedSymbol approvedName
        associatedDiseases(page: {size: $size, index: 0}) {
          count
          rows { disease { id name } score datatypeScores { id score } }
        }
      }
    }
    """
    data = _graphql(gql, {"id": target_id, "size": limit})
    target = data.get("data", {}).get("target", {})
    if not target:
        return {"status": "error", "message": f"Target '{target_id}' not found"}
    assocs = target.get("associatedDiseases", {})
    results = []
    for row in assocs.get("rows", []):
        disease = row.get("disease", {})
        results.append({
            "disease_id": disease.get("id", ""),
            "disease_name": disease.get("name", ""),
            "overall_score": row.get("score", 0),
            "datatype_scores": {s["id"]: s["score"] for s in (row.get("datatypeScores") or [])},
        })
    return {
        "status": "ok",
        "target_id": target.get("id", ""),
        "symbol": target.get("approvedSymbol", ""),
        "total_associations": assocs.get("count", 0),
        "count": len(results),
        "results": results,
    }


def get_drug_evidence(args: dict) -> dict:
    """Handler for get-drug-evidence."""
    target_id = args.get("target_id", "").strip()
    disease_id = args.get("disease_id", "").strip()
    gql = """
    query GetDrugEvidence($ensemblId: String!, $efoId: String!) {
      target(ensemblId: $ensemblId) {
        id approvedSymbol
        knownDrugs(diseaseIds: [$efoId]) {
          count
          rows { drug { id name mechanismOfAction } phase status urls { url niceName } }
        }
      }
    }
    """
    data = _graphql(gql, {"ensemblId": target_id, "efoId": disease_id})
    target = data.get("data", {}).get("target", {})
    if not target:
        return {"status": "error", "message": f"Target '{target_id}' not found"}
    drugs = target.get("knownDrugs", {})
    results = []
    for row in drugs.get("rows", []):
        d = row.get("drug", {})
        results.append({
            "drug_id": d.get("id", ""),
            "drug_name": d.get("name", ""),
            "mechanism": d.get("mechanismOfAction", ""),
            "phase": row.get("phase", 0),
            "status": row.get("status", ""),
        })
    return {"status": "ok", "count": len(results), "results": results}


def get_target_safety(args: dict) -> dict:
    """Handler for get-target-safety."""
    target_id = args.get("target_id", "").strip()
    gql = """
    query GetTargetSafety($id: String!) {
      target(ensemblId: $id) {
        id approvedSymbol approvedName
        safetyLiabilities {
          event { term }
          datasource
          literature
          url
          biosamples { tissueLabel cellLabel }
          effects { direction }
        }
      }
    }
    """
    data = _graphql(gql, {"id": target_id})
    target = data.get("data", {}).get("target", {})
    if not target:
        return {"status": "error", "message": f"Target '{target_id}' not found"}
    liabilities = target.get("safetyLiabilities") or []
    results = []
    for item in liabilities:
        event = item.get("event") or {}
        results.append({
            "event": event.get("term", ""),
            "datasource": item.get("datasource", ""),
            "biosamples": item.get("biosamples", []),
            "effects": item.get("effects", []),
        })
    return {"status": "ok", "symbol": target.get("approvedSymbol", ""), "count": len(results), "results": results}


def get_pharmacogenomics(args: dict) -> dict:
    """Handler for get-pharmacogenomics."""
    target_id = args.get("target_id", "").strip()
    gql = """
    query GetPharmacogenomics($id: String!) {
      target(ensemblId: $id) {
        id approvedSymbol
        pharmacogenomics {
          variantRsId
          genotype
          genotypeAnnotationText
          drugFromSource
          phenotypeText
          pgxCategory
          evidenceLevel
        }
      }
    }
    """
    data = _graphql(gql, {"id": target_id})
    target = data.get("data", {}).get("target", {})
    if not target:
        return {"status": "error", "message": f"Target '{target_id}' not found"}
    pgx = target.get("pharmacogenomics") or []
    results = []
    for item in pgx:
        results.append({
            "variant": item.get("variantRsId", ""),
            "genotype": item.get("genotype", ""),
            "drug": item.get("drugFromSource", ""),
            "phenotype": (item.get("phenotypeText") or "")[:500],
            "category": item.get("pgxCategory", ""),
            "evidence_level": item.get("evidenceLevel", ""),
        })
    return {"status": "ok", "symbol": target.get("approvedSymbol", ""), "count": len(results), "results": results}



# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

DISPATCH = {
    "search-targets": search_targets,
    "search-diseases": search_diseases,
    "get-associations": get_associations,
    "get-drug-evidence": get_drug_evidence,
    "get-target-safety": get_target_safety,
    "get-pharmacogenomics": get_pharmacogenomics,
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
