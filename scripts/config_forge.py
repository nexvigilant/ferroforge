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
  python3 config_forge.py --hub-deploy configs/my-config.json  # Deploy to hub
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
        hub_tools.append({
            "name": t["name"],
            "description": f"{station_prefix} {t['description']}",
            "inputSchema": {"type": "object", "properties": {}},
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


def deploy_to_hub(config_path: str, api_key: str = None) -> dict:
    """Deploy a local config file to the WebMCP Hub. Creates or updates."""
    if not api_key:
        api_key = os.environ.get("HUB_API_KEY", "")
    if not api_key:
        return {"status": "error", "message": "HUB_API_KEY not set"}

    with open(config_path) as f:
        config = json.load(f)

    payload = generate_hub_payload(config)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Try POST (create) first
    req = urllib.request.Request(
        "https://www.webmcp-hub.com/api/configs",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read())
        return {"status": "created", "config_id": result["id"], "tools": len(payload["tools"])}
    except urllib.error.HTTPError as e:
        if e.code != 409:
            return {"status": "error", "code": e.code, "message": e.read().decode()[:200]}

        # 409 Conflict — config exists. Extract existing ID and PUT to update.
        try:
            conflict = json.loads(e.read().decode())
            existing_id = conflict.get("existingId", "")
        except (json.JSONDecodeError, ValueError):
            return {"status": "error", "code": 409, "message": "Config exists but could not parse existingId"}

        if not existing_id:
            return {"status": "error", "code": 409, "message": "Config exists but no existingId returned"}

        update_req = urllib.request.Request(
            f"https://www.webmcp-hub.com/api/configs/{existing_id}",
            data=json.dumps(payload).encode(),
            headers=headers,
            method="PATCH",
        )
        try:
            update_resp = urllib.request.urlopen(update_req)
            update_result = json.loads(update_resp.read())
            return {"status": "updated", "config_id": existing_id, "tools": len(payload["tools"])}
        except urllib.error.HTTPError as ue:
            return {"status": "error", "code": ue.code, "message": ue.read().decode()[:200]}


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
        result = deploy_to_hub(args.config_file)
        print(json.dumps(result, indent=2))

    elif args.command == "preview":
        with open(args.config_file) as f:
            config = json.load(f)
        payload = generate_hub_payload(config)
        print(json.dumps(payload, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
