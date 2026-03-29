#!/usr/bin/env python3
"""
Forge — Rapid NexVigilant Station config + proxy generator.

Generates config JSON, proxy Python script, and dispatch.py wiring from
a compact YAML domain specification. Designed for velocity.

Usage:
  # From a YAML spec file (one or many domains)
  python3 forge.py from-spec domains/new-apis.yaml

  # Quick single config (interactive — prompts for tools)
  python3 forge.py quick --domain "api.example.com" --title "Example API"

  # Audit: show configs missing proxies, dispatch wiring gaps
  python3 forge.py audit

  # Stats: current inventory
  python3 forge.py stats

YAML spec format:
  configs:
    - domain: "api.example.com"
      title: "Example Drug Safety API"
      description: "Drug safety data from Example"
      base_url: "https://api.example.com/v2"
      proxy: true                          # generate proxy script
      tools:
        - search-drugs: "Search drug database by name"
        - get-drug-info(drug_name): "Get detailed drug information"
        - get-interactions(drug_name, limit?:int=20): "Get drug-drug interactions"
        - compute-risk-score(drug_name, event): "Compute risk score for drug-event pair"
"""

import argparse
import json
import os
import re
import sys
import textwrap
from pathlib import Path

FERROFORGE = Path(__file__).parent.parent.resolve()
CONFIGS_DIR = FERROFORGE / "configs"
SCRIPTS_DIR = FERROFORGE / "scripts"


# ---------------------------------------------------------------------------
# Parameter inference from tool signatures
# ---------------------------------------------------------------------------

# Common parameter patterns inferred from tool name prefixes + conventions
PARAM_PATTERNS = {
    # Drug-related params
    "drug_name": {"type": "string", "description": "Drug name (brand or generic)", "required": True},
    "drug": {"type": "string", "description": "Drug name", "required": True},
    "event": {"type": "string", "description": "Adverse event or reaction term", "required": True},
    "reaction": {"type": "string", "description": "Adverse reaction (MedDRA preferred term)", "required": True},
    # Search params
    "query": {"type": "string", "description": "Search query", "required": True},
    "search_query": {"type": "string", "description": "Search terms", "required": True},
    "condition": {"type": "string", "description": "Medical condition or disease", "required": True},
    # Identifiers
    "rxcui": {"type": "string", "description": "RxNorm Concept Unique Identifier", "required": True},
    "nct_id": {"type": "string", "description": "ClinicalTrials.gov NCT identifier", "required": True},
    "pmid": {"type": "string", "description": "PubMed ID", "required": True},
    "set_id": {"type": "string", "description": "DailyMed SPL set ID", "required": True},
    # Common optional
    "limit": {"type": "integer", "description": "Maximum results to return", "required": False},
    "offset": {"type": "integer", "description": "Pagination offset", "required": False},
    "page": {"type": "integer", "description": "Page number", "required": False},
    "sort": {"type": "string", "description": "Sort order", "required": False},
    "format": {"type": "string", "description": "Output format", "required": False},
    # Computation params
    "a": {"type": "integer", "description": "Cases with drug AND event", "required": True},
    "b": {"type": "integer", "description": "Cases with drug WITHOUT event", "required": True},
    "c": {"type": "integer", "description": "Cases with event WITHOUT drug", "required": True},
    "d": {"type": "integer", "description": "Cases without drug or event", "required": True},
    "n": {"type": "integer", "description": "Total count", "required": True},
    # Generic
    "name": {"type": "string", "description": "Name to look up", "required": True},
    "id": {"type": "string", "description": "Identifier", "required": True},
    "category": {"type": "string", "description": "Category filter", "required": False},
    "type": {"type": "string", "description": "Type filter", "required": False},
}

# Tool prefix → default parameter if none specified
PREFIX_DEFAULTS = {
    "search-": [{"name": "query", **PARAM_PATTERNS["query"]}],
    "get-drug": [{"name": "drug_name", **PARAM_PATTERNS["drug_name"]}],
    "get-safety": [{"name": "drug_name", **PARAM_PATTERNS["drug_name"]}],
    "get-interactions": [{"name": "drug_name", **PARAM_PATTERNS["drug_name"]}],
    "get-adverse": [{"name": "drug_name", **PARAM_PATTERNS["drug_name"]}],
    "compute-": [{"name": "drug_name", **PARAM_PATTERNS["drug_name"]},
                 {"name": "event", **PARAM_PATTERNS["event"]}],
    "calculate-": [{"name": "drug_name", **PARAM_PATTERNS["drug_name"]},
                   {"name": "event", **PARAM_PATTERNS["event"]}],
    "get-trial": [{"name": "nct_id", **PARAM_PATTERNS["nct_id"]}],
    "get-article": [{"name": "pmid", **PARAM_PATTERNS["pmid"]}],
    "get-label": [{"name": "drug_name", **PARAM_PATTERNS["drug_name"]}],
}


