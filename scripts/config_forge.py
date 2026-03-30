#!/usr/bin/env python3
"""Config Forge — Generate NexVigilant Station configs from domain descriptions.

Accelerates config creation by generating the full JSON config file
from a minimal domain specification. Handles:
  - Config JSON with outputSchema on all tools
  - Proxy wiring to the unified science or PV proxy
  - Hub deployment payload generation
  - Tool name normalization (kebab-case)

Usage:
  python3 config_forge.py --domain "science.nexvigilant.com" \
    --url-pattern "/proteomics/*" \
    --title "Proteomics & Mass Spec" \
    --description "Protein-level analysis from PRIDE and ProteomeXchange" \
    --proxy "scripts/science_proxy.py" \
    --tools "search-datasets:Search proteomics datasets by protein or tissue" \
    --tools "get-protein-quantification:Get protein abundance quantification data" \
    --tools "search-modifications:Search post-translational modifications"

  python3 config_forge.py --from-spec spec.json   # Batch from spec file
  python3 config_forge.py deploy configs/my-config.json                    # Deploy (POST or 409->PATCH)
  python3 config_forge.py deploy configs/my-config.json --hub-id UUID      # Direct PATCH (at cap)
  python3 config_forge.py batch-deploy hub-mapping.json                    # Batch PATCH all configs
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error


def normalize_tool_name(name: str) -> str:
    """Ensure tool name is kebab-case."""
    return name.lower().replace("_", "-").replace(" ", "-").strip("-")


def build_output_schema(tool_name: str) -> dict:
    """Generate default outputSchema based on tool name prefix."""
    base = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "ok | error"}
        },
        "required": ["status"]
    }

    if tool_name.startswith("search-") or tool_name.startswith("list-"):
        base["properties"]["count"] = {"type": "integer"}
        base["properties"]["results"] = {"type": "array", "items": {"type": "object"}}
        base["required"].append("results")
    elif tool_name.startswith("get-"):
        base["properties"]["data"] = {"type": "object"}
    elif tool_name.startswith("compute-") or tool_name.startswith("calculate-"):
        base["properties"]["result"] = {"type": "object"}
        base["properties"]["method"] = {"type": "string"}

    return base


def build_config(domain: str, url_pattern: str, title: str,
                 description: str, tools_spec: list, proxy: str = None) -> dict:
    """Build a complete station config from a tool specification list."""
    tools = []
    for spec in tools_spec:
        if isinstance(spec, str):
            # "name:description" format
            parts = spec.split(":", 1)
            name = normalize_tool_name(parts[0])
            desc = parts[1].strip() if len(parts) > 1 else f"Tool: {name}"
            params = []
        elif isinstance(spec, dict):
            name = normalize_tool_name(spec["name"])
            desc = spec.get("description", f"Tool: {name}")
            params = spec.get("parameters", [])
        else:
            continue

        tool = {
            "name": name,
            "description": desc,
            "parameters": params,
            "outputSchema": build_output_schema(name),
        }
        tools.append(tool)

    config = {
        "domain": domain,
        "url_pattern": url_pattern,
        "title": title,
        "description": description,
        "tools": tools,
    }
    if proxy:
        config["proxy"] = proxy

    return config


def generate_hub_payload(config: dict) -> dict:
    """Transform a local config into a WebMCP Hub API payload."""
    disclaimer = (
        "DISCLAIMER: This WebMCP configuration was developed by NexVigilant, LLC "
        "and is provided as a community resource to assist AI agents in navigating "
        "pharmacovigilance and drug research tools. NexVigilant is not responsible for, "
        "and does not officially endorse third-party use of this configuration, and "
        "expressly disclaims any and all liability for damages of any kind arising out "
        "of the use, reference to, or reliance upon any information or actions performed "
        "through this resource. No guarantee is provided that the content is correct, "
        "accurate, complete, up-to-date, or that the underlying site structure has not "
        "changed. This tool is for educational and professional development purposes only "
        "and does not constitute medical or regulatory advice. Built by NexVigilant "
        "(https://nexvigilant.com) — Empowerment Through Vigilance."
    )

    domain = config["domain"]
    url_pattern = config.get("url_pattern", "/*")
    if url_pattern.startswith("/"):
        url_pattern = f"{domain}{url_pattern.rstrip('/*')}/**"

    hub_tools = []
    for t in config["tools"]:
        station_prefix = "[NexVigilant Science Station]" if "science" in domain else "[NexVigilant Station]"
        # Build inputSchema from local parameter definitions
        input_props = {}
        input_required = []
        for param in t.get("parameters", []):
            input_props[param["name"]] = {
                "type": param.get("type", "string"),
                "description": param.get("description", ""),
            }
            if param.get("required"):
                input_required.append(param["name"])
        input_schema: dict = {"type": "object", "properties": input_props}
        if input_required:
            input_schema["required"] = input_required

        hub_tools.append({
            "name": t["name"],
            "description": f"{station_prefix} {t['description']}",
            "inputSchema": input_schema,
            "execution": {
                "selector": "body",
                "autosubmit": False,
                "resultExtract": "text",
                "resultSelector": "body",
            },
            "annotations": {
                "readOnlyHint": "true",
                "idempotentHint": "true",
                "destructiveHint": "false",
            },
        })

    return {
        "domain": domain,
        "urlPattern": url_pattern,
        "title": f"{station_prefix} {config['title']}",
        "description": f"{config['description']} {disclaimer}",
        "tools": hub_tools,
    }


def deploy_to_hub(config_path: str, api_key: str = None, hub_id: str = None) -> dict:
    """Deploy a local config file to the WebMCP Hub. Creates or updates.

    Args:
        config_path: Path to local config JSON file.
        api_key: Hub API key (falls back to HUB_API_KEY env var).
        hub_id: If provided, PATCH directly to this Hub config ID (skips POST).
                Required when at the 50-config cap since POST returns 403.
    """
    if not api_key:
        api_key = os.environ.get("HUB_API_KEY", "")
    if not api_key:
        return {"status": "error", "message": "HUB_API_KEY not set"}

    hub_url = os.environ.get("HUB_URL", "https://www.webmcp-hub.com")

    with open(config_path) as f:
        config = json.load(f)

    payload = generate_hub_payload(config)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Direct PATCH when hub_id is known (works at cap, skips POST)
    if hub_id:
        return _patch_config(hub_id, payload, headers, hub_url)

    # Try POST (create) first
    req = urllib.request.Request(
        f"{hub_url}/api/configs",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read())
        return {"status": "created", "config_id": result["id"], "tools": len(payload["tools"])}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if e.code == 409:
            # 409 Conflict — config exists. Extract existing ID and PATCH.
            try:
                conflict = json.loads(body)
                existing_id = conflict.get("existingId", "")
            except (json.JSONDecodeError, ValueError):
                return {"status": "error", "code": 409, "message": "Config exists but could not parse existingId"}
            if not existing_id:
                return {"status": "error", "code": 409, "message": "Config exists but no existingId returned"}
            return _patch_config(existing_id, payload, headers, hub_url)
        return {"status": "error", "code": e.code, "message": body[:200]}


def _patch_config(hub_id: str, payload: dict, headers: dict, hub_url: str = "https://www.webmcp-hub.com") -> dict:
    """PATCH an existing Hub config by ID."""
    req = urllib.request.Request(
        f"{hub_url}/api/configs/{hub_id}",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="PATCH",
    )
    try:
        resp = urllib.request.urlopen(req)
        json.loads(resp.read())
        return {"status": "updated", "config_id": hub_id, "tools": len(payload["tools"])}
    except urllib.error.HTTPError as e:
        return {"status": "error", "code": e.code, "message": e.read().decode()[:200]}


def from_spec_file(spec_path: str) -> list:
    """Generate multiple configs from a spec file."""
    with open(spec_path) as f:
        spec = json.load(f)

    results = []
    for entry in spec.get("configs", []):
        config = build_config(
            domain=entry["domain"],
            url_pattern=entry.get("url_pattern", "/*"),
            title=entry["title"],
            description=entry["description"],
            tools_spec=entry["tools"],
            proxy=entry.get("proxy"),
        )
        out_path = os.path.join(
            os.path.dirname(spec_path) or ".",
            f"configs/{normalize_tool_name(entry['title']).replace(' ', '-')}.json",
        )
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(config, f, indent=2)
        results.append({"path": out_path, "tools": len(config["tools"])})

    return results


def discover_hub_mapping(api_key: str = None) -> dict:
    """Fetch all Hub configs and build a local-filename → hub-id mapping."""
    if not api_key:
        api_key = os.environ.get("HUB_API_KEY", "")
    if not api_key:
        return {}

    hub_url = os.environ.get("HUB_URL", "https://www.webmcp-hub.com")
    headers = {"Authorization": f"Bearer {api_key}"}
    all_configs = []
    for page in range(1, 10):
        url = f"{hub_url}/api/configs?page={page}&limit=50"
        req = urllib.request.Request(url, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read())
            configs = data if isinstance(data, list) else data.get("configs", data.get("data", []))
            if not configs:
                break
            all_configs.extend(configs)
            if len(configs) < 50:
                break
        except urllib.error.HTTPError:
            break

    # Match hub configs to local config files by title
    config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "configs")
    mapping = {}
    for hub_config in all_configs:
        if not isinstance(hub_config, dict):
            continue
        hub_title = hub_config.get("title", "")
        hub_id = hub_config.get("id", "")
        # Try matching by generating hub payload for each local config
        for fname in os.listdir(config_dir):
            if not fname.endswith(".json") or fname in mapping:
                continue
            with open(os.path.join(config_dir, fname)) as f:
                local_config = json.load(f)
            payload = generate_hub_payload(local_config)
            if payload["title"] == hub_title:
                mapping[fname] = hub_id
                break

    return mapping


def main():
    parser = argparse.ArgumentParser(description="Config Forge — generate NexVigilant Station configs")
    sub = parser.add_subparsers(dest="command")

    # Generate command
    gen = sub.add_parser("generate", help="Generate a config from CLI args")
    gen.add_argument("--domain", required=True)
    gen.add_argument("--url-pattern", default="/*")
    gen.add_argument("--title", required=True)
    gen.add_argument("--description", required=True)
    gen.add_argument("--proxy", default=None)
    gen.add_argument("--tools", action="append", default=[], help="name:description pairs")
    gen.add_argument("--output", "-o", default=None, help="Output file path")

    # From spec
    batch = sub.add_parser("batch", help="Generate from spec JSON file")
    batch.add_argument("spec_file")

    # Deploy
    deploy = sub.add_parser("deploy", help="Deploy config to WebMCP Hub")
    deploy.add_argument("config_file")
    deploy.add_argument("--hub-id", default=None, help="PATCH directly to this Hub config ID (required at cap)")

    # Batch deploy with mapping
    batch_deploy = sub.add_parser("batch-deploy", help="Deploy all configs using a JSON mapping file")
    batch_deploy.add_argument("mapping_file", help="JSON file: {\"config_name.json\": \"hub-uuid\", ...}")

    # Discover mapping
    sub.add_parser("discover", help="Fetch Hub configs and generate hub-mapping.json")

    # Hub payload preview
    preview = sub.add_parser("preview", help="Preview hub payload without deploying")
    preview.add_argument("config_file")

    args = parser.parse_args()

    if args.command == "generate":
        config = build_config(
            args.domain, args.url_pattern, args.title,
            args.description, args.tools, args.proxy,
        )
        output = json.dumps(config, indent=2)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"Config written to {args.output} ({len(config['tools'])} tools)")
        else:
            print(output)

    elif args.command == "batch":
        results = from_spec_file(args.spec_file)
        for r in results:
            print(f"Generated: {r['path']} ({r['tools']} tools)")

    elif args.command == "deploy":
        result = deploy_to_hub(args.config_file, hub_id=args.hub_id)
        print(json.dumps(result, indent=2))

    elif args.command == "batch-deploy":
        with open(args.mapping_file) as f:
            mapping = json.load(f)
        config_dir = os.path.join(os.path.dirname(args.mapping_file) or ".", "configs")
        if not os.path.isdir(config_dir):
            config_dir = os.path.join(os.path.dirname(os.path.abspath(args.mapping_file)), "..", "configs")
        success, failed = 0, 0
        for config_name, hub_id in mapping.items():
            config_path = os.path.join(config_dir, config_name)
            if not os.path.exists(config_path):
                config_path = os.path.join("configs", config_name)
            result = deploy_to_hub(config_path, hub_id=hub_id)
            status = result.get("status", "error")
            if status in ("updated", "created"):
                print(f"  OK  {config_name:30s} -> {result.get('tools', '?')} tools")
                success += 1
            else:
                print(f"  ERR {config_name:30s} -> {result.get('message', '')[:80]}")
                failed += 1
        print(f"\nBatch: {success} ok, {failed} failed, {success + failed} total")

    elif args.command == "discover":
        mapping = discover_hub_mapping()
        if mapping:
            out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hub-mapping.json")
            with open(out_path, "w") as f:
                json.dump(mapping, f, indent=2)
                f.write("\n")
            print(f"Discovered {len(mapping)} config mappings -> {out_path}")
            for fname, hub_id in sorted(mapping.items()):
                print(f"  {fname:30s} -> {hub_id[:12]}...")
        else:
            print("No mappings discovered (check HUB_API_KEY)")

    elif args.command == "preview":
        with open(args.config_file) as f:
            config = json.load(f)
        payload = generate_hub_payload(config)
        print(json.dumps(payload, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
