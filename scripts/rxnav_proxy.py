#!/usr/bin/env python3
"""
RxNav Drug Nomenclature Proxy — routes MoltBrowser hub tool calls to rxnav.nlm.nih.gov.

Usage:
    echo '{"tool": "get-rxcui", "args": {"drug_name": "aspirin"}}' | python3 rxnav_proxy.py
    echo '{"tool": "search-drugs", "args": {"query": "metformin", "max_entries": 5}}' | python3 rxnav_proxy.py
    echo '{"tool": "get-interactions", "args": {"rxcuis": "1049502+1049504"}}' | python3 rxnav_proxy.py
    echo '{"tool": "get-ingredients", "args": {"rxcui": "1049502"}}' | python3 rxnav_proxy.py
    echo '{"tool": "get-ndc", "args": {"rxcui": "1049502"}}' | python3 rxnav_proxy.py
    echo '{"tool": "get-drug-classes", "args": {"drug_name": "warfarin"}}' | python3 rxnav_proxy.py

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.

RxNav REST API base: https://rxnav.nlm.nih.gov/REST
"""

import json
import sys
import urllib.parse
import urllib.request
import urllib.error

BASE_URL = "https://rxnav.nlm.nih.gov/REST"
REQUEST_TIMEOUT_SECONDS = 20
DEFAULT_MAX_ENTRIES = 10


