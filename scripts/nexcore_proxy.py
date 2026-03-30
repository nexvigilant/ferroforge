#!/usr/bin/env python3
"""
NexCore Bridge Proxy — routes Station tool calls to the nexcore-mcp binary.

Uses a persistent connection pool (nexcore_pool.py) to avoid per-call
subprocess spawn + MCP handshake overhead. First call: ~200ms (spawn).
Subsequent calls: ~5-20ms (reuse).

Station receives: stem_nexvigilant_com_stem_bio_cell_division
This proxy strips: stem_nexvigilant_com_ → stem_bio_cell_division
Calls nexcore-mcp: tools/call(stem_bio_cell_division, args)
Returns the result.
"""

import json
import os
import sys

# Ensure sibling imports work regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nexcore_pool import get_pool, strip_station_prefix


def main():
    try:
        raw = sys.stdin.read()
        envelope = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        json.dump({"status": "error", "message": f"Invalid JSON: {exc}"}, sys.stdout)
        return

    station_tool = envelope.get("tool", "")
    arguments = envelope.get("arguments", envelope.get("args", {}))

    nexcore_tool = strip_station_prefix(station_tool)
    pool = get_pool()
    result = pool.call(nexcore_tool, arguments)
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
