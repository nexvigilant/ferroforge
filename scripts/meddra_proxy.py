#!/usr/bin/env python3
"""
MedDRA Proxy — routes MoltBrowser hub tool calls for meddra.org.

Usage:
    echo '{"tool": "search-terms", "args": {"query": "headache"}}' | python3 meddra_proxy.py

MedDRA requires an MSSO subscription license (source: https://www.meddra.org/how-to-use/support-documentation/english).
All handlers return informative stubs describing what each tool would return
when connected to a live MedDRA dictionary. Reads a single JSON object from
stdin, dispatches to the appropriate handler, writes a structured JSON
response to stdout. No external dependencies — stdlib only.
"""

import json
import sys

# MedDRA hierarchy levels per MedDRA Introductory Guide
# (source: https://www.meddra.org/how-to-use/basics/hierarchy)
HIERARCHY_NOTE = (
    "MedDRA hierarchy: LLT -> PT -> HLT -> HLGT -> SOC "
    "(source: https://www.meddra.org/how-to-use/basics/hierarchy)"
)

# 27 SOCs per MedDRA structure
# (source: https://www.meddra.org/how-to-use/basics/hierarchy)
SOC_NOTE = (
    "27 SOCs organize all medical concepts by body system "
    "(source: https://www.meddra.org/how-to-use/basics/hierarchy)"
)

# SMQ documentation
# (source: https://www.meddra.org/how-to-use/tools/smqs)
SMQ_NOTE = (
    "SMQs are validated, pre-defined groupings of MedDRA terms for signal detection "
    "(source: https://www.meddra.org/how-to-use/tools/smqs)"
)


def search_terms(args: dict) -> dict:
    """
    Tool: search-terms

    Stub for MedDRA term search. When live, searches the MedDRA dictionary
    for PTs, LLTs, and HLTs matching the query.
    """
    query = args.get("query", "").strip()
    if not query:
        return {"status": "error", "message": "query is required"}

    return {
        "status": "stub",
        "tool": "search-terms",
        "description": (
            "Searches the MedDRA dictionary for Preferred Terms (PTs), "
            "Lowest Level Terms (LLTs), and High Level Terms (HLTs) matching "
            "the query. Returns coded terms with SOC hierarchy, MedDRA code, "
            "term level (LLT/PT/HLT/HLGT/SOC), and currency status. "
            + HIERARCHY_NOTE
        ),
        "parameters_received": {"query": query},
        "data_source": "meddra.org",
        "implementation_notes": "Requires MedDRA MSSO subscription license (source: https://www.meddra.org/how-to-use/support-documentation/english)",
    }


def get_term_hierarchy(args: dict) -> dict:
    """
    Tool: get-term-hierarchy

    Stub for MedDRA hierarchy lookup. When live, returns the full hierarchy
    for a given MedDRA term or code.
    """
    term = args.get("term", "").strip()
    code = args.get("code", "")
    if not term and not code:
        return {"status": "error", "message": "term or code is required"}

    return {
        "status": "stub",
        "tool": "get-term-hierarchy",
        "description": (
            "Returns the full MedDRA hierarchy for a given term or code. "
            + HIERARCHY_NOTE
            + ". Also returns the primary SOC flag "
            "and any multi-axiality (secondary SOC assignments)."
        ),
        "parameters_received": {
            "term": term or None,
            "code": code or None,
        },
        "data_source": "meddra.org",
        "implementation_notes": "Requires MedDRA MSSO subscription license (source: https://www.meddra.org/how-to-use/support-documentation/english)",
    }


def get_soc_terms(args: dict) -> dict:
    """
    Tool: get-soc-terms

    Stub for MedDRA SOC listing. When live, returns all Preferred Terms
    within a given System Organ Class.
    """
    soc = args.get("soc", "").strip()
    if not soc:
        return {"status": "error", "message": "soc is required"}

    return {
        "status": "stub",
        "tool": "get-soc-terms",
        "description": (
            "Returns all Preferred Terms (PTs) classified under the specified "
            "System Organ Class (SOC). " + SOC_NOTE
            + ". Results include PT code, term name, "
            "and primary/secondary SOC flag."
        ),
        "parameters_received": {"soc": soc},
        "data_source": "meddra.org",
        "implementation_notes": "Requires MedDRA MSSO subscription license (source: https://www.meddra.org/how-to-use/support-documentation/english)",
    }


def get_smq(args: dict) -> dict:
    """
    Tool: get-smq

    Stub for MedDRA Standardised MedDRA Query lookup. When live, returns
    the component terms of an SMQ.
    """
    smq_name = args.get("smq_name", "").strip()
    smq_code = args.get("smq_code", "")
    if not smq_name and not smq_code:
        return {"status": "error", "message": "smq_name or smq_code is required"}

    return {
        "status": "stub",
        "tool": "get-smq",
        "description": (
            "Returns the component Preferred Terms of a Standardised MedDRA "
            "Query (SMQ). " + SMQ_NOTE
            + ". Results include narrow/broad scope classification, term weight, "
            "and SMQ algorithm category."
        ),
        "parameters_received": {
            "smq_name": smq_name or None,
            "smq_code": smq_code or None,
        },
        "data_source": "meddra.org",
        "implementation_notes": "Requires MedDRA MSSO subscription license (source: https://www.meddra.org/how-to-use/support-documentation/english)",
    }


TOOL_DISPATCH = {
    "search-terms": search_terms,
    "get-term-hierarchy": get_term_hierarchy,
    "get-soc-terms": get_soc_terms,
    "get-smq": get_smq,
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