def parse_tool_sig(sig: str) -> tuple[str, str, list[dict]]:
    """Parse a tool signature like 'get-info(drug_name, limit?:int=20): Description'.

    Returns (name, description, parameters).
    """
    # Match: name(params): description  OR  name: description
    m = re.match(r'^([\w-]+)\(([^)]*)\)\s*:\s*(.+)$', sig.strip())
    if m:
        name, param_str, desc = m.group(1), m.group(2), m.group(3)
        params = _parse_params(param_str)
        return name, desc.strip(), params

    m = re.match(r'^([\w-]+)\s*:\s*(.+)$', sig.strip())
    if m:
        name, desc = m.group(1), m.group(2)
        return name, desc.strip(), []

    # Bare name
    return sig.strip(), f"Tool: {sig.strip()}", []


def _parse_params(param_str: str) -> list[dict]:
    """Parse 'drug_name, limit?:int=20' into parameter dicts."""
    params = []
    for part in param_str.split(","):
        part = part.strip()
        if not part:
            continue

        required = True
        default = None
        ptype = "string"

        # Check for optional marker
        if "?" in part:
            part = part.replace("?", "")
            required = False

        # Check for default value
        if "=" in part:
            part, default = part.rsplit("=", 1)
            default = default.strip()
            required = False

        # Check for type annotation
        if ":" in part:
            part, ptype = part.rsplit(":", 1)
            ptype = ptype.strip()

        pname = part.strip()

        # Look up known param patterns
        if pname in PARAM_PATTERNS:
            p = {"name": pname, **PARAM_PATTERNS[pname]}
            p["required"] = required
            if ptype != "string":
                p["type"] = ptype
        else:
            p = {"name": pname, "type": ptype, "description": pname.replace("_", " ").title(), "required": required}

        if default is not None:
            p["default"] = default

        params.append(p)

    return params


def infer_params(tool_name: str) -> list[dict]:
    """Infer default parameters from tool name prefix."""
    for prefix, defaults in PREFIX_DEFAULTS.items():
        if tool_name.startswith(prefix):
            return [dict(p) for p in defaults]
    # Generic get-X → single id-like param
    if tool_name.startswith("get-"):
        suffix = tool_name[4:]
        return [{"name": "id", "type": "string",
                 "description": f"{suffix.replace('-', ' ').title()} identifier", "required": True}]
    return []


def build_output_schema(tool_name: str) -> dict:
    """Generate outputSchema based on tool name prefix."""
    base = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "ok | error | stub"}
        },
        "required": ["status"]
    }

    if tool_name.startswith(("search-", "list-")):
        base["properties"]["count"] = {"type": "integer"}
        base["properties"]["results"] = {"type": "array", "items": {"type": "object"}}
        base["required"].append("results")
    elif tool_name.startswith("get-"):
        base["properties"]["data"] = {"type": "object"}
    elif tool_name.startswith(("compute-", "calculate-")):
        base["properties"]["result"] = {"type": "object"}
        base["properties"]["method"] = {"type": "string"}
    elif tool_name.startswith(("assess-", "classify-", "score-")):
        base["properties"]["result"] = {"type": "object"}
        base["properties"]["classification"] = {"type": "string"}

    return base


# ---------------------------------------------------------------------------
# Config generation
# ---------------------------------------------------------------------------

def build_config(domain: str, title: str, description: str,
                 tools_spec: list, proxy: str = None, private: bool = False) -> dict:
    """Build a complete station config from tool specifications."""
    tools = []
    for spec in tools_spec:
        if isinstance(spec, str):
            name, desc, params = parse_tool_sig(spec)
        elif isinstance(spec, dict):
            # YAML dict: {"get-info": "Description"} or {"name": "get-info", ...}
            if "name" in spec:
                name = spec["name"]
                desc = spec.get("description", f"Tool: {name}")
                params = spec.get("parameters", [])
            else:
                # Single key-value
                name = list(spec.keys())[0]
                desc = spec[name]
                name, desc, params = parse_tool_sig(f"{name}: {desc}")
        else:
            continue

        # Normalize
        name = name.lower().replace("_", "-").replace(" ", "-").strip("-")

        # Infer params if none specified
        if not params:
            params = infer_params(name)

        tool = {
            "name": name,
            "description": desc,
            "parameters": params,
            "outputSchema": build_output_schema(name),
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        }
        tools.append(tool)

    config = {
        "domain": domain,
        "url_pattern": "/*",
        "title": title,
        "description": description,
        "tools": tools,
    }
    if proxy:
        config["proxy"] = proxy
    if private:
        config["private"] = True

    return config


