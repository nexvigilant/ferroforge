#!/usr/bin/env python3
"""
DrugBank Proxy — routes MoltBrowser hub tool calls for go.drugbank.com.

Usage:
    echo '{"tool": "get-drug-info", "args": {"drug_name": "metformin"}}' | python3 drugbank_proxy.py

DrugBank requires a commercial API key. All tools return intelligent stubs
describing what each tool will return when live API access is configured.

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.
"""

import json
import sys


def _stub_response(tool_name: str, description: str, args: dict) -> dict:
    """Build a standardized stub response for a DrugBank tool."""
    return {
        "status": "stub",
        "tool": tool_name,
        "description": description,
        "parameters_received": args,
        "data_source": "go.drugbank.com",
        "implementation_notes": "Requires DrugBank API key (commercial license)",
    }


def get_drug_info(args: dict) -> dict:
    """
    Tool: get-drug-info

    Retrieves comprehensive drug information from DrugBank including
    identifiers, classification, description, categories, and regulatory status.
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    return _stub_response(
        "get-drug-info",
        (
            "Returns comprehensive drug monograph: DrugBank ID, IUPAC name, "
            "molecular formula, molecular weight, description, drug categories, "
            "ATC codes, pharmacological classification, regulatory status "
            "(FDA/EMA approval), and cross-references (PubChem, ChEBI, KEGG)."
        ),
        args,
    )


def get_interactions(args: dict) -> dict:
    """
    Tool: get-interactions

    Retrieves drug-drug interactions from DrugBank for the specified drug.
    Returns interacting drugs, severity, and clinical descriptions.
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    return _stub_response(
        "get-interactions",
        (
            "Returns drug-drug interactions: interacting drug name, DrugBank ID, "
            "interaction description, severity level (major/moderate/minor), "
            "clinical consequence, and management recommendation. Supports "
            "filtering by severity via optional 'severity' parameter."
        ),
        args,
    )


def get_pharmacology(args: dict) -> dict:
    """
    Tool: get-pharmacology

    Retrieves pharmacological profile from DrugBank including mechanism of
    action, pharmacodynamics, pharmacokinetics (ADME), and toxicity data.
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    return _stub_response(
        "get-pharmacology",
        (
            "Returns pharmacological profile: mechanism of action, "
            "pharmacodynamics description, absorption, distribution (Vd, "
            "protein binding), metabolism (CYP enzymes), elimination (half-life, "
            "clearance, route), toxicity (LD50, adverse effects), and "
            "food/alcohol interactions."
        ),
        args,
    )


def get_targets(args: dict) -> dict:
    """
    Tool: get-targets

    Retrieves molecular targets (enzymes, transporters, carriers, receptors)
    for a drug from DrugBank. Returns target name, gene, organism, and action.
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    return _stub_response(
        "get-targets",
        (
            "Returns molecular targets grouped by type: targets (primary), "
            "enzymes (metabolizing), transporters, and carriers. Each entry "
            "includes UniProt ID, gene name, organism, known action "
            "(inhibitor/inducer/substrate/agonist/antagonist), and "
            "pharmacological action (yes/no/unknown)."
        ),
        args,
    )


def get_adverse_effects(args: dict) -> dict:
    """
    Tool: get-adverse-effects

    Retrieves known adverse effects for a drug from DrugBank, organized by
    MedDRA System Organ Class with frequency data where available.
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    return _stub_response(
        "get-adverse-effects",
        (
            "Returns adverse effects organized by MedDRA System Organ Class. "
            "Each effect includes preferred term, frequency category "
            "(very common/common/uncommon/rare/very rare/not known per CIOMS), "
            "and source reference (label, post-marketing, clinical trial). "
            "Useful for cross-referencing with FAERS signal detection."
        ),
        args,
    )


TOOL_DISPATCH = {
    "get-drug-info": get_drug_info,
    "get-interactions": get_interactions,
    "get-pharmacology": get_pharmacology,
    "get-targets": get_targets,
    "get-adverse-effects": get_adverse_effects,
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
