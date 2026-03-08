#!/usr/bin/env python3
"""SLO health check — query station health and alert on violations.

Designed to run on a cron schedule (e.g., every 5 minutes).
Returns exit code 0 if all SLOs met, 1 if any violations detected.

Usage:
    python3 scripts/slo_check.py [--url https://mcp.nexvigilant.com]
    python3 scripts/slo_check.py --local --log station-telemetry.jsonl
"""

import json
import sys
import argparse
from datetime import datetime


def parse_args():
    p = argparse.ArgumentParser(description="SLO health check")
    p.add_argument("--url", default="https://mcp.nexvigilant.com",
                   help="Station URL to check (default: production)")
    p.add_argument("--local", action="store_true",
                   help="Check local telemetry file instead of remote health endpoint")
    p.add_argument("--log", default="station-telemetry.jsonl",
                   help="Path to local telemetry JSONL (with --local)")
    p.add_argument("--json", action="store_true",
                   help="Output as JSON")
    return p.parse_args()


def check_remote(url):
    """Fetch health from the station's health endpoint."""
    import urllib.request
    import urllib.error

    health_url = f"{url.rstrip('/')}/health"
    try:
        with urllib.request.urlopen(health_url, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        return {"error": f"Cannot reach {health_url}: {e}", "slo_status": "unreachable"}
    except Exception as e:
        return {"error": str(e), "slo_status": "error"}


def check_local(log_path):
    """Compute health from local telemetry log."""
    from collections import defaultdict
    from datetime import timedelta

    records = []
    try:
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return {"error": f"File not found: {log_path}", "slo_status": "error"}

    if not records:
        return {"slo_status": "ok", "total_calls": 0, "message": "No telemetry data"}

    total = len(records)
    errors = sum(1 for r in records if r.get("is_error", False))
    error_rate = (errors / total * 100) if total > 0 else 0

    durations = sorted(r.get("duration_ms", 0) for r in records)
    p99_idx = max(0, int(len(durations) * 0.99) - 1)
    p99 = durations[p99_idx] if durations else 0

    slo_status = "ok"
    if error_rate >= 10 or p99 > 5000:
        slo_status = "critical"
    elif error_rate >= 5:
        slo_status = "warn"

    return {
        "slo_status": slo_status,
        "total_calls": total,
        "total_errors": errors,
        "error_rate_pct": round(error_rate, 2),
        "latency_p99_ms": p99,
        "latency_slo_ok": p99 <= 5000,
    }


def format_alert(health):
    """Format health data as an alert message."""
    status = health.get("slo_status", "unknown")
    ts = datetime.now().isoformat()

    lines = [f"[{ts}] Station SLO: {status.upper()}"]

    if "error" in health:
        lines.append(f"  Error: {health['error']}")
        return "\n".join(lines), True

    if status in ("critical", "warn"):
        lines.append(f"  Error rate: {health.get('error_rate_pct', '?')}%")
        lines.append(f"  P99 latency: {health.get('latency_p99_ms', '?')}ms")

        degraded = health.get("degraded_domains", [])
        if degraded:
            lines.append(f"  Degraded domains: {', '.join(degraded)}")

        return "\n".join(lines), True

    lines.append(f"  Calls: {health.get('total_calls', '?')}, "
                 f"Errors: {health.get('total_errors', '?')}, "
                 f"P99: {health.get('latency_p99_ms', '?')}ms")
    return "\n".join(lines), False


def main():
    args = parse_args()

    if args.local:
        health = check_local(args.log)
    else:
        health = check_remote(args.url)

    if args.json:
        print(json.dumps(health, indent=2))
    else:
        msg, has_alert = format_alert(health)
        print(msg)

    # Exit 1 on SLO violation (for cron/CI alerting)
    status = health.get("slo_status", "unknown")
    sys.exit(1 if status in ("critical", "unreachable", "error") else 0)


if __name__ == "__main__":
    main()
