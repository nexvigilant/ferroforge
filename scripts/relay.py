#!/usr/bin/env python3
"""
Station Relay — Chain tool calls with output→input wiring.

Each hop's output feeds the next hop's input. Electrician's discipline:
test every wire as current flows through it.

Usage:
  python3 relay.py run chains/signal-pipeline.yaml --drug semaglutide
  python3 relay.py run chains/causality-chain.yaml --drug metformin --event "Lactic acidosis"
  python3 relay.py list                  # Show available chains
  python3 relay.py test chains/*.yaml    # Dry-run all chains

Chain YAML format:
  name: signal-pipeline
  description: Drug → FAERS → PRR → Naranjo → Verdict
  hops:
    - tool: rxnav_nlm_nih_gov_search_drugs
      args: { query: "$drug" }
      extract: { rxcui: "results[0].rxcui" }

    - tool: api_fda_gov_search_adverse_events
      args: { drug_name: "$drug", serious: true, limit: 5 }
      extract: { total: "total_matching", top_reaction: "results[0].reactions[0]" }

    - tool: open-vigil_fr_compute_disproportionality
      args: { drug: "$drug", event: "$top_reaction" }
      extract: { prr: "scores.PRR", signal: "signal_assessment" }
"""

import json
import os
import sys
import time
from pathlib import Path

STATION_URL = os.environ.get("STATION_URL", "https://mcp.nexvigilant.com")


def load_chain(path: str) -> dict:
    """Load a chain YAML file. Falls back to JSON."""
    text = Path(path).read_text()
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return _mini_yaml_parse(text)


def _mini_yaml_parse(text: str) -> dict:
    """Minimal YAML parser for chain specs."""
    import re
    result = {"name": "", "description": "", "hops": []}
    current_hop = None
    in_args = False
    in_extract = False

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("name:"):
            result["name"] = stripped.split(":", 1)[1].strip().strip('"').strip("'")
        elif stripped.startswith("description:"):
            result["description"] = stripped.split(":", 1)[1].strip().strip('"').strip("'")
        elif stripped == "hops:":
            continue
        elif stripped.startswith("- tool:"):
            if current_hop:
                result["hops"].append(current_hop)
            current_hop = {
                "tool": stripped.split(":", 1)[1].strip().strip('"').strip("'"),
                "args": {},
                "extract": {},
            }
            in_args = False
            in_extract = False
        elif current_hop:
            if stripped.startswith("args:"):
                in_args = True
                in_extract = False
                # Inline args: args: { key: val }
                inline = stripped.split(":", 1)[1].strip()
                if inline.startswith("{"):
                    try:
                        current_hop["args"] = json.loads(inline.replace("'", '"'))
                    except json.JSONDecodeError:
                        # Parse key: val pairs
                        pairs = re.findall(r'(\w+):\s*([^,}]+)', inline)
                        for k, v in pairs:
                            v = v.strip().strip('"').strip("'")
                            if v == "true":
                                v = True
                            elif v == "false":
                                v = False
                            elif v.isdigit():
                                v = int(v)
                            current_hop["args"][k] = v
                        in_args = False
            elif stripped.startswith("extract:"):
                in_extract = True
                in_args = False
                inline = stripped.split(":", 1)[1].strip()
                if inline.startswith("{"):
                    pairs = re.findall(r'(\w+):\s*"([^"]+)"', inline)
                    for k, v in pairs:
                        current_hop["extract"][k] = v
                    in_extract = False
            elif in_args and ":" in stripped:
                k, v = stripped.split(":", 1)
                v = v.strip().strip('"').strip("'")
                if v == "true":
                    v = True
                elif v == "false":
                    v = False
                elif v.isdigit():
                    v = int(v)
                current_hop["args"][k.strip()] = v
            elif in_extract and ":" in stripped:
                k, v = stripped.split(":", 1)
                current_hop["extract"][k.strip()] = v.strip().strip('"').strip("'")

    if current_hop:
        result["hops"].append(current_hop)

    return result


