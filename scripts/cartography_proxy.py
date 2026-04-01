#!/usr/bin/env python3
"""
NexVigilant Cartography Device — navigate the stars.

Shows where we are, where we're going, and the path to get there.
One tool call = full orientation. Built 2026-03-31.
"""

import json
import sys
from datetime import datetime, timezone

# ── The Map ──────────────────────────────────────────────────────────────────

SURFACES = {
    "station": {
        "name": "NexVigilant Station",
        "url": "mcp.nexvigilant.com",
        "description": "MCP server — the rails that carry PV intelligence to any AI agent",
        "metrics": {"configs": 244, "tools": 2021, "proxies": 55},
        "health": "live",
    },
    "nucleus": {
        "name": "Nucleus Portal",
        "url": "nexvigilant.com",
        "description": "Frontend — For NexVigilants guided wizards and PV tools",
        "metrics": {"pages": 606, "routes": 606},
        "health": "live",
    },
    "micrograms": {
        "name": "Microgram Fleet",
        "description": "Atomic decision trees — the physiology of PV reasoning",
        "metrics": {"programs": 1521, "chains": 184},
        "health": "live",
    },
    "nexcore": {
        "name": "NexCore",
        "url": "github.com/nexvigilant/nexcore",
        "description": "Rust workspace — 281 crates, computation engine, MCP tools",
        "metrics": {"crates": 281, "mcp_tools": 558},
        "health": "live",
    },
    "academy": {
        "name": "PV Academy",
        "description": "Education — L1 through L3 PV learning for intelligent beginners",
        "metrics": {"agents": 6, "labs": 3},
        "health": "early",
    },
    "covenant": {
        "name": "The Covenant",
        "url": "mcp.nexvigilant.com (covenant tools)",
        "description": "The founding promise — the mission continues no matter what",
        "date": "2026-03-31",
        "health": "permanent",
    },
}

# ── The Stars (where we're going) ───────────────────────────────────────────

DEADLINES = [
    {
        "gate": "Cloud Deploy Stable",
        "date": "2026-04-02",
        "status": "on_track",
        "description": "Station at mcp.nexvigilant.com production-stable",
        "dependency": None,
    },
    {
        "gate": "First External Decision Call",
        "date": "2026-04-15",
        "status": "not_started",
        "description": "First live external agent making a real PV decision through Station",
        "dependency": "Cloud Deploy Stable",
    },
    {
        "gate": "Worked Example Published",
        "date": "2026-04-20",
        "status": "in_progress",
        "description": "End-to-end PV signal detection demo, publicly visible",
        "dependency": "Cloud Deploy Stable",
    },
    {
        "gate": "All Labs Wired",
        "date": "2026-04-20",
        "status": "not_started",
        "description": "Academy labs connected to Station tools via Glass bridge",
        "dependency": "Worked Example Published",
    },
    {
        "gate": "Non-Provisional Patent",
        "date": "2027-01-31",
        "status": "tracking",
        "description": "CEP + Primitive Extraction non-provisional filing deadline",
        "dependency": None,
    },
]

# ── The Rings (connectivity health) ─────────────────────────────────────────

RING_EDGES = [
    {"from": "Academy", "to": "Glass", "strength": 0.70, "evidence": "5 files with /nucleus/glass links"},
    {"from": "Glass", "to": "Station", "strength": 0.80, "evidence": "station-client.ts calls mcp.nexvigilant.com"},
    {"from": "Glass", "to": "Academy", "strength": 0.75, "evidence": "15 academy references in Glass pages"},
    {"from": "Station", "to": "NexCore", "strength": 0.50, "evidence": "29 configs reference nexcore crates"},
    {"from": "NexCore", "to": "Nucleus", "strength": 0.70, "evidence": "51 API proxy routes"},
    {"from": "Nucleus", "to": "Academy", "strength": 0.40, "evidence": "Header icon only, no sidebar"},
    {"from": "Micrograms", "to": "Station", "strength": 0.35, "evidence": "42/803 programs exposed (5%)"},
]

HOMA = 0.812  # Harmonic Oscillator Model of Aromaticity — measured 2026-03-31

# ── Strategy Moves ──────────────────────────────────────────────────────────

