#!/usr/bin/env python3
"""
NexVigilant Microgram Proxy — Decision Tree Executor

Routes MCP tool calls to the rsk binary for microgram and chain execution.
Sub-microsecond PV logic: signal classification, causality, seriousness, regulatory action.

Usage:
    echo '{"tool": "run-prr-signal", "arguments": {"prr": 8.5}}' | python3 microgram_proxy.py
"""

import json
import subprocess
import sys
from pathlib import Path

import os
RSK_BINARY = Path(os.environ.get("RSK_BINARY", str(Path.home() / "Projects" / "rsk-core" / "target" / "release" / "rsk")))
MCG_DIR = Path(os.environ.get("MCG_DIR", str(Path.home() / "Projects" / "rsk-core" / "rsk" / "micrograms")))
CHAINS_DIR = Path(os.environ.get("CHAINS_DIR", str(Path.home() / "Projects" / "rsk-core" / "rsk" / "chains")))

# ---------------------------------------------------------------------------
# Chain definitions: tool name → chain spec
# ---------------------------------------------------------------------------

CHAIN_TOOLS = {
    "run-pv-signal-to-action": {
        "chain": "prr-signal -> signal-to-causality -> naranjo-quick -> causality-to-action",
        "accumulate": True,
    },
    "run-case-assessment-pipeline": {
        "chain": "case-validity -> case-seriousness -> signal-to-causality -> naranjo-quick -> causality-to-action",
        "accumulate": True,
    },
    "run-benefit-risk-assessment": {
        "chain": "benefit-risk-gate -> benefit-risk-ratio",
        "accumulate": True,
    },
    # Tier 1: Station-integration chains (designed to consume Station tool outputs)
    "run-station-dailymed-pipeline": {
        "chain": "config-dailymed-adr-risk -> adapt-risk-tier -> signal-to-causality",
        "accumulate": True,
    },
    "run-station-pubmed-pipeline": {
        "chain": "config-pubmed-signal-strength -> adapt-evidence-to-signal -> signal-to-causality",
        "accumulate": True,
    },
    "run-station-openvigil-pipeline": {
        "chain": "config-openvigil-triage -> adapt-signal-strength -> signal-to-causality",
        "accumulate": True,
    },
    "run-station-trial-pipeline": {
        "chain": "config-trial-sae-triage -> adapt-safety-concern -> signal-to-causality",
        "accumulate": True,
    },
    "run-station-drugbank-pipeline": {
        "chain": "config-drugbank-ddi-gate -> adapt-interaction-severity -> signal-to-causality",
        "accumulate": True,
    },
    "run-station-rxnav-pipeline": {
        "chain": "config-rxnav-interaction-severity -> adapt-interaction-severity -> signal-to-causality",
        "accumulate": True,
    },
    "run-station-recall-pipeline": {
        "chain": "config-fda-recall-severity -> adapt-risk-tier -> signal-to-causality",
        "accumulate": True,
    },
    # Tier 2: Core clinical decision chains
    "run-seriousness-to-deadline": {
        "chain": "case-seriousness -> transform-seriousness-to-bool",
        "accumulate": True,
    },
    "run-adr-severity-escalation": {
        "chain": "adr-severity -> escalation-router",
        "accumulate": True,
    },
    "run-confidence-deadline": {
        "chain": "confidence-gate -> deadline-alert",
        "accumulate": True,
    },
    "run-investigation-prioritization": {
        "chain": "transbeyesian-propagator -> eig-priority-ranker",
        "accumulate": True,
    },
    "run-signal-deep-validation": {
        "chain": "multi-signal-combiner -> signal-validation-gate -> signal-trend-detector -> signal-recurrence-detector",
        "accumulate": True,
    },
    "run-bradford-hill-evidence": {
        "chain": "signal-comparator -> dose-response-classifier -> naranjo-quick",
        "accumulate": True,
    },
    "run-bradford-hill-multi-criterion": {
        "chain": "temporal-association -> signal-comparator -> dose-response-classifier -> rechallenge-evaluator -> naranjo-quick",
        "accumulate": True,
    },
    # Helix Computing chains
    "run-helix-system-health": {
        "chain": "heligram -> crystalbook-4primitive -> crystalbook-8law",
        "accumulate": True,
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
}


def run_single(microgram: str, input_json: dict) -> dict:
    """Execute a single microgram via rsk mcg run."""
    mcg_path = MCG_DIR / f"{microgram}.yaml"
    if not mcg_path.exists():
        return {"status": "error", "message": f"Microgram not found: {microgram}"}

    cmd = [
        str(RSK_BINARY), "mcg", "run",
        "-i", json.dumps(input_json),
        str(mcg_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

    if result.returncode != 0:
        return {"status": "error", "message": result.stderr.strip()[:500]}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "message": f"Invalid JSON output: {result.stdout[:200]}"}


def run_chain(spec: dict, input_json: dict) -> dict:
    """Execute a microgram chain via rsk mcg chain."""
    if "chain_file" in spec:
        # Use chain YAML file
        chain_path = CHAINS_DIR / f"{spec['chain_file']}.yaml"
        if not chain_path.exists():
            return {"status": "error", "message": f"Chain file not found: {spec['chain_file']}"}

        cmd = [
            str(RSK_BINARY), "mcg", "chain",
            "-i", json.dumps(input_json),
            "--accumulate",
            str(chain_path),
        ]
    else:
        # Inline chain spec
        cmd = [
            str(RSK_BINARY), "mcg", "chain",
            "-i", json.dumps(input_json),
            "-d", str(MCG_DIR),
        ]
        if spec.get("accumulate"):
            cmd.append("--accumulate")
        cmd.append(spec["chain"])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        return {"status": "error", "message": result.stderr.strip()[:500]}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "message": f"Invalid JSON output: {result.stdout[:200]}"}


def list_micrograms() -> dict:
    """List available micrograms via rsk mcg catalog."""
    cmd = [str(RSK_BINARY), "mcg", "catalog", str(MCG_DIR)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

    if result.returncode != 0:
        return {"status": "error", "message": result.stderr.strip()[:500]}

    try:
        data = json.loads(result.stdout)
        entries = data.get("entries", [])
        return {
            "status": "ok",
            "micrograms": data.get("total_micrograms", len(entries)),
            "total_tests": data.get("total_tests", 0),
            "all_pass": data.get("all_pass", False),
            "catalog": entries,
        }
    except json.JSONDecodeError:
        return {"status": "ok", "micrograms": 0, "catalog": []}


def list_chains() -> dict:
    """List available chain files."""
    chains = []
    for f in sorted(CHAINS_DIR.glob("*.yaml")):
        try:
            import yaml
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
        return run_chain(CHAIN_TOOLS[tool], args)
    elif tool in SINGLE_TOOLS:
        return run_single(SINGLE_TOOLS[tool], args)
    elif tool == "list-micrograms":
        return list_micrograms()
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