# ---------------------------------------------------------------------------
# Proxy generation
# ---------------------------------------------------------------------------

def generate_proxy(domain: str, title: str, base_url: str, tools: list[dict]) -> str:
    """Generate a proxy Python script for a domain."""
    safe_domain = domain.replace(".", "_").replace("-", "_")
    handlers = []

    for tool in tools:
        name = tool["name"]
        fn_name = name.replace("-", "_")
        params = tool.get("parameters", [])
        required = [p["name"] for p in params if p.get("required")]

        if name.startswith(("search-", "list-")):
            handler = _gen_search_handler(fn_name, name, base_url, required, params)
        elif name.startswith("get-"):
            handler = _gen_get_handler(fn_name, name, base_url, required, params)
        elif name.startswith(("compute-", "calculate-", "assess-", "classify-", "score-")):
            handler = _gen_compute_handler(fn_name, name, base_url, required, params)
        else:
            handler = _gen_stub_handler(fn_name, name)

        handlers.append(handler)

    # Build dispatch map
    dispatch_entries = []
    for tool in tools:
        fn = tool["name"].replace("-", "_")
        dispatch_entries.append(f'    "{tool["name"]}": {fn},')

    dispatch_map = "\n".join(dispatch_entries)

    return textwrap.dedent(f'''\
#!/usr/bin/env python3
"""
{title} Proxy — NexVigilant Station

Domain: {domain}
Base URL: {base_url}

Reads JSON from stdin, dispatches to handler, writes JSON to stdout.
No external dependencies — stdlib only.
"""

import json
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

BASE_URL = "{base_url}"
REQUEST_TIMEOUT = 20
_RETRY_CODES = {{429, 503}}
_MAX_RETRIES = 3


def _fetch(url: str) -> dict:
    """HTTP GET with retry on 429/503."""
    req = urllib.request.Request(
        url,
        headers={{"User-Agent": "NexVigilant-FerroForge/1.0 (ferroforge@nexvigilant.com)"}},
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
            raise RuntimeError(f"HTTP {{exc.code}}: {{exc.reason}}") from exc
        except urllib.error.URLError as exc:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(0.2 * (3 ** attempt))
                last_exc = exc
                continue
            raise RuntimeError(f"Network error: {{exc.reason}}") from exc
    raise RuntimeError(f"Failed after {{_MAX_RETRIES}} retries: {{last_exc}}")


def _post(url: str, payload: dict) -> dict:
    """HTTP POST JSON with retry."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={{
            "User-Agent": "NexVigilant-FerroForge/1.0 (ferroforge@nexvigilant.com)",
            "Content-Type": "application/json",
        }},
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
            raise RuntimeError(f"HTTP {{exc.code}}: {{exc.reason}}") from exc
        except urllib.error.URLError as exc:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(0.2 * (3 ** attempt))
                last_exc = exc
                continue
            raise RuntimeError(f"Network error: {{exc.reason}}") from exc
    raise RuntimeError(f"Failed after {{_MAX_RETRIES}} retries: {{last_exc}}")


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

{"".join(handlers)}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

DISPATCH = {{
{dispatch_map}
}}


def main():
    try:
        raw = sys.stdin.read()
        envelope = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        json.dump({{"status": "error", "message": f"Invalid JSON: {{exc}}"}}, sys.stdout)
        return

    tool = envelope.get("tool", "")
    args = envelope.get("arguments", envelope.get("args", {{}}))

    handler = DISPATCH.get(tool)
    if not handler:
        json.dump({{"status": "error", "message": f"Unknown tool: {{tool}}"}}, sys.stdout)
        return

    try:
        result = handler(args)
        json.dump(result, sys.stdout)
    except Exception as exc:
        json.dump({{"status": "error", "message": str(exc)}}, sys.stdout)


if __name__ == "__main__":
    main()
''')


