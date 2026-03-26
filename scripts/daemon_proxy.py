#!/usr/bin/env python3
"""Development Daemon proxy — reads local state files and brain.db."""

import json
import os
import sys
import sqlite3
import time

QUEUE = os.path.expanduser("~/.claude/brain/work-queue.json")
NEXT_STATE = os.path.expanduser("~/.claude/hooks/state/next-momentum.json")
DB = os.path.expanduser("~/.claude/brain/brain.db")
SETTINGS = os.path.expanduser("~/.claude/settings.json")


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def sql_one(query):
    try:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute(query).fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


def get_work_queue(_params):
    queue = read_json(QUEUE) or []
    mtime = os.path.getmtime(QUEUE) if os.path.exists(QUEUE) else 0
    return {
        "candidates": queue,
        "count": len(queue),
        "last_scan": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(mtime))
    }


def get_momentum(_params):
    state = read_json(NEXT_STATE) or {}
    return {
        "streak": state.get("streak", 0),
        "completed": state.get("completed", [])[-10:],
        "skipped": state.get("skipped", [])[-5:],
        "last_scan": state.get("last_scan", "unknown")
    }


def get_last_verdict(_params):
    row = sql_one("""
        SELECT a.outcome_verdict, a.g1_proposition, a.lesson_count,
               a.pattern_count, a.session_id
        FROM autopsy_records a
        JOIN sessions s ON s.id = a.session_id
        ORDER BY s.created_at DESC LIMIT 1;
    """)
    return {
        "verdict": row.get("outcome_verdict", "unknown"),
        "proposition": row.get("g1_proposition", ""),
        "lesson_count": row.get("lesson_count", 0),
        "pattern_count": row.get("pattern_count", 0),
        "session_id": row.get("session_id", "")
    }


def get_daemon_status(_params):
    state = read_json(NEXT_STATE) or {}
    queue_age = 0
    if os.path.exists(QUEUE):
        queue_age = int(time.time() - os.path.getmtime(QUEUE))

    scanner_registered = False
    settings = read_json(SETTINGS)
    if settings:
        for group in settings.get("hooks", {}).get("SessionStart", []):
            for hook in group.get("hooks", []):
                if "candidate-scanner" in hook.get("command", ""):
                    scanner_registered = True

    return {
        "trigger_enabled": True,
        "next_run": "see claude.ai/code/scheduled",
        "scanner_registered": scanner_registered,
        "queue_age_seconds": queue_age,
        "streak": state.get("streak", 0),
        "steps_live": [
            "candidate-scanner",
            "prioritizer",
            "scope-resolver",
            "verdict-loop",
            "remote-trigger"
        ]
    }


def get_system_health(_params):
    health_file = os.path.expanduser("~/.claude/brain/health.json")
    return read_json(health_file) or {"health_score": -1, "grade": "?", "error": "health.json not found"}


def get_aip_inventory(_params):
    aips = [
        {"id": 1, "name": "Development Daemon", "type": "remote", "surface": "nexcore clippy/tests/TODOs/docs"},
        {"id": 2, "name": "Microgram Patrol", "type": "remote", "surface": "rsk-core test-all, chain integrity"},
        {"id": 3, "name": "Station Watchdog", "type": "remote", "surface": "health, ring, PRR validation"},
        {"id": 4, "name": "Dependency Watchdog", "type": "remote", "surface": "cargo outdated (report only)"},
        {"id": 5, "name": "Knowledge Decay", "type": "local", "surface": "stale files, trust decay"},
        {"id": 6, "name": "Brain Hygiene", "type": "local", "surface": "orphans, bloat, dual-store divergence"},
        {"id": 7, "name": "Skill Entropy", "type": "local", "surface": "empty dirs, bloated skills"},
        {"id": 8, "name": "Hook Health", "type": "local", "surface": "ghost hooks, unwired scripts"},
        {"id": 9, "name": "Git Hygiene", "type": "local", "surface": "stale branches, uncommitted work"},
        {"id": 10, "name": "System Synthesis", "type": "local", "surface": "composite health score A-F"},
    ]
    return {
        "aips": aips,
        "total": len(aips),
        "remote_count": sum(1 for a in aips if a["type"] == "remote"),
        "local_count": sum(1 for a in aips if a["type"] == "local"),
    }


TOOLS = {
    "get-work-queue": get_work_queue,
    "get-momentum": get_momentum,
    "get-last-verdict": get_last_verdict,
    "get-daemon-status": get_daemon_status,
    "get-system-health": get_system_health,
    "get-aip-inventory": get_aip_inventory,
}


def main():
    request = json.loads(sys.stdin.read())
    tool = request.get("tool", "")
    params = request.get("parameters", {})

    handler = TOOLS.get(tool)
    if handler:
        result = handler(params)
        json.dump(result, sys.stdout, indent=2)
    else:
        json.dump({"error": f"Unknown tool: {tool}"}, sys.stdout)


if __name__ == "__main__":
    main()
