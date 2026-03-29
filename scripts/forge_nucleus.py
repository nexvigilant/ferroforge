#!/usr/bin/env python3
"""
Forge Nucleus — Generate Next.js 16 page scaffolds from Station configs.

Takes Station config JSON → generates TypeScript page components + route files
for the Nucleus portal. Follows the Anatomy/Physiology/Nervous System doctrine:
  - Anatomy (UI): For NexVigilants wizard pages
  - Physiology (Logic): Microgram references + pv-compute client calls
  - Nervous System (Transport): MCP tool bindings

Usage:
  python3 forge_nucleus.py scaffold --config configs/pv-compute.json
  python3 forge_nucleus.py scaffold --domain "pv-compute.nexvigilant.com"
  python3 forge_nucleus.py batch                    # Scaffold ALL uncovered configs
  python3 forge_nucleus.py batch --dry-run          # Preview what would be generated
  python3 forge_nucleus.py coverage                 # Show which configs have pages

Output structure (per config):
  src/app/vigilance/{domain}/page.tsx       — Route page (server component)
  src/app/vigilance/{domain}/components/    — Client components
    tool-cards.tsx                           — Tool card grid
    tool-form.tsx                            — Interactive tool form
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
NUCLEUS = Path.home() / "Projects/Active/nucleus"
VIGILANCE_DIR = NUCLEUS / "src/app/vigilance"


# ---------------------------------------------------------------------------
# Naming conventions
# ---------------------------------------------------------------------------

def domain_to_slug(domain: str) -> str:
    """Convert domain to URL slug: pv-compute.nexvigilant.com → pv-compute"""
    slug = domain.replace(".nexvigilant.com", "").replace("www.", "")
    slug = slug.replace(".", "-")
    return slug


def domain_to_pascal(domain: str) -> str:
    """Convert domain to PascalCase: pv-compute.nexvigilant.com → PvCompute"""
    slug = domain_to_slug(domain)
    return "".join(word.capitalize() for word in slug.split("-"))


def tool_to_label(name: str) -> str:
    """Convert tool name to human label: search-drugs → Search Drugs"""
    return name.replace("-", " ").title()


def tool_to_camel(name: str) -> str:
    """Convert tool name to camelCase: search-drugs → searchDrugs"""
    parts = name.split("-")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


# ---------------------------------------------------------------------------
# Page generation
# ---------------------------------------------------------------------------

def generate_page_tsx(config: dict) -> str:
    """Generate the route page.tsx (server component)."""
    domain = config["domain"]
    title = config["title"]
    description = config["description"]
    slug = domain_to_slug(domain)
    pascal = domain_to_pascal(domain)
    tool_count = len(config.get("tools", []))

    return textwrap.dedent(f'''\
import {{ Metadata }} from "next/metadata"
import {{ ToolCards }} from "./components/tool-cards"

export const metadata: Metadata = {{
  title: "{title} | NexVigilant",
  description: "{description[:120]}",
}}

export default function {pascal}Page() {{
  return (
    <div className="container mx-auto px-4 py-8 max-w-6xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight text-foreground">
          {title}
        </h1>
        <p className="mt-2 text-muted-foreground max-w-2xl">
          {description[:200]}
        </p>
        <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
          <span className="inline-flex items-center rounded-md bg-primary/10 px-2 py-1 text-xs font-medium text-primary">
            {tool_count} tools
          </span>
          <span className="inline-flex items-center rounded-md bg-muted px-2 py-1 text-xs font-medium">
            {slug}
          </span>
        </div>
      </div>
      <ToolCards />
    </div>
  )
}}
''')


def generate_tool_cards(config: dict) -> str:
    """Generate the tool-cards.tsx client component."""
    domain = config["domain"]
    tools = config.get("tools", [])
    pascal = domain_to_pascal(domain)

    tool_entries = []
    for tool in tools:
        name = tool["name"]
        desc = tool.get("description", name).replace('"', '\\"')
        params = tool.get("parameters", [])
        param_names = [p["name"] for p in params if p.get("required")]
        label = tool_to_label(name)

        tool_entries.append(f'''\
    {{
      name: "{name}",
      label: "{label}",
      description: "{desc[:120]}",
      params: [{', '.join(f'"{p}"' for p in param_names)}],
    }}''')

    tools_array = ",\n".join(tool_entries)

    return textwrap.dedent(f'''\
"use client"

import {{ useState }} from "react"
import {{ Card, CardContent, CardDescription, CardHeader, CardTitle }} from "@/components/ui/card"
import {{ Button }} from "@/components/ui/button"
import {{ Input }} from "@/components/ui/input"
import {{ Badge }} from "@/components/ui/badge"

interface ToolDef {{
  name: string
  label: string
  description: string
  params: string[]
}}

const TOOLS: ToolDef[] = [
{tools_array}
]

export function ToolCards() {{
  const [search, setSearch] = useState("")
  const [selectedTool, setSelectedTool] = useState<string | null>(null)

  const filtered = TOOLS.filter(
    (t) =>
      t.label.toLowerCase().includes(search.toLowerCase()) ||
      t.description.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="space-y-6">
      <Input
        placeholder="Search tools..."
        value={{search}}
        onChange={{(e) => setSearch(e.target.value)}}
        className="max-w-sm"
      />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {{filtered.map((tool) => (
          <Card
            key={{tool.name}}
            className={{`cursor-pointer transition-colors hover:border-primary ${{
              selectedTool === tool.name ? "border-primary bg-primary/5" : ""
            }}`}}
            onClick={{() => setSelectedTool(tool.name === selectedTool ? null : tool.name)}}
          >
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">
                {{tool.label}}
              </CardTitle>
              <CardDescription className="text-sm line-clamp-2">
                {{tool.description}}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-1">
                {{tool.params.map((p) => (
                  <Badge key={{p}} variant="secondary" className="text-xs">
                    {{p}}
                  </Badge>
                ))}}
                {{tool.params.length === 0 && (
                  <Badge variant="outline" className="text-xs">no params</Badge>
                )}}
              </div>
            </CardContent>
          </Card>
        ))}}
      </div>

      {{filtered.length === 0 && (
        <p className="text-center text-muted-foreground py-8">
          No tools match your search.
        </p>
      )}}
    </div>
  )
}}
''')


def generate_tool_form(config: dict) -> str:
    """Generate the tool-form.tsx client component for interactive tool execution."""
    domain = config["domain"]
    tools = config.get("tools", [])
    pascal = domain_to_pascal(domain)
    station_domain = domain.replace(".", "_").replace("-", "_")

    return textwrap.dedent(f'''\
"use client"

import {{ useState }} from "react"
import {{ Card, CardContent, CardHeader, CardTitle }} from "@/components/ui/card"
import {{ Button }} from "@/components/ui/button"
import {{ Input }} from "@/components/ui/input"
import {{ Label }} from "@/components/ui/label"

interface ToolFormProps {{
  toolName: string
  params: {{ name: string; type: string; description: string; required: boolean }}[]
}}

export function ToolForm({{ toolName, params }}: ToolFormProps) {{
  const [values, setValues] = useState<Record<string, string>>({{}})
  const [result, setResult] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async () => {{
    setLoading(true)
    setResult(null)
    try {{
      // Call via pv-compute client-side or API route
      const res = await fetch("/api/station/call", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          tool: `{station_domain}_${{toolName.replace(/-/g, "_")}}`,
          arguments: values,
        }}),
      }})
      const data = await res.json()
      setResult(JSON.stringify(data, null, 2))
    }} catch (err) {{
      setResult(`Error: ${{err}}`)
    }} finally {{
      setLoading(false)
    }}
  }}

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">{{toolName.replace(/-/g, " ").replace(/\\b\\w/g, (c: string) => c.toUpperCase())}}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {{params.map((p) => (
          <div key={{p.name}} className="space-y-1">
            <Label htmlFor={{p.name}}>
              {{p.name}} {{p.required && <span className="text-destructive">*</span>}}
            </Label>
            <Input
              id={{p.name}}
              placeholder={{p.description}}
              value={{values[p.name] || ""}}
              onChange={{(e) => setValues((v) => ({{ ...v, [p.name]: e.target.value }}))}}
            />
          </div>
        ))}}
        <Button onClick={{handleSubmit}} disabled={{loading}}>
          {{loading ? "Running..." : "Execute"}}
        </Button>
        {{result && (
          <pre className="mt-4 p-4 bg-muted rounded-md text-xs overflow-auto max-h-96">
            {{result}}
          </pre>
        )}}
      </CardContent>
    </Card>
  )
}}
''')


# ---------------------------------------------------------------------------
# Scaffolding
# ---------------------------------------------------------------------------

def scaffold_config(config: dict, dry_run: bool = False) -> dict:
    """Scaffold Nucleus pages for a config. Returns summary."""
    domain = config["domain"]
    slug = domain_to_slug(domain)
    page_dir = VIGILANCE_DIR / slug
    components_dir = page_dir / "components"

    files = {
        page_dir / "page.tsx": generate_page_tsx(config),
        components_dir / "tool-cards.tsx": generate_tool_cards(config),
        components_dir / "tool-form.tsx": generate_tool_form(config),
    }

    result = {
        "domain": domain,
        "slug": slug,
        "files": len(files),
        "tools": len(config.get("tools", [])),
    }

    if dry_run:
        result["action"] = "would_create"
        return result

    for filepath, content in files.items():
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content)

    result["action"] = "created"
    return result


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

def get_existing_pages() -> set[str]:
    """Get slugs that already have pages in vigilance/."""
    if not VIGILANCE_DIR.exists():
        return set()
    return {
        d.name for d in VIGILANCE_DIR.iterdir()
        if d.is_dir() and (d / "page.tsx").exists()
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_scaffold(args):
    """Scaffold pages for a single config."""
    if args.config:
        with open(args.config) as f:
            config = json.load(f)
    elif args.domain:
        # Find config by domain
        for cfg_path in CONFIGS_DIR.glob("*.json"):
            c = json.load(open(cfg_path))
            if c["domain"] == args.domain:
                config = c
                break
        else:
            print(f"No config found for domain: {args.domain}")
            return
    else:
        print("Specify --config or --domain")
        return

    result = scaffold_config(config, dry_run=args.dry_run)
    action = "Would create" if args.dry_run else "Created"
    print(f"{action}: vigilance/{result['slug']}/ ({result['files']} files, {result['tools']} tools)")


def cmd_batch(args):
    """Scaffold pages for ALL configs without existing pages."""
    existing = get_existing_pages()
    configs = []

    for cfg_path in sorted(CONFIGS_DIR.glob("*.json")):
        config = json.load(open(cfg_path))
        # Skip private configs
        if config.get("private"):
            continue
        slug = domain_to_slug(config["domain"])
        if slug not in existing:
            configs.append(config)

    if not configs:
        print("All public configs already have pages.")
        return

    created = 0
    total_tools = 0

    for config in configs:
        result = scaffold_config(config, dry_run=args.dry_run)
        action = "WOULD" if args.dry_run else "WROTE"
        print(f"  {action} vigilance/{result['slug']:40s} {result['tools']:4d} tools")
        created += 1
        total_tools += result["tools"]

    action = "Would scaffold" if args.dry_run else "Scaffolded"
    print(f"\n{action} {created} pages, {total_tools} tools")


def cmd_coverage(args):
    """Show page coverage."""
    existing = get_existing_pages()
    configs = list(CONFIGS_DIR.glob("*.json"))

    public_configs = []
    for cfg_path in configs:
        config = json.load(open(cfg_path))
        if not config.get("private"):
            public_configs.append(config)

    covered = 0
    uncovered = 0
    for config in public_configs:
        slug = domain_to_slug(config["domain"])
        if slug in existing:
            covered += 1
        else:
            uncovered += 1

    total = covered + uncovered
    pct = (covered / total * 100) if total else 0

    print(f"Nucleus page coverage: {covered}/{total} ({pct:.0f}%)")
    print(f"  With pages:    {covered}")
    print(f"  Without pages: {uncovered}")
    print(f"  Existing dirs: {len(existing)}")

    if uncovered > 0 and args.verbose:
        print(f"\nMissing pages:")
        for config in sorted(public_configs, key=lambda c: c["domain"]):
            slug = domain_to_slug(config["domain"])
            if slug not in existing:
                n = len(config.get("tools", []))
                print(f"  {slug:40s} {n:4d} tools")


def main():
    parser = argparse.ArgumentParser(description="Forge Nucleus — generate Next.js pages from Station configs")
    sub = parser.add_subparsers(dest="command")

    sc = sub.add_parser("scaffold", help="Scaffold pages for one config")
    sc.add_argument("--config", help="Path to config JSON")
    sc.add_argument("--domain", help="Domain name")
    sc.add_argument("--dry-run", action="store_true")

    ba = sub.add_parser("batch", help="Scaffold pages for ALL uncovered configs")
    ba.add_argument("--dry-run", action="store_true")

    co = sub.add_parser("coverage", help="Show page coverage")
    co.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
    if args.command == "scaffold":
        cmd_scaffold(args)
    elif args.command == "batch":
        cmd_batch(args)
    elif args.command == "coverage":
        cmd_coverage(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
