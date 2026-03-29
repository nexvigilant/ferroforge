#!/usr/bin/env python3
"""
NexVigilant MoltBrowser MCP Server — sovereign browser automation.

Replaces the third-party moltbrowser-mcp npm package. Queries
mcp.nexvigilant.com/configs/lookup for site configs instead of webmcp-hub.com.

MCP stdio server implementing:
  - browser_navigate(url)  → navigate + auto-discover configs from MoltBook
  - hub_execute(toolName, arguments) → execute a MoltBook config tool
  - browser_fallback(tool, arguments) → raw Playwright fallback
  - browser_press_key(key) → press a key
  - contribute_create_config(...) → POST to /configs/contribute
  - contribute_add_tool(...) → add tool to contributed config

Transport: stdio (JSON-RPC 2.0)
Config discovery: GET mcp.nexvigilant.com/configs/lookup?domain=X

Usage:
    Register in ~/.claude.json as MCP server:
    {
      "mcpServers": {
        "nexvigilant-moltbrowser": {
          "type": "stdio",
          "command": "python3",
          "args": ["/home/matthew/ferroforge/scripts/nexvigilant-moltbrowser-mcp.py"]
        }
      }
    }
"""

from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from typing import Any

MOLTBOOK_URL = "https://mcp.nexvigilant.com/configs/lookup"
CONTRIBUTE_URL = "https://mcp.nexvigilant.com/configs/contribute"
SERVER_NAME = "nexvigilant-moltbrowser"
SERVER_VERSION = "1.0.0"

# Global state
_browser = None
_page = None
_pw = None
_current_url = None
_discovered_tools: dict[str, dict] = {}  # toolName -> tool config


def _ensure_browser():
    """Launch browser if not already running."""
    global _browser, _page, _pw
    if _page is not None:
        return True
    try:
        from playwright.sync_api import sync_playwright
        _pw = sync_playwright().start()
        _browser = _pw.chromium.launch(headless=True)
        _page = _browser.new_page()
        return True
    except ImportError:
        return False


def _close_browser():
    """Close browser if running."""
    global _browser, _page, _pw
    if _browser:
        _browser.close()
        _browser = None
    if _pw:
        _pw.stop()
        _pw = None
    _page = None