def call_tool(tool_name: str, args: dict) -> tuple[dict, int]:
    """Call a Station tool via HTTP RPC. Returns (result, latency_ms)."""
    import urllib.request
    import urllib.error

    start = time.monotonic()
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args},
    }).encode()

    req = urllib.request.Request(
        f"{STATION_URL}/rpc",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        return {"status": "error", "message": str(exc)}, int((time.monotonic() - start) * 1000)

    latency = int((time.monotonic() - start) * 1000)

    content = data.get("result", {}).get("content", [])
    if content:
        text = content[0].get("text", "{}")
        try:
            return json.loads(text), latency
        except json.JSONDecodeError:
            return {"status": "ok", "raw": text}, latency

    if "error" in data:
        return {"status": "error", "message": data["error"].get("message", "")}, latency

    return {"status": "ok", "result": data.get("result")}, latency


def resolve_value(data: dict, path: str):
    """Extract a value from nested dict using dot notation + array indexing.
    e.g., "results[0].rxcui" → data["results"][0]["rxcui"]
    """
    import re
    parts = re.split(r'\.', path)
    current = data
    for part in parts:
        # Check for array index
        m = re.match(r'(\w+)\[(\d+)\]', part)
        if m:
            key, idx = m.group(1), int(m.group(2))
            if isinstance(current, dict) and key in current:
                current = current[key]
                if isinstance(current, list) and idx < len(current):
                    current = current[idx]
                else:
                    return None
            else:
                return None
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def substitute_vars(args: dict, context: dict) -> dict:
    """Replace $var references in args with context values."""
    result = {}
    for key, val in args.items():
        if isinstance(val, str) and val.startswith("$"):
            var_name = val[1:]
            result[key] = context.get(var_name, val)
        else:
            result[key] = val
    return result


def run_chain(chain: dict, initial_vars: dict, verbose: bool = True) -> dict:
    """Execute a relay chain. Returns final context with all extracted values."""
    context = dict(initial_vars)
    results = []
    total_start = time.monotonic()

    if verbose:
        print(f"\n{'='*60}")
        print(f"RELAY: {chain['name']}")
        print(f"  {chain.get('description', '')}")
        print(f"  Hops: {len(chain['hops'])}")
        print(f"  Vars: {context}")
        print(f"{'='*60}\n")

    for i, hop in enumerate(chain["hops"]):
        tool = hop["tool"]
        raw_args = hop.get("args", {})
        extract = hop.get("extract", {})

        # Substitute variables
        args = substitute_vars(raw_args, context)

        if verbose:
            print(f"Hop {i+1}/{len(chain['hops'])}: {tool}")
            print(f"  Args: {json.dumps(args, default=str)[:120]}")

        # Call tool
        result, latency = call_tool(tool, args)
        status = result.get("status", "?")

        # Extract values for next hop
        extracted = {}
        for var_name, path in extract.items():
            val = resolve_value(result, path)
            if val is not None:
                context[var_name] = val
                extracted[var_name] = val

        hop_result = {
            "hop": i + 1,
            "tool": tool,
            "status": status,
            "latency_ms": latency,
            "extracted": extracted,
        }
        results.append(hop_result)

        if verbose:
            status_icon = "✓" if status in ("ok", "signal_detected") else "✗" if status == "error" else "~"
            print(f"  {status_icon} {status} ({latency}ms)")
            if extracted:
                for k, v in extracted.items():
                    val_str = str(v)[:80]
                    print(f"    → ${k} = {val_str}")
            print()

        # Stop on error if critical
        if status == "error" and not hop.get("continue_on_error"):
            if verbose:
                print(f"  Chain halted at hop {i+1}: {result.get('message', '')[:120]}")
            break

    total_ms = int((time.monotonic() - total_start) * 1000)
    passed = sum(1 for r in results if r["status"] not in ("error",))
    fidelity = passed / len(results) if results else 0

    summary = {
        "chain": chain["name"],
        "hops_total": len(chain["hops"]),
        "hops_executed": len(results),
        "hops_passed": passed,
        "fidelity": round(fidelity, 3),
        "total_ms": total_ms,
        "context": context,
        "results": results,
    }

    if verbose:
        print(f"{'='*60}")
        print(f"RELAY COMPLETE: {chain['name']}")
        print(f"  Fidelity: {passed}/{len(results)} ({fidelity*100:.0f}%)")
        print(f"  Total: {total_ms}ms")
        print(f"  Context: {json.dumps(context, default=str)[:200]}")
        print(f"{'='*60}")

    return summary


def cmd_run(args):
    """Run a chain."""
    chain = load_chain(args[0])

    # Parse --key=value pairs as initial vars
    initial = {}
    for arg in args[1:]:
        if arg.startswith("--"):
            parts = arg[2:].split("=", 1)
            if len(parts) == 2:
                initial[parts[0]] = parts[1]
            elif len(parts) == 1 and args.index(arg) + 1 < len(args):
                initial[parts[0]] = args[args.index(arg) + 1]

    return run_chain(chain, initial)


def cmd_list(args):
    """List available chains."""
    chains_dir = Path(__file__).parent.parent / "chains"
    relay_dir = Path(__file__).parent.parent / "relays"

    for d in [chains_dir, relay_dir]:
        if d.exists():
            for f in sorted(d.glob("*.yaml")) + sorted(d.glob("*.json")):
                try:
                    chain = load_chain(str(f))
                    name = chain.get("name", f.stem)
                    hops = len(chain.get("hops", []))
                    desc = chain.get("description", "")[:60]
                    print(f"  {name:30s} {hops} hops — {desc}")
                except Exception:
                    print(f"  {f.name:30s} (parse error)")


def cmd_test(args):
    """Dry-run chains without calling tools."""
    for path in args:
        try:
            chain = load_chain(path)
            hops = len(chain.get("hops", []))
            tools = [h["tool"] for h in chain.get("hops", [])]
            print(f"  {chain.get('name','?'):30s} {hops} hops: {' → '.join(tools)}")
        except Exception as e:
            print(f"  {path}: ERROR {e}")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  relay.py run <chain.yaml> --drug semaglutide")
        print("  relay.py list")
        print("  relay.py test <chain.yaml> [...]")
        return

    cmd = sys.argv[1]
    if cmd == "run":
        cmd_run(sys.argv[2:])
    elif cmd == "list":
        cmd_list(sys.argv[2:])
    elif cmd == "test":
        cmd_test(sys.argv[2:])
    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
