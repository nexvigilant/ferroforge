#!/usr/bin/env python3
"""Seed the NexVigilant Hub from local configs directory.

Usage:
    HUB_TOKEN=<token> python3 hub/seed.py                           # Seed via API
    HUB_TOKEN=<token> python3 hub/seed.py --hub-url http://host:port  # Custom URL
    python3 hub/seed.py --direct                                      # Direct DB write (no server needed)
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

# Add parent dir to path for config_forge imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from config_forge import generate_hub_payload


def seed_via_api(hub_url: str, token: str, config_dir: str) -> None:
    """Seed hub by POSTing each config through the API."""
    configs = []
    for fname in sorted(os.listdir(config_dir)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(config_dir, fname)) as f:
            local_config = json.load(f)
        payload = generate_hub_payload(local_config)
        configs.append(payload)

    body = json.dumps({"configs": configs}).encode()
    req = urllib.request.Request(
        f"{hub_url}/api/import",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        print(f"Seeded: {result['imported']} new, {result['updated']} updated, {result['total']} total")
    except urllib.error.HTTPError as e:
        print(f"Error {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
        sys.exit(1)


def seed_direct(config_dir: str) -> None:
    """Seed hub by writing directly to SQLite (no server needed)."""
    import sqlite3
    import uuid
    from datetime import datetime, timezone

    db_path = os.path.join(os.path.dirname(__file__), "hub.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    # Ensure table exists
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS configs (
            id TEXT PRIMARY KEY,
            domain TEXT NOT NULL,
            url_pattern TEXT NOT NULL DEFAULT '/**',
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            tools_json TEXT NOT NULL DEFAULT '[]',
            contributor TEXT NOT NULL DEFAULT 'nexvigilant',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_configs_domain ON configs(domain);
        CREATE INDEX IF NOT EXISTS idx_configs_title ON configs(title);
    """)

    imported = 0
    updated = 0
    for fname in sorted(os.listdir(config_dir)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(config_dir, fname)) as f:
            local_config = json.load(f)
        payload = generate_hub_payload(local_config)

        now = datetime.now(timezone.utc).isoformat()
        domain = payload["domain"]
        title = payload["title"]

        existing = conn.execute(
            "SELECT id FROM configs WHERE domain = ? AND title = ?",
            (domain, title),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE configs SET url_pattern=?, description=?,
                   tools_json=?, updated_at=? WHERE id=?""",
                (
                    payload.get("urlPattern", "/**"),
                    payload.get("description", ""),
                    json.dumps(payload.get("tools", [])),
                    now,
                    existing[0],
                ),
            )
            updated += 1
            print(f"  UPD {fname:30s} ({len(payload.get('tools', []))} tools)")
        else:
            config_id = str(uuid.uuid4())[:8]
            conn.execute(
                """INSERT INTO configs (id, domain, url_pattern, title, description,
                   tools_json, contributor, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    config_id,
                    domain,
                    payload.get("urlPattern", "/**"),
                    title,
                    payload.get("description", ""),
                    json.dumps(payload.get("tools", [])),
                    "nexvigilant",
                    now,
                    now,
                ),
            )
            imported += 1
            print(f"  NEW {fname:30s} -> {config_id} ({len(payload.get('tools', []))} tools)")

    conn.commit()
    conn.close()
    print(f"\nSeeded: {imported} new, {updated} updated, {imported + updated} total")
    print(f"DB: {db_path}")


def main():
    parser = argparse.ArgumentParser(description="Seed NexVigilant Hub")
    parser.add_argument("--hub-url", default="http://127.0.0.1:8787")
    parser.add_argument("--direct", action="store_true", help="Write directly to SQLite (no server)")
    parser.add_argument("--config-dir", default=os.path.join(os.path.dirname(__file__), "..", "configs"))
    args = parser.parse_args()

    if not os.path.isdir(args.config_dir):
        print(f"Config dir not found: {args.config_dir}", file=sys.stderr)
        sys.exit(1)

    if args.direct:
        seed_direct(args.config_dir)
    else:
        token = os.environ.get("HUB_TOKEN", "")
        if not token:
            print("Set HUB_TOKEN env var", file=sys.stderr)
            sys.exit(1)
        seed_via_api(args.hub_url, token, args.config_dir)


if __name__ == "__main__":
    main()
