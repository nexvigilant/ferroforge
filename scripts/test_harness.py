#!/usr/bin/env python3
"""
NexVigilant Station — Automated Test Harness

Auto-discovers all configs and their tools, generates test inputs,
runs each through dispatch.py, and validates responses.

Usage:
    python3 scripts/test_harness.py              # Test all tools
    python3 scripts/test_harness.py --live-only   # Only test live proxy tools
    python3 scripts/test_harness.py --domain fda  # Filter by domain substring
"""

import json
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.resolve()
CONFIGS_DIR = SCRIPTS_DIR.parent / "configs"
DISPATCH = str(SCRIPTS_DIR / "dispatch.py")

# Default test arguments per parameter name (for generating test inputs)
DEFAULT_TEST_ARGS: dict[str, str] = {
    "drug_name": "metformin",
    "drug": "metformin",
    "query": "metformin safety",
    "nct_id": "NCT02793479",
    "event": "lactic acidosis",
    "reaction": "lactic acidosis",
    "name": "metformin",
    "condition": "diabetes",
    "limit": "3",
    "term": "lactic acidosis",
    "rxcui": "6809",
    "pmid": "25505270",
    "set_id": "cfda5778-0089-4954-94ed-5ba21f8e2b14",
    "spl_id": "cfda5778-0089-4954-94ed-5ba21f8e2b14",
    "gene": "BRCA1",
    "target": "EGFR",
    "organism": "human",
    "protein": "insulin",
    "identifier": "metformin",
    "application_number": "NDA020357",
    "uniprot_id": "O94992",
}


def load_configs() -> list[dict]:
    """Load all config JSON files."""
    configs = []
    for path in sorted(CONFIGS_DIR.glob("*.json")):
        try:
            with open(path) as f:
                configs.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue
    return configs


def has_proxy(config: dict) -> bool:
    """Check if a config has any proxy (config-level or tool-level)."""
    if config.get("proxy"):
        return True
    return any(t.get("proxy") for t in config.get("tools", []))


def make_mcp_name(domain: str, tool_name: str) -> str:
    """Build the MCP-prefixed tool name."""
    prefix = domain.replace(".", "_")
    suffix = tool_name.replace("-", "_")
    return f"{prefix}_{suffix}"


# Per-tool overrides when the default for a param name is wrong for that tool
TOOL_ARG_OVERRIDES: dict[str, dict[str, str]] = {
    "get-crystal-structures": {"query": "EGFR kinase"},
    "search-clinical-candidates": {"target": "EGFR"},
    "get-expression-profile": {"query": "BRCA1 expression"},
    "search-geo-datasets": {"query": "cancer gene expression"},
}


def generate_test_args(tool: dict) -> dict:
    """Generate test arguments from tool parameter definitions."""
    tool_name = tool.get("name", "")
    overrides = TOOL_ARG_OVERRIDES.get(tool_name, {})
    args = {}
    for param in tool.get("parameters", []):
        name = param.get("name", "")
        if name in overrides:
            args[name] = overrides[name]
        elif name in DEFAULT_TEST_ARGS:
            args[name] = DEFAULT_TEST_ARGS[name]
        elif param.get("required", False):
            args[name] = "test"
    return args


def call_dispatch(tool_name: str, arguments: dict, timeout: int = 30) -> tuple[dict, float]:
    """Call dispatch.py with a tool envelope. Returns (response, elapsed_secs)."""
    envelope = json.dumps({"tool": tool_name, "arguments": arguments})
    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, DISPATCH],
            input=envelope,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"Timeout after {timeout}s"}, timeout

    if result.returncode != 0:
        return {"status": "error", "error": result.stderr.strip()[:200]}, time.time() - start

    try:
        return json.loads(result.stdout.strip()), elapsed
    except json.JSONDecodeError:
        return {"status": "error", "error": "Invalid JSON response"}, elapsed


def validate_schema(response: dict, tool: dict) -> list[str]:
    """Validate response against outputSchema. Returns list of violations."""
    violations = []
    schema = tool.get("outputSchema", {})
    if not schema:
        return violations

    required = schema.get("required", [])
    properties = schema.get("properties", {})

    for field in required:
        if field not in response:
            violations.append(f"Missing required field: {field}")

    for field, prop in properties.items():
        if field in response:
            expected_type = prop.get("type")
            value = response[field]
            if expected_type == "string" and not isinstance(value, str):
                violations.append(f"{field}: expected string, got {type(value).__name__}")
            elif expected_type == "number" and not isinstance(value, (int, float)):
                violations.append(f"{field}: expected number, got {type(value).__name__}")
            elif expected_type == "object" and not isinstance(value, dict):
                violations.append(f"{field}: expected object, got {type(value).__name__}")
            elif expected_type == "array" and not isinstance(value, list):
                violations.append(f"{field}: expected array, got {type(value).__name__}")

    return violations


def main() -> None:
    live_only = "--live-only" in sys.argv
    domain_filter = ""
    for i, arg in enumerate(sys.argv):
        if arg == "--domain" and i + 1 < len(sys.argv):
            domain_filter = sys.argv[i + 1].lower()

    configs = load_configs()
    print("NexVigilant Station — Test Harness")
    print(f"Configs: {len(configs)}, Filter: {'live-only' if live_only else 'all'}"
          + (f", domain={domain_filter}" if domain_filter else ""))
    print("=" * 72)

    total = 0
    passed = 0
    failed = 0
    skipped = 0
    results_table: list[tuple[str, str, str, str, str]] = []

    for config in configs:
        domain = config.get("domain", "unknown")
        if domain_filter and domain_filter not in domain.lower():
            continue

        is_live = has_proxy(config)
        if live_only and not is_live:
            continue

        for tool in config.get("tools", []):
            total += 1
            mcp_name = make_mcp_name(domain, tool["name"])
            args = generate_test_args(tool)

            if not is_live:
                skipped += 1
                results_table.append((mcp_name, "SKIP", "—", "no proxy", ""))
                continue

            response, elapsed = call_dispatch(mcp_name, args)
            status = response.get("status", "unknown")
            schema_violations = validate_schema(response, tool)

            if status in ("ok", "stub", "not_found", "unavailable") and not schema_violations:
                passed += 1
                symbol = "PASS"
            elif status == "error" and "timeout" in str(response.get("error", "")).lower():
                failed += 1
                symbol = "TIMEOUT"
            else:
                failed += 1
                symbol = "FAIL"

            error_detail = ""
            if schema_violations:
                error_detail = "; ".join(schema_violations)
            elif status == "error":
                error_detail = str(response.get("error", ""))[:80]

            results_table.append((
                mcp_name,
                symbol,
                f"{elapsed:.1f}s",
                status,
                error_detail,
            ))

    # Print results
    for name, symbol, elapsed, status, detail in results_table:
        short_name = name if len(name) <= 50 else name[:47] + "..."
        line = f"  [{symbol:>7}] {short_name:<50} {elapsed:>6}  {status}"
        if detail:
            line += f"  ({detail})"
        print(line)

    print("=" * 72)
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped out of {total} tools")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