def _gen_search_handler(fn_name: str, tool_name: str, base_url: str,
                        required: list, params: list) -> str:
    """Generate a search handler stub."""
    return f'''
def {fn_name}(args: dict) -> dict:
    """Handler for {tool_name}."""
    query = args.get("query", "")
    limit = int(args.get("limit", 20))
    # TODO: Wire to real API endpoint
    # url = f"{{BASE_URL}}/search?q={{_quote(query)}}&limit={{limit}}"
    # data = _fetch(url)
    return {{"status": "stub", "tool": "{tool_name}", "query": query,
            "message": "Wire to real API — edit {fn_name}() in this proxy"}}

'''


def _gen_get_handler(fn_name: str, tool_name: str, base_url: str,
                     required: list, params: list) -> str:
    """Generate a get handler stub."""
    primary = required[0] if required else "id"
    return f'''
def {fn_name}(args: dict) -> dict:
    """Handler for {tool_name}."""
    key = args.get("{primary}", "")
    # TODO: Wire to real API endpoint
    # url = f"{{BASE_URL}}/{{_quote(key)}}"
    # data = _fetch(url)
    return {{"status": "stub", "tool": "{tool_name}", "{primary}": key,
            "message": "Wire to real API — edit {fn_name}() in this proxy"}}

'''


def _gen_compute_handler(fn_name: str, tool_name: str, base_url: str,
                         required: list, params: list) -> str:
    """Generate a compute handler stub."""
    return f'''
def {fn_name}(args: dict) -> dict:
    """Handler for {tool_name}."""
    # TODO: Implement computation logic
    return {{"status": "stub", "tool": "{tool_name}", "args": args,
            "message": "Implement computation — edit {fn_name}() in this proxy"}}

'''


def _gen_stub_handler(fn_name: str, tool_name: str) -> str:
    """Generate a generic stub handler."""
    return f'''
def {fn_name}(args: dict) -> dict:
    """Handler for {tool_name}."""
    return {{"status": "stub", "tool": "{tool_name}", "args": args,
            "message": "Implement handler — edit {fn_name}() in this proxy"}}

'''


# ---------------------------------------------------------------------------
# Dispatch.py wiring
# ---------------------------------------------------------------------------

def check_dispatch_wiring(domain: str) -> bool:
    """Check if domain is already wired in dispatch.py."""
    dispatch_path = SCRIPTS_DIR / "dispatch.py"
    content = dispatch_path.read_text()
    prefix = domain.replace(".", "_").replace("-", "_")
    return prefix in content


def wire_dispatch(domain: str, proxy_filename: str) -> str:
    """Return the line to add to PARAMETER_ALIGNMENT in dispatch.py."""
    proxy_name = proxy_filename
    return f'    "{proxy_name}": {{}},  # {domain} — auto-wired by forge.py'


# ---------------------------------------------------------------------------
# YAML spec loading
# ---------------------------------------------------------------------------

def load_yaml_spec(path: str) -> dict:
    """Load a YAML spec file. Falls back to JSON if PyYAML not available."""
    text = Path(path).read_text()
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        # Try JSON fallback
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Manual minimal YAML parser for our simple format
            return _mini_yaml_parse(text)


