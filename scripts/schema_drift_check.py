#!/usr/bin/env python3
"""Schema drift detection — validate config JSON files against expected schema.

Checks that all config files in configs/ conform to the HubConfig schema:
- Required top-level fields present (domain, title, description, tools)
- Each tool has required fields (name, description, parameters)
- Each parameter has required fields (name, type, description, required)
- No empty tool lists
- Domain names are valid identifiers
- Tool names follow kebab-case convention

Usage:
    python3 scripts/schema_drift_check.py [--config-dir configs]
"""

import json
import sys
import re
import argparse
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description="Schema drift detection")
    p.add_argument("--config-dir", default="configs",
                   help="Path to configs directory")
    p.add_argument("--json", action="store_true",
                   help="Output as JSON")
    return p.parse_args()


REQUIRED_TOP = {"domain", "title", "description", "tools"}
REQUIRED_TOOL = {"name", "description", "parameters"}
REQUIRED_PARAM = {"name", "type", "description", "required"}
KEBAB_RE = re.compile(r'^[a-z][a-z0-9]*(-[a-z0-9]+)*$')


def validate_config(path):
    """Validate a single config file. Returns list of issues."""
    issues = []

    try:
        with open(path) as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"]

    if not isinstance(config, dict):
        return ["Config root must be an object"]

    # Check required top-level fields
    missing_top = REQUIRED_TOP - set(config.keys())
    if missing_top:
        issues.append(f"Missing top-level fields: {', '.join(sorted(missing_top))}")

    # Validate domain
    domain = config.get("domain", "")
    if not domain:
        issues.append("Empty domain")

    # Validate tools array
    tools = config.get("tools", [])
    if not isinstance(tools, list):
        issues.append("'tools' must be an array")
        return issues

    if len(tools) == 0:
        issues.append("Empty tools array")

    for i, tool in enumerate(tools):
        if not isinstance(tool, dict):
            issues.append(f"Tool [{i}]: must be an object")
            continue

        # Check required tool fields
        missing_tool = REQUIRED_TOOL - set(tool.keys())
        if missing_tool:
            name = tool.get("name", f"[{i}]")
            issues.append(f"Tool '{name}': missing fields: {', '.join(sorted(missing_tool))}")

        # Validate tool name format
        name = tool.get("name", "")
        if name and not KEBAB_RE.match(name):
            issues.append(f"Tool '{name}': name should be kebab-case")

        # Validate parameters
        params = tool.get("parameters", [])
        if not isinstance(params, list):
            issues.append(f"Tool '{name}': 'parameters' must be an array")
            continue

        for j, param in enumerate(params):
            if not isinstance(param, dict):
                issues.append(f"Tool '{name}' param [{j}]: must be an object")
                continue

            missing_param = REQUIRED_PARAM - set(param.keys())
            if missing_param:
                pname = param.get("name", f"[{j}]")
                issues.append(f"Tool '{name}' param '{pname}': missing: {', '.join(sorted(missing_param))}")

    return issues


def main():
    args = parse_args()
    config_dir = Path(args.config_dir)

    if not config_dir.exists():
        print(f"Error: Config directory not found: {config_dir}", file=sys.stderr)
        sys.exit(1)

    configs = sorted(config_dir.glob("*.json"))
    if not configs:
        print(f"No JSON configs found in {config_dir}", file=sys.stderr)
        sys.exit(1)

    results = {"total_configs": len(configs), "valid": 0, "invalid": 0, "issues": []}

    for path in configs:
        issues = validate_config(path)
        if issues:
            results["invalid"] += 1
            results["issues"].append({"file": path.name, "issues": issues})
        else:
            results["valid"] += 1

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"\n=== Schema Drift Check ===")
        print(f"Configs: {results['total_configs']}")
        print(f"Valid: {results['valid']}")
        print(f"Invalid: {results['invalid']}")

        if results["issues"]:
            print(f"\n--- Issues ---")
            for entry in results["issues"]:
                print(f"\n{entry['file']}:")
                for issue in entry["issues"]:
                    print(f"  - {issue}")
        else:
            print("\nAll configs valid.")

        print()

    sys.exit(1 if results["invalid"] > 0 else 0)


if __name__ == "__main__":
    main()