def _discover_configs(domain: str) -> list[dict]:
    """Query MoltBook for configs matching a domain."""
    try:
        url = f"{MOLTBOOK_URL}?domain={urllib.parse.quote(domain)}"
        req = urllib.request.Request(url, headers={"User-Agent": f"{SERVER_NAME}/{SERVER_VERSION}"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("configs", [])
    except Exception:
        return []


import urllib.parse


def _snapshot_page() -> str:
    """Get a text snapshot of the current page."""
    if _page is None:
        return ""
    try:
        return _page.inner_text("body")[:5000]
    except Exception:
        return ""


# --- MCP Tool Handlers ---

def handle_browser_navigate(args: dict) -> dict:
    """Navigate to a URL and auto-discover MoltBook configs."""
    global _current_url, _discovered_tools

    url = args.get("url", "")
    if not url:
        return {"error": "url is required"}

    if not _ensure_browser():
        return {"error": "playwright not installed. Run: pip install playwright && playwright install chromium"}

    _page.goto(url, timeout=30000, wait_until="domcontentloaded")
    _page.wait_for_timeout(2000)
    _current_url = url

    # Extract domain for config lookup
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc

    # Auto-discover configs from MoltBook
    configs = _discover_configs(domain)
    _discovered_tools.clear()

    discovered_tool_list = []
    for config in configs:
        for tool in config.get("tools", []):
            tool_name = tool.get("name", "")
            _discovered_tools[tool_name] = tool
            discovered_tool_list.append({
                "name": tool_name,
                "description": tool.get("description", ""),
                "params": [p.get("name") for p in tool.get("inputSchema", {}).get("properties", {}).keys()]
                    if isinstance(tool.get("inputSchema", {}).get("properties"), dict) else [],
            })

    # Get page snapshot
    title = _page.title()
    snapshot = _snapshot_page()

    result = {
        "page": {
            "url": _page.url,
            "title": title,
        },
        "snapshot": snapshot[:2000],
    }

    if discovered_tool_list:
        result["hub_tools"] = discovered_tool_list
        result["note"] = f"Found {len(discovered_tool_list)} MoltBook tools for {domain}. Use hub_execute to run them."
    else:
        result["note"] = f"No MoltBook configs found for {domain}. Use browser_fallback for manual interaction."

    return result


def handle_hub_execute(args: dict) -> dict:
    """Execute a MoltBook-discovered tool against the current page."""
    tool_name = args.get("toolName", "")
    tool_args = args.get("arguments", {})

    if not tool_name:
        return {"error": "toolName is required"}
    if _page is None:
        return {"error": "No page open. Call browser_navigate first."}
    if tool_name not in _discovered_tools:
        available = list(_discovered_tools.keys())
        return {"error": f"Tool '{tool_name}' not found. Available: {available}"}

    tool = _discovered_tools[tool_name]

    # Execute based on tool execution config
    execution = tool.get("execution", {})
    fields = execution.get("fields", [])
    steps = execution.get("steps", [])
    result_selector = execution.get("resultSelector", "")
    result_extract = execution.get("resultExtract", "text")

    try:
        # Fill fields
        for field in fields:
            selector = field.get("selector", "")
            param_name = field.get("name", "")
            value = tool_args.get(param_name, "")
            if selector and value:
                _page.fill(selector, str(value))
                _page.wait_for_timeout(500)

        # Execute steps
        for step in steps:
            action = step.get("action", "")
            selector = step.get("selector", "")
            value = step.get("value", "")

            # Interpolate {{paramName}} in values
            if value and "{{" in value:
                for k, v in tool_args.items():
                    value = value.replace(f"{{{{{k}}}}}", str(v))

            if action == "click" and selector:
                _page.click(selector, timeout=10000)
            elif action == "fill" and selector:
                _page.fill(selector, value)
            elif action == "wait" and selector:
                _page.wait_for_selector(selector, timeout=10000)
            elif action == "navigate":
                nav_url = step.get("url", value)
                if nav_url:
                    _page.goto(nav_url, timeout=30000)

            _page.wait_for_timeout(500)

        # Auto-submit if configured
        if execution.get("autosubmit"):
            submit_sel = execution.get("submitSelector", "")
            if submit_sel:
                _page.click(submit_sel, timeout=10000)
            else:
                _page.keyboard.press("Enter")
            _page.wait_for_timeout(2000)

        # Wait for results
        wait_sel = execution.get("resultWaitSelector", "")
        if wait_sel:
            _page.wait_for_selector(wait_sel, timeout=15000)

        delay = execution.get("resultDelay", 1000)
        _page.wait_for_timeout(delay)

        # Extract results
        if result_selector:
            if result_extract == "list":
                elements = _page.query_selector_all(result_selector)
                results = [el.inner_text().strip() for el in elements[:50]]
                return {"results": results, "count": len(results)}
            elif result_extract == "table":
                tables = _page.query_selector_all(result_selector)
                rows = []
                for table in tables[:3]:
                    for row in table.query_selector_all("tr"):
                        cells = [c.inner_text().strip() for c in row.query_selector_all("th, td")]
                        if cells:
                            rows.append(cells)
                return {"table": rows, "row_count": len(rows)}
            elif result_extract == "html":
                el = _page.query_selector(result_selector)
                return {"html": el.inner_html() if el else ""}
            elif result_extract == "attribute":
                attr = execution.get("resultAttribute", "href")
                elements = _page.query_selector_all(result_selector)
                return {"values": [el.get_attribute(attr) for el in elements[:50]]}
            else:
                el = _page.query_selector(result_selector)
                return {"text": el.inner_text().strip() if el else ""}
        else:
            return {"text": _snapshot_page()[:3000]}

    except Exception as e:
        return {"error": f"Execution failed: {type(e).__name__}: {e}"}


def handle_browser_fallback(args: dict) -> dict:
    """Raw Playwright fallback for manual interaction."""
    tool = args.get("tool", "")
    tool_args = args.get("arguments", {})

    if not tool:
        return {
            "available_tools": [
                "browser_snapshot", "browser_click", "browser_type",
                "browser_fill", "browser_select_option", "browser_evaluate",
            ],
            "note": "Pass tool name + arguments. Use browser_snapshot to get element refs.",
        }

    if _page is None:
        return {"error": "No page open. Call browser_navigate first."}

    try:
        if tool == "browser_snapshot":
            return {"snapshot": _snapshot_page()[:5000], "url": _page.url, "title": _page.title()}
        elif tool == "browser_click":
            selector = tool_args.get("selector", "")
            if selector:
                _page.click(selector, timeout=10000)
                _page.wait_for_timeout(1000)
                return {"clicked": selector, "url": _page.url}
        elif tool == "browser_fill":
            selector = tool_args.get("selector", "")
            value = tool_args.get("value", "")
            if selector:
                _page.fill(selector, value)
                return {"filled": selector, "value": value}
        elif tool == "browser_type":
            selector = tool_args.get("selector", "")
            text = tool_args.get("text", "")
            if selector:
                _page.type(selector, text)
                return {"typed": text, "into": selector}
        elif tool == "browser_evaluate":
            expression = tool_args.get("expression", "")
            if expression:
                result = _page.evaluate(expression)
                return {"result": result}
        elif tool == "browser_select_option":
            selector = tool_args.get("selector", "")
            values = tool_args.get("values", [])
            if selector:
                _page.select_option(selector, values)
                return {"selected": values, "in": selector}
        else:
            return {"error": f"Unknown fallback tool: {tool}"}
    except Exception as e:
        return {"error": f"Fallback failed: {type(e).__name__}: {e}"}

    return {"error": "Missing required arguments"}


def handle_browser_press_key(args: dict) -> dict:
    """Press a keyboard key."""
    key = args.get("key", "")
    if not key:
        return {"error": "key is required"}
    if _page is None:
        return {"error": "No page open"}
    _page.keyboard.press(key)
    _page.wait_for_timeout(500)
    return {"pressed": key}


def handle_contribute_create_config(args: dict) -> dict:
    """Create a new config on the NexVigilant MoltBook hub."""
    domain = args.get("domain", "")
    title = args.get("title", "")
    description = args.get("description", "")

    if not domain or not title:
        return {"error": "domain and title are required"}

    # POST to MoltContrib
    payload = json.dumps({
        "domain": domain,
        "title": title,
        "description": description,
        "tools": args.get("tools", [{"name": "get-content", "description": "Extract page content"}]),
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            CONTRIBUTE_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return json.loads(body)
        except Exception:
            return {"error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"error": str(e)}


# --- MCP Protocol ---

TOOLS = [
    {
        "name": "browser_navigate",
        "description": "Navigate to a URL. Auto-discovers MoltBook configs for the domain — if tools exist, they appear in the response. Use hub_execute to run discovered tools.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL to navigate to"}},
            "required": ["url"],
        },
    },
    {
        "name": "hub_execute",
        "description": "Execute a MoltBook-discovered tool on the current page. After browser_navigate discovers tools, use this to run them with arguments.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "toolName": {"type": "string", "description": "Tool name from the navigation response"},
                "arguments": {"type": "object", "description": "Arguments for the tool"},
            },
            "required": ["toolName"],
        },
    },
    {
        "name": "browser_fallback",
        "description": "Raw Playwright fallback when hub tools are insufficient. Call without args to list available tools.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool": {"type": "string", "description": "Playwright tool name"},
                "arguments": {"type": "object", "description": "Tool arguments"},
            },
        },
    },
    {
        "name": "browser_press_key",
        "description": "Press a keyboard key.",
        "inputSchema": {
            "type": "object",
            "properties": {"key": {"type": "string", "description": "Key name (e.g., Enter, Tab, ArrowDown)"}},
            "required": ["key"],
        },
    },
    {
        "name": "contribute_create_config",
        "description": "Create a new config on the NexVigilant MoltBook hub. After manually interacting with a site, contribute the selectors back.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Site domain"},
                "title": {"type": "string", "description": "Config title"},
                "description": {"type": "string", "description": "What this config does"},
                "tools": {"type": "array", "description": "Tools array with name + description"},
            },
            "required": ["domain", "title"],
        },
    },
]