def _mini_yaml_parse(text: str) -> dict:
    """Minimal YAML-like parser for forge specs. Handles our specific format."""
    # This is intentionally simple — for complex YAML, install PyYAML
    lines = text.split("\n")
    result = {"configs": []}
    current_config = None
    in_tools = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())

        if stripped.startswith("- domain:"):
            if current_config:
                result["configs"].append(current_config)
            current_config = {"domain": stripped.split(":", 1)[1].strip().strip('"').strip("'")}
            in_tools = False
        elif current_config and not in_tools:
            if stripped.startswith("title:"):
                current_config["title"] = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            elif stripped.startswith("description:"):
                current_config["description"] = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            elif stripped.startswith("base_url:"):
                current_config["base_url"] = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            elif stripped.startswith("proxy:"):
                val = stripped.split(":", 1)[1].strip()
                current_config["proxy"] = val.lower() not in ("false", "no", "0")
            elif stripped.startswith("private:"):
                val = stripped.split(":", 1)[1].strip()
                current_config["private"] = val.lower() in ("true", "yes", "1")
            elif stripped == "tools:":
                in_tools = True
                current_config["tools"] = []
        elif in_tools and stripped.startswith("- "):
            tool_str = stripped[2:].strip().strip('"').strip("'")
            current_config.setdefault("tools", []).append(tool_str)

    if current_config:
        result["configs"].append(current_config)

    return result


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def audit():
    """Audit configs for missing proxies, dispatch gaps, schema issues."""
    configs = sorted(CONFIGS_DIR.glob("*.json"))
    proxy_scripts = {f.stem: f for f in SCRIPTS_DIR.glob("*_proxy.py")}
    dispatch_content = (SCRIPTS_DIR / "dispatch.py").read_text()

    issues = []
    stats = {"configs": 0, "tools": 0, "rust_native": 0, "proxied": 0, "no_proxy": 0}

    for config_path in configs:
        with open(config_path) as f:
            config = json.load(f)

        domain = config["domain"]
        tools = config.get("tools", [])
        proxy = config.get("proxy", "")
        stats["configs"] += 1
        stats["tools"] += len(tools)

        if proxy == "rust-native":
            stats["rust_native"] += 1
            continue

        if not proxy or proxy == "(none)":
            stats["no_proxy"] += 1
            issues.append(f"NO_PROXY: {config_path.name} ({domain}) — no proxy defined")
            continue

        stats["proxied"] += 1

        # Check proxy file exists
        if proxy.startswith("scripts/"):
            proxy_path = FERROFORGE / proxy
            if not proxy_path.exists() and proxy != "scripts/dispatch.py":
                issues.append(f"MISSING_PROXY: {config_path.name} references {proxy} — file not found")

        # Check dispatch wiring
        prefix = domain.replace(".", "_").replace("-", "_")
        if "dispatch.py" in proxy and prefix not in dispatch_content:
            issues.append(f"DISPATCH_GAP: {config_path.name} ({domain}) — prefix '{prefix}' not in dispatch.py")

        # Check tools have outputSchema
        for tool in tools:
            if "outputSchema" not in tool:
                issues.append(f"NO_SCHEMA: {config_path.name} tool '{tool['name']}' missing outputSchema")
            if "annotations" not in tool:
                issues.append(f"NO_ANNOTATIONS: {config_path.name} tool '{tool['name']}' missing annotations")

    return stats, issues


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_from_spec(args):
    """Generate configs (and optionally proxies) from a YAML spec file."""
    spec = load_yaml_spec(args.spec_file)
    results = []

    for entry in spec.get("configs", []):
        domain = entry["domain"]
        title = entry.get("title", domain)
        description = entry.get("description", title)
        tools_spec = entry.get("tools", [])
        base_url = entry.get("base_url", f"https://{domain}")
        want_proxy = entry.get("proxy", False)
        private = entry.get("private", False)

        # Determine proxy value
        if want_proxy is True:
            safe = domain.replace(".", "_").replace("-", "_")
            proxy_filename = f"{safe}_proxy.py"
            proxy_value = f"scripts/{proxy_filename}"
        elif isinstance(want_proxy, str):
            proxy_value = want_proxy
            proxy_filename = None
        else:
            proxy_value = "rust-native"
            proxy_filename = None

        # Build config
        config = build_config(domain, title, description, tools_spec, proxy_value, private)

        # Write config
        config_filename = domain.replace(".", "-") + ".json"
        if domain.startswith("www."):
            config_filename = domain[4:].replace(".", "-") + ".json"
        config_path = CONFIGS_DIR / config_filename
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
            f.write("\n")

        result = {"config": str(config_path), "tools": len(config["tools"])}

        # Generate proxy if requested
        if want_proxy is True and proxy_filename:
            proxy_code = generate_proxy(domain, title, base_url, config["tools"])
            proxy_path = SCRIPTS_DIR / proxy_filename
            if not proxy_path.exists() or args.overwrite:
                with open(proxy_path, "w") as f:
                    f.write(proxy_code)
                os.chmod(proxy_path, 0o755)
                result["proxy"] = str(proxy_path)
            else:
                result["proxy_skipped"] = f"{proxy_path} exists (use --overwrite)"

            # Check dispatch wiring
            if not check_dispatch_wiring(domain):
                result["dispatch_note"] = wire_dispatch(domain, proxy_filename)

        results.append(result)
        print(f"  {config_path.name}: {len(config['tools'])} tools", end="")
        if "proxy" in result:
            print(f" + proxy", end="")
        print()

    print(f"\nGenerated {len(results)} configs, {sum(r['tools'] for r in results)} tools total")

    # Show dispatch wiring notes
    notes = [r["dispatch_note"] for r in results if "dispatch_note" in r]
    if notes:
        print(f"\nAdd to dispatch.py PARAMETER_ALIGNMENT:")
        for note in notes:
            print(f"  {note}")

    return results


