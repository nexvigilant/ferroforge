#!/usr/bin/env python3
"""
NexVigilant Dispatch Daemon — persistent Python process for Station tool calls.

Instead of spawning a fresh `python3 dispatch.py` per tool call (Python startup
+ module import = ~50-100ms overhead), this daemon stays alive and reads
JSON-RPC requests from stdin, one per line.

The Station binary can spawn this once and reuse it for all tool calls,
eliminating per-call Python startup cost and enabling persistent connection
pools (nexcore_pool) and HTTP session reuse.

Protocol:
  - Reads one JSON line from stdin per request
  - Writes one JSON line to stdout per response
  - Stays alive until stdin closes or receives {"method": "shutdown"}
  - Flushes stdout after every response

Usage (from Rust or test):
    # Start daemon
    python3 dispatch_daemon.py

    # Send requests (one JSON per line):
    {"id": 1, "tool": "api_fda_gov_search_adverse_events", "arguments": {"drug_name": "aspirin"}}
    {"id": 2, "tool": "stem_nexvigilant_com_stem_version", "arguments": {}}

    # Shutdown
    {"method": "shutdown"}
"""

import json
import os
import sys

# Ensure sibling imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dispatch import dispatch as route_tool


def main():
    # Pre-warm the nexcore pool on startup
    try:
        from nexcore_pool import get_pool
        pool = get_pool()
        pool._ensure_alive()
        sys.stderr.write("dispatch_daemon: nexcore pool pre-warmed\n")
        sys.stderr.flush()
    except Exception as exc:
        sys.stderr.write(f"dispatch_daemon: pool pre-warm failed: {exc}\n")
        sys.stderr.flush()

    sys.stderr.write("dispatch_daemon: ready\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = {"id": None, "status": "error", "message": f"Invalid JSON: {exc}"}
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            continue

        # Shutdown command
        if request.get("method") == "shutdown":
            try:
                from nexcore_pool import get_pool
                get_pool().close()
            except Exception:
                pass
            break

        req_id = request.get("id")
        tool = request.get("tool", "")
        arguments = request.get("arguments", {})

        try:
            result = route_tool({"tool": tool, "arguments": arguments})
            if req_id is not None:
                result["id"] = req_id
        except Exception as exc:
            result = {"id": req_id, "status": "error", "message": str(exc)}

        sys.stdout.write(json.dumps(result) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