TOOL_HANDLERS = {
    "browser_navigate": handle_browser_navigate,
    "hub_execute": handle_hub_execute,
    "browser_fallback": handle_browser_fallback,
    "browser_press_key": handle_browser_press_key,
    "contribute_create_config": handle_contribute_create_config,
}


def handle_jsonrpc(request: dict) -> dict | None:
    """Handle a JSON-RPC 2.0 request."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "NexVigilant MoltBrowser — sovereign browser automation.\n\n"
                    "Navigate with browser_navigate. MoltBook configs are auto-discovered from "
                    "mcp.nexvigilant.com. If hub tools are found, use hub_execute to run them. "
                    "If not, use browser_fallback for raw Playwright. "
                    "After manual interaction, contribute configs back with contribute_create_config.\n\n"
                    "This server queries YOUR hub at mcp.nexvigilant.com — not webmcp-hub.com."
                ),
            },
        }

    if method == "notifications/initialized":
        return None  # Notification, no response

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        handler = TOOL_HANDLERS.get(tool_name)
        if not handler:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps({"error": f"Unknown tool: {tool_name}"})}],
                    "isError": True,
                },
            }

        result = handler(arguments)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
            },
        }

    # Unknown method
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main():
    """Run MCP stdio server loop."""
    import io
    reader = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")

    for line in reader:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = handle_jsonrpc(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