def _fetch(url: str) -> dict:
    """Execute an HTTP GET and return parsed JSON. Raises RuntimeError on failure."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "NexVigilant-FerroForge/1.0 (ferroforge@nexvigilant.com)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        error_body = {}
        try:
            error_body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            pass
        msg = error_body.get("message", exc.reason) if error_body else exc.reason
        raise RuntimeError(f"HTTP {exc.code}: {msg}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def _resolve_drug(args: dict) -> str:
    """Resolve drug name from any known alias. Agents use varied parameter names."""
    return (args.get("drug_name") or args.get("drug") or args.get("name")
            or args.get("substance") or args.get("product")
            or args.get("query") or "").strip()


def _resolve_query(args: dict) -> str:
    """Resolve query from any known alias."""
    return (args.get("query") or args.get("search_query") or args.get("search")
            or args.get("q") or args.get("drug_name") or args.get("drug")
            or "").strip()


def get_rxcui(args: dict) -> dict:
    """
    Tool: get-rxcui

    Resolves a drug name (brand or generic) to its RxNorm Concept Unique Identifier
    (RxCUI). Returns the primary RxCUI and any additional concept details available.
    Uses the /rxcui.json?name= endpoint for exact-match concept lookup.
    """
    drug_name = _resolve_drug(args)
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    encoded = urllib.parse.quote(drug_name, safe="")
    url = f"{BASE_URL}/rxcui.json?name={encoded}"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "drug_name": drug_name}

    # RxNav returns idGroup with rxnormId list on exact match
    id_group = data.get("idGroup", {})
    rxnorm_ids = id_group.get("rxnormId", [])

    if not rxnorm_ids:
        return {
            "status": "not_found",
            "message": f"No RxCUI found for '{drug_name}'. Try search-drugs for approximate matches.",
            "drug_name": drug_name,
        }

    primary_rxcui = rxnorm_ids[0]

    # Fetch concept properties for the primary RxCUI
    props_url = f"{BASE_URL}/rxcui/{primary_rxcui}/properties.json"
    properties = {}
    try:
        props_data = _fetch(props_url)
        props = props_data.get("properties", {})
        properties = {
            "name": props.get("name"),
            "synonym": props.get("synonym"),
            "tty": props.get("tty"),          # term type: IN, BN, SBD, SCD, etc.
            "language": props.get("language"),
        }
    except RuntimeError:
        pass  # Properties are supplementary; continue without them

    return {
        "status": "ok",
        "drug_name": drug_name,
        "rxcui": primary_rxcui,
        "all_rxcuis": rxnorm_ids,
        "properties": properties,
    }


def search_drugs(args: dict) -> dict:
    """
    Tool: search-drugs

    Searches RxNorm using approximate term matching. Returns ranked candidates
    with their RxCUI, name, and match score. Useful when exact name is unknown
    or misspelled. Uses /approximateTerm.json.
    """
    query = _resolve_query(args)
    if not query:
        return {"status": "error", "message": "query is required (also accepts: drug_name, drug, search_query)", "count": 0, "results": []}

    max_entries = int(args.get("max_entries", DEFAULT_MAX_ENTRIES))
    max_entries = max(1, min(max_entries, 100))

    encoded = urllib.parse.quote(query, safe="")
    url = f"{BASE_URL}/approximateTerm.json?term={encoded}&maxEntries={max_entries}"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "count": 0, "results": []}

    approx_group = data.get("approximateGroup", {})
    candidates = approx_group.get("candidate", [])

    results = []
    for c in candidates:
        results.append({
            "rxcui": c.get("rxcui"),
            "rxaui": c.get("rxaui"),
            "score": c.get("score"),
            "rank": c.get("rank"),
            "name": c.get("name"),
        })

    return {
        "status": "ok",
        "query": query,
        "count": len(results),
        "results": results,
    }


def get_interactions(args: dict) -> dict:
    """
    Tool: get-interactions

    Returns drug-drug interaction pairs for a set of RxCUIs. Accepts a
    plus-sign-separated or comma-separated list of RxCUIs and queries
    /interaction/list.json. Returns interaction pairs with severity,
    description, and source references (NDF-RT, ONCHigh, DrugBank, etc.).
    """
    rxcuis_raw = args.get("rxcuis", "").strip()
    if not rxcuis_raw:
        return {"status": "error", "message": "rxcuis is required (plus-separated or comma-separated RxCUI list)"}

    # Normalize separators and determine endpoint
    rxcuis_normalized = rxcuis_raw.replace(",", "+").replace(" ", "")
    rxcui_list = [r for r in rxcuis_normalized.split("+") if r]

    if len(rxcui_list) == 1:
        url = f"{BASE_URL}/interaction/interaction.json?rxcui={rxcui_list[0]}"
    else:
        url = f"{BASE_URL}/interaction/list.json?rxcuis={rxcuis_normalized}"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        error_msg = str(exc)
        if "404" in error_msg:
            return {
                "status": "unavailable",
                "message": "RxNav interaction API endpoints (/interaction/) are no longer available as of API v3.1.345 (March 2026). Use DrugBank or openFDA for drug-drug interaction data.",
                "rxcuis": rxcuis_raw,
            }
        return {"status": "error", "message": error_msg, "rxcuis": rxcuis_raw}

    full_interaction_type_group = data.get("fullInteractionTypeGroup", [])

    interactions = []
    for group in full_interaction_type_group:
        source = group.get("sourceName", "")
        for interaction_type in group.get("fullInteractionType", []):
            comment = interaction_type.get("comment", "")
            for pair in interaction_type.get("interactionPair", []):
                concepts = pair.get("interactionConcept", [])
                drug_pair = []
                for concept in concepts:
                    min_concept = concept.get("minConceptItem", {})
                    drug_pair.append({
                        "rxcui": min_concept.get("rxcui"),
                        "name": min_concept.get("name"),
                        "tty": min_concept.get("tty"),
                    })
                interactions.append({
                    "source": source,
                    "severity": pair.get("severity", ""),
                    "description": pair.get("description", comment),
                    "drugs": drug_pair,
                })

    return {
        "status": "ok",
        "rxcuis": rxcuis_raw,
        "interaction_count": len(interactions),
        "interactions": interactions,
    }


def get_ingredients(args: dict) -> dict:
    """
    Tool: get-ingredients

    Returns the active ingredient(s) for a drug product RxCUI.
    Queries /rxcui/{rxcui}/related.json?tty=IN to navigate the RxNorm
    concept graph to ingredient-level terms (tty=IN).
    """
    rxcui = args.get("rxcui", "").strip()
    if not rxcui:
        return {"status": "error", "message": "rxcui is required"}

    url = f"{BASE_URL}/rxcui/{rxcui}/related.json?tty=IN"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "rxcui": rxcui}

    related_group = data.get("relatedGroup", {})
    concept_group_list = related_group.get("conceptGroup", [])

    ingredients = []
    for group in concept_group_list:
        if group.get("tty") == "IN":
            for prop in group.get("conceptProperties", []):
                ingredients.append({
                    "rxcui": prop.get("rxcui"),
                    "name": prop.get("name"),
                    "synonym": prop.get("synonym"),
                    "tty": prop.get("tty"),
                    "language": prop.get("language"),
                })

    if not ingredients:
        return {
            "status": "not_found",
            "message": f"No ingredient (tty=IN) concepts found for RxCUI {rxcui}",
            "rxcui": rxcui,
        }

    return {
        "status": "ok",
        "rxcui": rxcui,
        "ingredient_count": len(ingredients),
        "ingredients": ingredients,
    }


def get_ndc(args: dict) -> dict:
    """
    Tool: get-ndc

    Returns NDC (National Drug Code) codes associated with a given RxCUI.
    Queries /rxcui/{rxcui}/ndcs.json. NDCs identify specific marketed
    products (labeler + product + package).
    """
    rxcui = args.get("rxcui", "").strip()
    if not rxcui:
        return {"status": "error", "message": "rxcui is required"}

    url = f"{BASE_URL}/rxcui/{rxcui}/ndcs.json"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "rxcui": rxcui}

    ndc_group = data.get("ndcGroup", {})
    ndc_list = ndc_group.get("ndcList", {})
    ndcs = ndc_list.get("ndc", [])

    if not ndcs:
        return {
            "status": "not_found",
            "message": f"No NDCs found for RxCUI {rxcui}",
            "rxcui": rxcui,
        }

    return {
        "status": "ok",
        "rxcui": rxcui,
        "ndc_count": len(ndcs),
        "ndcs": ndcs,
    }


def get_drug_classes(args: dict) -> dict:
    """
    Tool: get-drug-classes

    Returns pharmacologic and therapeutic drug classes for a drug by name.
    Queries /rxclass/class/byDrugName.json which returns ATC, EPC, MoA,
    PE, PK, TC, VA, and other classification systems.
    """
    drug_name = _resolve_drug(args)
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    encoded = urllib.parse.quote(drug_name, safe="")
    url = f"{BASE_URL}/rxclass/class/byDrugName.json?drugName={encoded}"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "drug_name": drug_name}

    drug_member_group = data.get("rxclassDrugInfoList", {})
    members = drug_member_group.get("rxclassDrugInfo", [])

    if not members:
        return {
            "status": "not_found",
            "message": f"No drug class data found for '{drug_name}'",
            "drug_name": drug_name,
        }

    # Group by classification type, dedup by (class_id, class_name, relation)
    classes_by_type: dict[str, list[dict]] = {}
    seen: set[tuple[str, str, str, str]] = set()
    for member in members:
        rx_class_info = member.get("rxclassMinConceptItem", {})
        class_type = rx_class_info.get("classType", "UNKNOWN")
        class_id = rx_class_info.get("classId", "")
        class_name = rx_class_info.get("className", "")
        relation = member.get("rela", "")
        key = (class_type, class_id, class_name, relation)
        if key in seen:
            continue
        seen.add(key)
        entry = {
            "class_id": class_id,
            "class_name": class_name,
            "relation": relation,
        }
        classes_by_type.setdefault(class_type, []).append(entry)

    unique_count = sum(len(v) for v in classes_by_type.values())
    return {
        "status": "ok",
        "drug_name": drug_name,
        "total_classifications": unique_count,
        "classes_by_type": classes_by_type,
    }


TOOL_DISPATCH = {
    "get-rxcui": get_rxcui,
    "search-drugs": search_drugs,
    "get-interactions": get_interactions,
    "get-ingredients": get_ingredients,
    "get-ndc": get_ndc,
    "get-drug-classes": get_drug_classes,
}


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        result = {"status": "error", "message": "No input received on stdin"}
        print(json.dumps(result))
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        result = {"status": "error", "message": f"Invalid JSON input: {exc}"}
        print(json.dumps(result))
        sys.exit(1)

    tool_name = payload.get("tool", "").strip()
    args = payload.get("arguments", payload.get("args", {}))

    if tool_name not in TOOL_DISPATCH:
        known = list(TOOL_DISPATCH.keys())
        result = {
            "status": "error",
            "message": f"Unknown tool '{tool_name}'. Known tools: {known}",
        }
        print(json.dumps(result))
        sys.exit(1)

    handler = TOOL_DISPATCH[tool_name]
    result = handler(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
