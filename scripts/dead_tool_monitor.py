#!/usr/bin/env python3
"""Dead tool monitor — identify tools with persistent errors from telemetry.

Reads the station-telemetry.jsonl file and reports tools that consistently
fail, have high error rates, or haven't been called recently.

Usage:
    python3 scripts/dead_tool_monitor.py [--log station-telemetry.jsonl] [--threshold 0.5]
"""

import json
import sys
import argparse
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description="Dead tool monitor")
    p.add_argument("--log", default="station-telemetry.jsonl",
                   help="Path to telemetry JSONL file")
    p.add_argument("--threshold", type=float, default=0.5,
                   help="Error rate threshold (0.0-1.0) to flag as degraded")
    p.add_argument("--min-calls", type=int, default=3,
                   help="Minimum calls to include in analysis")
    p.add_argument("--days", type=int, default=7,
                   help="Look back N days")
    p.add_argument("--json", action="store_true",
                   help="Output as JSON instead of table")
    return p.parse_args()


def load_records(path, days):
    """Load telemetry records from JSONL, filtering to recent window."""
    cutoff = datetime.now(tz=None) - timedelta(days=days)
    records = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    # Parse timestamp — ISO 8601 format
                    ts = rec.get("timestamp", "")
                    if ts:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00").replace("+00:00", ""))
                        if dt < cutoff:
                            continue
                    records.append(rec)
                except (json.JSONDecodeError, ValueError):
                    continue
    except FileNotFoundError:
        print(f"Error: Telemetry file not found: {path}", file=sys.stderr)
        sys.exit(1)
    return records


def analyze(records, threshold, min_calls):
    """Analyze records for dead/degraded tools."""
    stats = defaultdict(lambda: {"total": 0, "errors": 0, "last_ok": None, "last_call": None})

    for rec in records:
        tool = rec.get("tool_name", "unknown")
        is_error = rec.get("is_error", False)
        ts = rec.get("timestamp", "")

        stats[tool]["total"] += 1
        if is_error:
            stats[tool]["errors"] += 1

        stats[tool]["last_call"] = ts
        if not is_error:
            stats[tool]["last_ok"] = ts

    results = {"dead": [], "degraded": [], "healthy": 0, "total_tools": 0}

    for tool, s in sorted(stats.items()):
        if s["total"] < min_calls:
            continue

        results["total_tools"] += 1
        error_rate = s["errors"] / s["total"] if s["total"] > 0 else 0

        if error_rate >= 1.0:
            results["dead"].append({
                "tool": tool,
                "calls": s["total"],
                "error_rate": error_rate,
                "last_ok": s["last_ok"],
                "last_call": s["last_call"],
            })
        elif error_rate >= threshold:
            results["degraded"].append({
                "tool": tool,
                "calls": s["total"],
                "error_rate": round(error_rate, 3),
                "errors": s["errors"],
                "last_ok": s["last_ok"],
                "last_call": s["last_call"],
            })
        else:
            results["healthy"] += 1

    return results


def print_table(results):
    """Print results as a readable table."""
    dead = results["dead"]
    degraded = results["degraded"]

    print(f"\n=== Dead Tool Monitor ===")
    print(f"Total tools analyzed: {results['total_tools']}")
    print(f"Healthy: {results['healthy']}")
    print(f"Degraded: {len(degraded)}")
    print(f"Dead (100% errors): {len(dead)}")

    if dead:
        print(f"\n--- DEAD TOOLS (100% error rate) ---")
        print(f"{'Tool':<50} {'Calls':>6} {'Last OK':<20}")
        print("-" * 80)
        for t in dead:
            last_ok = t["last_ok"] or "never"
            print(f"{t['tool']:<50} {t['calls']:>6} {last_ok:<20}")

    if degraded:
        print(f"\n--- DEGRADED TOOLS (>{results.get('threshold', 0.5)*100:.0f}% errors) ---")
        print(f"{'Tool':<50} {'Calls':>6} {'Errors':>7} {'Rate':>6}")
        print("-" * 80)
        for t in degraded:
            print(f"{t['tool']:<50} {t['calls']:>6} {t['errors']:>7} {t['error_rate']:>5.1%}")

    if not dead and not degraded:
        print("\nAll tools healthy.")

    print()


def main():
    args = parse_args()
    records = load_records(args.log, args.days)

    if not records:
        print(f"No telemetry records found in last {args.days} days.", file=sys.stderr)
        sys.exit(0)

    results = analyze(records, args.threshold, args.min_calls)
    results["threshold"] = args.threshold

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_table(results)

    # Exit 1 if any dead tools found (useful for CI/alerting)
    sys.exit(1 if results["dead"] else 0)


if __name__ == "__main__":
    main()
