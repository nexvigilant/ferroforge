#!/usr/bin/env python3
"""
Comparative Toxicogenomics Database (CTD) Proxy — NexVigilant Station

Domain: ctdbase.org
Tools: 6 (search-chemical-gene, get-chemical-diseases, search-chemical-pathways,
       get-gene-disease, get-exposure-outcomes, search-phenotypes)

CTD has added captcha verification to its batch query API (as of 2026).
All tools return structured reference responses with direct URLs to CTD
query pages. When captcha is removed, switch back to live TSV parsing.
"""

import json
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



USER_AGENT = "NexVigilant-Station/1.0 (station@nexvigilant.com)"
BASE_URL = "https://ctdbase.org"


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _chemical(args: dict) -> str:
    return (args.get("chemical") or args.get("drug_name") or args.get("drug")
            or args.get("query") or args.get("name") or args.get("substance") or "").strip()


def _gene(args: dict) -> str:
    return (args.get("gene") or args.get("gene_symbol") or args.get("query") or "").strip()


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def search_chemical_gene(args: dict) -> dict:
    """Search curated chemical-gene interactions in CTD."""
    chem = _chemical(args)
    if not chem:
        return {"status": "error", "message": "Missing required parameter: chemical or drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "CTD — Chemical-Gene Interactions",
        "chemical": chem,
        "resources": [
            {
                "name": "Chemical-Gene Interactions",
                "url": f"{BASE_URL}/detail.go?type=chem&acc=auto&view=ixn&inputTerms={_q(chem)}",
            },
            {
                "name": "Batch Query (genes_curated)",
                "url": f"{BASE_URL}/tools/batchQuery.go?inputType=chem&inputTerms={_q(chem)}&report=genes_curated&format=tsv",
                "note": "Requires captcha verification in browser as of 2026.",
            },
        ],
        "note": f"CTD curates chemical-gene/protein interactions from the literature. Search '{chem}' to see genes affected by this chemical, interaction types, and supporting publications.",
    }


def get_chemical_diseases(args: dict) -> dict:
    """Get curated chemical-disease associations from CTD."""
    chem = _chemical(args)
    if not chem:
        return {"status": "error", "message": "Missing required parameter: chemical or drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "CTD — Chemical-Disease Associations",
        "chemical": chem,
        "resources": [
            {
                "name": "Chemical-Disease Associations",
                "url": f"{BASE_URL}/detail.go?type=chem&acc=auto&view=disease&inputTerms={_q(chem)}",
            },
            {
                "name": "Batch Query (diseases_curated)",
                "url": f"{BASE_URL}/tools/batchQuery.go?inputType=chem&inputTerms={_q(chem)}&report=diseases_curated&format=tsv",
                "note": "Requires captcha verification in browser.",
            },
        ],
        "note": f"CTD provides curated and inferred chemical-disease associations. Includes therapeutic and toxicological relationships with evidence from the literature.",
    }


def search_chemical_pathways(args: dict) -> dict:
    """Search enriched pathways for a chemical in CTD."""
    chem = _chemical(args)
    if not chem:
        return {"status": "error", "message": "Missing required parameter: chemical or drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "CTD — Enriched Pathways",
        "chemical": chem,
        "resources": [
            {
                "name": "Chemical-Pathway Enrichment",
                "url": f"{BASE_URL}/detail.go?type=chem&acc=auto&view=pathway&inputTerms={_q(chem)}",
            },
            {
                "name": "Batch Query (pathways_enriched)",
                "url": f"{BASE_URL}/tools/batchQuery.go?inputType=chem&inputTerms={_q(chem)}&report=pathways_enriched&format=tsv",
                "note": "Requires captcha verification in browser.",
            },
        ],
        "note": f"CTD computes statistically enriched pathways based on the set of genes that interact with a chemical. Includes KEGG and Reactome pathways.",
    }


def get_gene_disease(args: dict) -> dict:
    """Get curated gene-disease associations from CTD."""
    gene = _gene(args)
    if not gene:
        return {"status": "error", "message": "Missing required parameter: gene or gene_symbol"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "CTD — Gene-Disease Associations",
        "gene": gene,
        "resources": [
            {
                "name": "Gene-Disease Associations",
                "url": f"{BASE_URL}/detail.go?type=gene&acc=auto&view=disease&inputTerms={_q(gene)}",
            },
            {
                "name": "Batch Query (diseases_curated)",
                "url": f"{BASE_URL}/tools/batchQuery.go?inputType=gene&inputTerms={_q(gene)}&report=diseases_curated&format=tsv",
                "note": "Requires captcha verification in browser.",
            },
        ],
        "note": f"CTD curates gene-disease relationships from the literature. Includes both direct evidence and inferred associations via shared chemicals.",
    }


def get_exposure_outcomes(args: dict) -> dict:
    """Get exposure-disease/phenotype outcome associations for a chemical."""
    chem = _chemical(args)
    if not chem:
        return {"status": "error", "message": "Missing required parameter: chemical or drug_name"}
    return {
        "status": "ok",
        "type": "reference",
        "source": "CTD — Exposure Studies",
        "chemical": chem,
        "resources": [
            {
                "name": "Exposure Studies",
                "url": f"{BASE_URL}/detail.go?type=chem&acc=auto&view=expStudies&inputTerms={_q(chem)}",
            },
            {
                "name": "Chemical Detail Page",
                "url": f"{BASE_URL}/detail.go?type=chem&acc=auto&inputTerms={_q(chem)}",
            },
        ],
        "note": f"CTD curates exposure-outcome associations linking environmental chemicals to diseases and phenotypes in human populations.",
    }


def search_phenotypes(args: dict) -> dict:
    """Search phenotype associations for a chemical or gene in CTD."""
    query = _chemical(args) or _gene(args)
    if not query:
        return {"status": "error", "message": "Missing required parameter: chemical, drug_name, or gene"}
    input_type = "gene" if args.get("gene") else "chem"
    view_type = "phenotype"
    return {
        "status": "ok",
        "type": "reference",
        "source": "CTD — Phenotype Associations",
        "query": query,
        "input_type": input_type,
        "resources": [
            {
                "name": "Phenotype Associations",
                "url": f"{BASE_URL}/detail.go?type={input_type}&acc=auto&view={view_type}&inputTerms={_q(query)}",
            },
            {
                "name": "Batch Query (phenotypes_curated)",
                "url": f"{BASE_URL}/tools/batchQuery.go?inputType={input_type}&inputTerms={_q(query)}&report=phenotypes_curated&format=tsv",
                "note": "Requires captcha verification in browser.",
            },
        ],
        "note": f"CTD curates chemical-phenotype and gene-phenotype associations from the literature, linking molecular perturbations to observable biological outcomes.",
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

DISPATCH = {
    "search-chemical-gene": search_chemical_gene,
    "get-chemical-diseases": get_chemical_diseases,
    "search-chemical-pathways": search_chemical_pathways,
    "get-gene-disease": get_gene_disease,
    "get-exposure-outcomes": get_exposure_outcomes,
    "search-phenotypes": search_phenotypes,
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
