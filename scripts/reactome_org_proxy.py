#!/usr/bin/env python3
"""
Reactome Biological Pathways Proxy — NexVigilant Station

Domain: reactome.org
Base URL: https://reactome.org/ContentService

Reads JSON from stdin, dispatches to handler, writes JSON to stdout.
No external dependencies — stdlib only.
"""

import json
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

BASE_URL = "https://reactome.org/ContentService"
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


def search_pathways(args: dict) -> dict:
    """Handler for search-pathways."""
    query = args.get("query", "")
    limit = min(int(args.get("limit", 10)), 100)
    url = f"{BASE_URL}/search/query?query={_quote(query)}&species=Homo%20sapiens&types=Pathway&cluster=true"
    data = _fetch(url)
    results_list = data.get("results", [])
    results = []
    for group in results_list:
        for entry in group.get("entries", [])[:limit]:
            results.append({
                "stable_id": entry.get("stId", ""),
                "name": entry.get("name", ""),
                "species": entry.get("species", ""),
                "exact_type": entry.get("exactType", ""),
            })
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break
    return {"status": "ok", "count": len(results), "results": results}


def get_pathway(args: dict) -> dict:
    """Handler for get-pathway."""
    pathway_id = args.get("pathway_id", "").strip()
    url = f"{BASE_URL}/data/query/{_quote(pathway_id)}"
    data = _fetch(url)
    return {
        "status": "ok",
        "stable_id": data.get("stId", ""),
        "name": data.get("displayName", ""),
        "species": (data.get("speciesName") or ""),
        "is_disease": data.get("isInDisease", False),
        "is_inferred": data.get("isInferred", False),
        "has_diagram": data.get("hasDiagram", False),
        "schema_class": data.get("schemaClass", ""),
    }


def get_pathway_participants(args: dict) -> dict:
    """Handler for get-pathway-participants."""
    pathway_id = args.get("pathway_id", "").strip()
    url = f"{BASE_URL}/data/participants/{_quote(pathway_id)}"
    data = _fetch(url)
    results = []
    items = data if isinstance(data, list) else []
    for item in items[:50]:
        results.append({
            "stable_id": item.get("stId", ""),
            "name": item.get("displayName", ""),
            "schema_class": item.get("schemaClass", ""),
        })
    return {"status": "ok", "pathway_id": pathway_id, "count": len(results), "results": results}


def get_disease_pathways(args: dict) -> dict:
    """Handler for get-disease-pathways."""
    disease = args.get("disease", "").strip()
    url = f"{BASE_URL}/search/query?query={_quote(disease)}&species=Homo%20sapiens&types=Pathway&cluster=true"
    data = _fetch(url)
    results_list = data.get("results", [])
    results = []
    for group in results_list:
        for entry in group.get("entries", [])[:25]:
            results.append({
                "stable_id": entry.get("stId", ""),
                "name": entry.get("name", ""),
                "species": entry.get("species", ""),
            })
    return {"status": "ok", "query": disease, "count": len(results), "results": results}


def search_reactions(args: dict) -> dict:
    """Handler for search-reactions."""
    query = args.get("query", "")
    limit = min(int(args.get("limit", 10)), 100)
    url = f"{BASE_URL}/search/query?query={_quote(query)}&species=Homo%20sapiens&types=Reaction&cluster=true"
    data = _fetch(url)
    results_list = data.get("results", [])
    results = []
    for group in results_list:
        for entry in group.get("entries", [])[:limit]:
            results.append({
                "stable_id": entry.get("stId", ""),
                "name": entry.get("name", ""),
                "species": entry.get("species", ""),
                "exact_type": entry.get("exactType", ""),
            })
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break
    return {"status": "ok", "count": len(results), "results": results}


def get_drug_pathway_targets(args: dict) -> dict:
    """Handler for get-drug-pathway-targets."""
    drug_name = args.get("drug_name", "").strip()
    url = f"{BASE_URL}/search/query?query={_quote(drug_name)}&species=Homo%20sapiens&cluster=true"
    data = _fetch(url)
    results_list = data.get("results", [])
    results = []
    for group in results_list:
        for entry in group.get("entries", [])[:25]:
            results.append({
                "stable_id": entry.get("stId", ""),
                "name": entry.get("name", ""),
                "exact_type": entry.get("exactType", ""),
            })
    return {"status": "ok", "drug_name": drug_name, "count": len(results), "results": results}



# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

DISPATCH = {
    "search-pathways": search_pathways,
    "get-pathway": get_pathway,
    "get-pathway-participants": get_pathway_participants,
    "get-disease-pathways": get_disease_pathways,
    "search-reactions": search_reactions,
    "get-drug-pathway-targets": get_drug_pathway_targets,
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