def cmd_audit(args):
    """Run audit and print results."""
    stats, issues = audit()
    print(f"Station: {stats['configs']} configs, {stats['tools']} tools")
    print(f"  Rust-native: {stats['rust_native']}, Proxied: {stats['proxied']}, No proxy: {stats['no_proxy']}")

    if issues:
        print(f"\n{len(issues)} issues:")
        for issue in issues:
            print(f"  {issue}")
    else:
        print("\nNo issues found.")


def cmd_stats(args):
    """Print inventory stats."""
    configs = sorted(CONFIGS_DIR.glob("*.json"))
    total_tools = 0
    domains = {"rust_native": [], "proxied": [], "other": []}

    for config_path in configs:
        with open(config_path) as f:
            config = json.load(f)
        n = len(config.get("tools", []))
        total_tools += n
        proxy = config.get("proxy", "")
        if proxy == "rust-native":
            domains["rust_native"].append((config["domain"], n))
        elif proxy:
            domains["proxied"].append((config["domain"], n))
        else:
            domains["other"].append((config["domain"], n))

    proxy_scripts = list(SCRIPTS_DIR.glob("*_proxy.py"))

    print(f"Configs: {len(configs)} | Tools: {total_tools} | Proxy scripts: {len(proxy_scripts)}")
    print(f"  Rust-native: {len(domains['rust_native'])} configs ({sum(n for _, n in domains['rust_native'])} tools)")
    print(f"  Proxied:     {len(domains['proxied'])} configs ({sum(n for _, n in domains['proxied'])} tools)")
    if domains["other"]:
        print(f"  No proxy:    {len(domains['other'])} configs ({sum(n for _, n in domains['other'])} tools)")


def cmd_quick(args):
    """Quick interactive config generation."""
    domain = args.domain
    title = args.title or domain
    description = args.description or title
    base_url = args.base_url or f"https://{domain}"

    print(f"Quick forge: {domain}")
    print(f"Enter tools (one per line, empty to finish):")
    print(f"  Format: tool-name(param1, param2?:int): Description")
    print(f"  Simple: search-drugs: Search for drugs by name")
    print()

    tools_spec = []
    while True:
        try:
            line = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        tools_spec.append(line)

    if not tools_spec:
        print("No tools specified. Aborted.")
        return

    config = build_config(domain, title, description, tools_spec,
                         proxy=f"scripts/{domain.replace('.', '_').replace('-', '_')}_proxy.py" if args.proxy else "rust-native")
    config_path = CONFIGS_DIR / f"{domain.replace('.', '-')}.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    print(f"\nWrote {config_path} ({len(config['tools'])} tools)")

    if args.proxy:
        proxy_code = generate_proxy(domain, title, base_url, config["tools"])
        proxy_path = SCRIPTS_DIR / f"{domain.replace('.', '_').replace('-', '_')}_proxy.py"
        with open(proxy_path, "w") as f:
            f.write(proxy_code)
        os.chmod(proxy_path, 0o755)
        print(f"Wrote {proxy_path}")


def main():
    parser = argparse.ArgumentParser(description="Forge — rapid Station config + proxy generator")
    sub = parser.add_subparsers(dest="command")

    # from-spec
    sp = sub.add_parser("from-spec", help="Generate from YAML/JSON spec file")
    sp.add_argument("spec_file", help="Path to spec YAML/JSON")
    sp.add_argument("--overwrite", action="store_true", help="Overwrite existing proxy scripts")

    # quick
    q = sub.add_parser("quick", help="Quick interactive config generation")
    q.add_argument("--domain", required=True)
    q.add_argument("--title", default=None)
    q.add_argument("--description", default=None)
    q.add_argument("--base-url", default=None)
    q.add_argument("--proxy", action="store_true", help="Also generate proxy script")

    # audit
    sub.add_parser("audit", help="Audit configs for issues")

    # stats
    sub.add_parser("stats", help="Print inventory stats")

    args = parser.parse_args()

    if args.command == "from-spec":
        cmd_from_spec(args)
    elif args.command == "quick":
        cmd_quick(args)
    elif args.command == "audit":
        cmd_audit(args)
    elif args.command == "stats":
        cmd_stats(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
