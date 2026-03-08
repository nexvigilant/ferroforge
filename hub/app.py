#!/usr/bin/env python3
"""NexVigilant Hub — Self-hosted WebMCP config registry.

No config cap. Own the rails. API-compatible with webmcp-hub.com
so config_forge.py works with a URL swap.

Usage:
    HUB_TOKEN=<secret> python3 hub/app.py                  # Port 8787
    HUB_TOKEN=<secret> python3 hub/app.py --port 9090      # Custom port
    HUB_TOKEN=<secret> python3 hub/app.py --host 0.0.0.0   # Bind all interfaces

Env:
    HUB_TOKEN   — Bearer token for write operations (required)
    HUB_DB      — SQLite database path (default: hub/hub.db)
"""

import json
import os
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HUB_TOKEN = os.environ.get("HUB_TOKEN", "")
HUB_DB = os.environ.get("HUB_DB", os.path.join(os.path.dirname(__file__), "hub.db"))

app = FastAPI(
    title="NexVigilant Hub",
    description="Self-hosted WebMCP config registry — no cap, full sovereignty",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def _init_db() -> None:
    """Create tables if they don't exist."""
    with _db() as conn:
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


@contextmanager
def _db():
    """Yield a sqlite3 connection with row_factory."""
    conn = sqlite3.connect(HUB_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_config(row: sqlite3.Row) -> dict:
    """Convert a DB row to the API response format."""
    return {
        "id": row["id"],
        "domain": row["domain"],
        "urlPattern": row["url_pattern"],
        "title": row["title"],
        "description": row["description"],
        "tools": json.loads(row["tools_json"]),
        "contributor": row["contributor"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _require_auth(authorization: Optional[str]) -> None:
    """Validate Bearer token for write operations."""
    if not HUB_TOKEN:
        raise HTTPException(500, "HUB_TOKEN not configured on server")
    if not authorization:
        raise HTTPException(401, "Authorization header required")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or parts[1] != HUB_TOKEN:
        raise HTTPException(403, "Invalid token")


# ---------------------------------------------------------------------------
# Routes — API-compatible with webmcp-hub.com
# ---------------------------------------------------------------------------

@app.post("/api/configs", status_code=201)
async def create_config(request: Request, authorization: str = Header(None)):
    """Create a new config. Returns 409 if domain+title already exists."""
    _require_auth(authorization)
    body = await request.json()

    domain = body.get("domain", "")
    title = body.get("title", "")
    if not domain or not title:
        raise HTTPException(400, "domain and title are required")

    with _db() as conn:
        # Check for existing config by domain + title
        existing = conn.execute(
            "SELECT id FROM configs WHERE domain = ? AND title = ?",
            (domain, title),
        ).fetchone()
        if existing:
            return JSONResponse(
                status_code=409,
                content={"error": "Config already exists", "existingId": existing["id"]},
            )

        config_id = str(uuid.uuid4())[:8]
        now = _now()
        conn.execute(
            """INSERT INTO configs (id, domain, url_pattern, title, description,
               tools_json, contributor, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                config_id,
                domain,
                body.get("urlPattern", "/**"),
                title,
                body.get("description", ""),
                json.dumps(body.get("tools", [])),
                "nexvigilant",
                now,
                now,
            ),
        )
    return {"id": config_id, "status": "created"}


@app.patch("/api/configs/{config_id}")
async def update_config(config_id: str, request: Request, authorization: str = Header(None)):
    """Update an existing config by ID."""
    _require_auth(authorization)
    body = await request.json()

    with _db() as conn:
        existing = conn.execute("SELECT id FROM configs WHERE id = ?", (config_id,)).fetchone()
        if not existing:
            raise HTTPException(404, f"Config {config_id} not found")

        updates = []
        params = []
        for api_field, db_field in [
            ("domain", "domain"),
            ("urlPattern", "url_pattern"),
            ("title", "title"),
            ("description", "description"),
        ]:
            if api_field in body:
                updates.append(f"{db_field} = ?")
                params.append(body[api_field])
        if "tools" in body:
            updates.append("tools_json = ?")
            params.append(json.dumps(body["tools"]))

        updates.append("updated_at = ?")
        params.append(_now())
        params.append(config_id)

        conn.execute(
            f"UPDATE configs SET {', '.join(updates)} WHERE id = ?",
            params,
        )
    return {"id": config_id, "status": "updated"}


@app.get("/api/configs")
async def list_configs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    domain: Optional[str] = Query(None),
    authorization: str = Header(None),
):
    """List configs with pagination. Public read — no auth required."""
    offset = (page - 1) * limit

    with _db() as conn:
        if domain:
            rows = conn.execute(
                "SELECT * FROM configs WHERE domain = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (domain, limit, offset),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM configs WHERE domain = ?", (domain,)
            ).fetchone()["cnt"]
        else:
            rows = conn.execute(
                "SELECT * FROM configs ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) as cnt FROM configs").fetchone()["cnt"]

    configs = [_row_to_config(r) for r in rows]

    return {
        "configs": configs,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }


@app.get("/api/configs/{config_id}")
async def get_config(config_id: str):
    """Get a single config by ID. Public read."""
    with _db() as conn:
        row = conn.execute("SELECT * FROM configs WHERE id = ?", (config_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Config {config_id} not found")
    return _row_to_config(row)


@app.delete("/api/configs/{config_id}")
async def delete_config(config_id: str, authorization: str = Header(None)):
    """Delete a config by ID."""
    _require_auth(authorization)
    with _db() as conn:
        existing = conn.execute("SELECT id FROM configs WHERE id = ?", (config_id,)).fetchone()
        if not existing:
            raise HTTPException(404, f"Config {config_id} not found")
        conn.execute("DELETE FROM configs WHERE id = ?", (config_id,))
    return {"id": config_id, "status": "deleted"}


# ---------------------------------------------------------------------------
# Agent discovery endpoints — the value surface
# ---------------------------------------------------------------------------

@app.get("/api/tools")
async def list_all_tools(domain: Optional[str] = Query(None)):
    """List all tools across all configs. The agent discovery endpoint."""
    with _db() as conn:
        if domain:
            rows = conn.execute(
                "SELECT domain, title, tools_json FROM configs WHERE domain = ?", (domain,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT domain, title, tools_json FROM configs").fetchall()

    tools = []
    for row in rows:
        config_tools = json.loads(row["tools_json"])
        for t in config_tools:
            t["_config_domain"] = row["domain"]
            t["_config_title"] = row["title"]
            tools.append(t)

    return {"tools": tools, "count": len(tools)}


@app.get("/api/stats")
async def hub_stats():
    """Hub statistics — config count, tool count, domains."""
    with _db() as conn:
        config_count = conn.execute("SELECT COUNT(*) as cnt FROM configs").fetchone()["cnt"]
        rows = conn.execute("SELECT domain, tools_json FROM configs").fetchall()

    tool_count = sum(len(json.loads(r["tools_json"])) for r in rows)
    domains = sorted(set(r["domain"] for r in rows))

    return {
        "configs": config_count,
        "tools": tool_count,
        "domains": domains,
        "domain_count": len(domains),
        "cap": None,  # No cap. That's the point.
    }


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "nexvigilant-hub", "version": "1.0.0"}


# ---------------------------------------------------------------------------
# MCP-compatible tools/list endpoint
# ---------------------------------------------------------------------------

@app.get("/mcp/tools/list")
async def mcp_tools_list():
    """MCP-compatible tools/list for agent integration."""
    with _db() as conn:
        rows = conn.execute("SELECT * FROM configs").fetchall()

    tools = []
    for row in rows:
        config_tools = json.loads(row["tools_json"])
        domain_prefix = row["domain"].replace(".", "_").replace("-", "_")
        for t in config_tools:
            tool_name = t.get("name", "").replace("-", "_")
            tools.append({
                "name": f"{domain_prefix}_{tool_name}",
                "description": t.get("description", ""),
                "inputSchema": t.get("inputSchema", {"type": "object", "properties": {}}),
            })

    return {"tools": tools}


# ---------------------------------------------------------------------------
# Bulk import from local configs directory
# ---------------------------------------------------------------------------

@app.post("/api/import")
async def import_configs(request: Request, authorization: str = Header(None)):
    """Bulk import configs from an array of local config objects.

    Body: {"configs": [<config_forge hub payload>, ...]}
    """
    _require_auth(authorization)
    body = await request.json()
    configs = body.get("configs", [])

    imported = 0
    updated = 0
    with _db() as conn:
        for c in configs:
            domain = c.get("domain", "")
            title = c.get("title", "")
            if not domain or not title:
                continue

            existing = conn.execute(
                "SELECT id FROM configs WHERE domain = ? AND title = ?",
                (domain, title),
            ).fetchone()

            now = _now()
            if existing:
                conn.execute(
                    """UPDATE configs SET url_pattern=?, description=?,
                       tools_json=?, updated_at=? WHERE id=?""",
                    (
                        c.get("urlPattern", "/**"),
                        c.get("description", ""),
                        json.dumps(c.get("tools", [])),
                        now,
                        existing["id"],
                    ),
                )
                updated += 1
            else:
                config_id = str(uuid.uuid4())[:8]
                conn.execute(
                    """INSERT INTO configs (id, domain, url_pattern, title, description,
                       tools_json, contributor, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        config_id,
                        domain,
                        c.get("urlPattern", "/**"),
                        title,
                        c.get("description", ""),
                        json.dumps(c.get("tools", [])),
                        "nexvigilant",
                        now,
                        now,
                    ),
                )
                imported += 1

    return {"imported": imported, "updated": updated, "total": imported + updated}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_init_db()

if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="NexVigilant Hub")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    if not HUB_TOKEN:
        print("ERROR: Set HUB_TOKEN environment variable", file=sys.stderr)
        sys.exit(1)

    print(f"NexVigilant Hub starting on {args.host}:{args.port}")
    print(f"  DB: {HUB_DB}")
    print(f"  Configs: no cap")
    uvicorn.run(app, host=args.host, port=args.port)
