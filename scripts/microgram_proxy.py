#!/usr/bin/env python3
"""
NexVigilant Microgram Proxy — Decision Tree Executor

Routes MCP tool calls to the rsk binary for microgram and chain execution.
Uses rsk_pool for path caching and pre-validated binary.

Usage:
    echo '{"tool": "run-prr-signal", "arguments": {"prr": 8.5}}' | python3 microgram_proxy.py
"""

import json
import os
import sys

# Ensure sibling imports work regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rsk_pool import run_single, run_chain, run_chain_file, catalog, CHAINS_DIR

# ---------------------------------------------------------------------------
# Chain definitions: tool name → chain spec
# ---------------------------------------------------------------------------

CHAIN_TOOLS = {
    "run-pv-signal-to-action": {
        "chain": "prr-signal -> signal-to-causality -> naranjo-quick -> causality-to-action",
    },
    "run-case-assessment-pipeline": {
        "chain": "case-validity -> case-seriousness -> signal-to-causality -> naranjo-quick -> causality-to-action",
    },
    "run-benefit-risk-assessment": {
        "chain": "benefit-risk-gate -> benefit-risk-ratio",
    },
    "run-station-dailymed-pipeline": {
        "chain": "config-dailymed-adr-risk -> adapt-risk-tier -> signal-to-causality",
    },
    "run-station-pubmed-pipeline": {
        "chain": "config-pubmed-signal-strength -> adapt-evidence-to-signal -> signal-to-causality",
    },
    "run-station-openvigil-pipeline": {
        "chain": "config-openvigil-triage -> adapt-signal-strength -> signal-to-causality",
    },
    "run-station-trial-pipeline": {
        "chain": "config-trial-sae-triage -> adapt-safety-concern -> signal-to-causality",
    },
    "run-station-drugbank-pipeline": {
        "chain": "config-drugbank-ddi-gate -> adapt-interaction-severity -> signal-to-causality",
    },
    "run-station-rxnav-pipeline": {
        "chain": "config-rxnav-interaction-severity -> adapt-interaction-severity -> signal-to-causality",
    },
    "run-station-recall-pipeline": {
        "chain": "config-fda-recall-severity -> adapt-risk-tier -> signal-to-causality",
    },
    "run-seriousness-to-deadline": {
        "chain": "case-seriousness -> transform-seriousness-to-bool",
    },
    "run-adr-severity-escalation": {
        "chain": "adr-severity -> escalation-router",
    },
    "run-confidence-deadline": {
        "chain": "confidence-gate -> deadline-alert",
    },
    "run-investigation-prioritization": {
        "chain": "transbeyesian-propagator -> eig-priority-ranker",
    },
    "run-signal-deep-validation": {
        "chain": "multi-signal-combiner -> signal-validation-gate -> signal-trend-detector -> signal-recurrence-detector",
    },
    "run-bradford-hill-evidence": {
        "chain": "signal-comparator -> dose-response-classifier -> naranjo-quick",
    },
    "run-bradford-hill-multi-criterion": {
        "chain": "temporal-association -> signal-comparator -> dose-response-classifier -> rechallenge-evaluator -> naranjo-quick",
    },
    "run-helix-system-health": {
        "chain": "heligram -> crystalbook-4primitive -> crystalbook-8law",
    },
    "run-sota-drift-detection": {
        "chain": "sota-domain-classifier -> sota-frontier-check -> drift-alert-classifier",
    },
    "run-sota-pubmed-pipeline": {
        "chain": "sota-pubmed-triage -> sota-domain-classifier -> sota-frontier-check -> drift-alert-classifier",
    },
    "run-signal-consensus-to-action": {
        "chain_file": "signal-consensus-to-action",
    },
    # Spanish grammar chains
    "run-caso-clinico-espanol": {
        "chain_file": "caso-clinico-espanol",
    },
    "run-gramatica-causalidad-espanola": {
        "chain_file": "gramatica-causalidad-espanola",
    },
    "run-presente-desambiguacion": {
        "chain_file": "presente-desambiguacion",
    },
}

# Single microgram tools: tool name → microgram filename (without .yaml)
SINGLE_TOOLS = {
    "run-prr-signal": "prr-signal",
    "run-naranjo-quick": "naranjo-quick",
    "run-case-seriousness": "case-seriousness",
    "run-workflow-router": "workflow-router",
    "run-crystalbook-4primitive": "crystalbook-4primitive",
    "run-crystalbook-8law": "crystalbook-8law",
    "run-crystalbook-diagnostic": "crystalbook-diagnostic",
    "run-ich-q1a-stability-testing": "ich-q1a-stability-testing",
    "run-ich-q1b-photostability": "ich-q1b-photostability",
    "run-ich-e1-population-exposure": "ich-e1-population-exposure",
    "run-heligram": "heligram",
    "run-sota-authority-decompose": "sota-authority-decompose",
    "run-disproportionality-consensus": "disproportionality-consensus",
}


def list_chains() -> dict:
    """List available chain files."""
    import yaml
    chains = []
    for f in sorted(CHAINS_DIR.glob("*.yaml")):
        try:
            with open(f) as fh:
                data = yaml.safe_load(fh)
            chains.append({
                "name": data.get("name", f.stem),
                "description": data.get("description", ""),
                "steps": data.get("steps", []),
            })
        except Exception:
            chains.append({"name": f.stem, "description": "", "steps": []})
    return {"status": "ok", "chains": chains}


def dispatch(tool: str, args: dict) -> dict:
    """Route tool call to the correct handler."""
    if tool in CHAIN_TOOLS:
        spec = CHAIN_TOOLS[tool]
        if "chain_file" in spec:
            return run_chain_file(spec["chain_file"], args)
        return run_chain(spec["chain"], args, accumulate=True)
    elif tool in SINGLE_TOOLS:
        return run_single(SINGLE_TOOLS[tool], args)
    elif tool == "list-micrograms":
        return catalog()
    elif tool == "list-chains":
        return list_chains()
    else:
        return {"status": "error", "message": f"Unknown tool: {tool}"}


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"status": "error", "message": "No input"}))
        return

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"status": "error", "message": "Invalid JSON input"}))
        return

    tool = envelope.get("tool", "")
    args = envelope.get("arguments", {})

    result = dispatch(tool, args)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