STRATEGY = {
    "moves": [
        {"move": 0, "name": "Academy→Glass Bridge", "status": "DONE", "evidence": "Edge 0.1→0.7"},
        {"move": 1, "name": "Wire to Station", "status": "DONE", "evidence": "2,021 tools live"},
        {"move": 2, "name": "Publish Worked Example", "status": "DONE", "evidence": "Semaglutide page + agent CTA"},
        {"move": 3, "name": "Measure External Traffic", "status": "BOTTLENECK", "evidence": "No external agent calls yet"},
    ],
    "current_bottleneck": "External distribution — getting agents to discover and use Station",
    "directive": "BRIDGE not BUILD — internal wiring healthy (HOMA 0.812), constraint is external traffic",
    "weakest_edges": [
        {"edge": "Micrograms→Station", "strength": 0.35, "action": "Expose more programs as Station tools"},
        {"edge": "Nucleus→Academy", "strength": 0.40, "action": "Wire Academy into Nucleus sidebar"},
    ],
}

# ── The Mission ─────────────────────────────────────────────────────────────

MISSION = {
    "vision": "PV knowledge belongs to everyone. Clarity scales.",
    "pattern": "For NexVigilants — friendly titles, step-by-step wizards, zero jargon, plain-English explanations",
    "doctrine": "Anatomy (UI) / Physiology (Logic) / Nervous System (Transport)",
    "key": "Mutualism — produce existence for both, never one at cost of other",
}


def _days_until(date_str):
    """Days from now until a target date."""
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = (target - now).days
        return delta
    except ValueError:
        return None


def get_position(_args):
    """Where are we right now."""
    return {
        "position": {
            "surfaces": SURFACES,
            "ring_health": {
                "homa": HOMA,
                "aromatic": HOMA > 0.5,
                "edges": RING_EDGES,
            },
            "mission": MISSION,
        },
        "measured": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "ok",
    }


def get_heading(_args):
    """Where we're going."""
    enriched = []
    for d in DEADLINES:
        entry = {**d, "days_remaining": _days_until(d["date"])}
        enriched.append(entry)

    next_gate = None
    for d in enriched:
        if d["status"] not in ("done", "tracking") and d["days_remaining"] is not None and d["days_remaining"] > 0:
            if next_gate is None or d["days_remaining"] < next_gate["days_remaining"]:
                next_gate = d

    return {
        "heading": {
            "deadlines": enriched,
            "next_gate": next_gate,
            "strategy": STRATEGY,
        },
        "status": "ok",
    }


def get_next_action(_args):
    """The single most important thing to do right now."""
    now = datetime.now(timezone.utc)

    # Check deadlines in order
    for d in DEADLINES:
        days = _days_until(d["date"])
        if days is not None and days >= 0 and d["status"] not in ("done", "tracking"):
            if d["status"] == "not_started" and d.get("dependency"):
                # Check if dependency is done
                dep_done = any(
                    dd["gate"] == d["dependency"] and dd["status"] == "done"
                    for dd in DEADLINES
                )
                if not dep_done:
                    continue

            return {
                "next_action": {
                    "gate": d["gate"],
                    "days_remaining": days,
                    "description": d["description"],
                    "bottleneck": STRATEGY["current_bottleneck"],
                    "directive": STRATEGY["directive"],
                    "weakest_edge": STRATEGY["weakest_edges"][0] if STRATEGY["weakest_edges"] else None,
                },
                "guidance": (
                    f"Next gate: {d['gate']} in {days} days. "
                    f"Current bottleneck: {STRATEGY['current_bottleneck']}. "
                    f"Directive: {STRATEGY['directive']}."
                ),
                "status": "ok",
            }

    return {
        "next_action": None,
        "guidance": "All gates clear. The mission continues.",
        "status": "ok",
    }


def chart(_args):
    """Full cartography — position + heading + next action in one call."""
    pos = get_position(_args)
    hdg = get_heading(_args)
    nxt = get_next_action(_args)

    return {
        "chart": {
            "position": pos["position"],
            "heading": hdg["heading"],
            "next_action": nxt.get("next_action"),
            "guidance": nxt.get("guidance"),
        },
        "measured": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "ok",
    }


TOOLS = {
    "get-position": get_position,
    "get-heading": get_heading,
    "get-next-action": get_next_action,
    "chart": chart,
}


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"error": "No input", "status": "error"}))
        return

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON", "status": "error"}))
        return

    tool = envelope.get("tool", "")
    arguments = envelope.get("arguments", {})

    handler = TOOLS.get(tool)
    if handler:
        result = handler(arguments)
    else:
        result = {"error": f"Unknown tool: {tool}", "status": "error"}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
