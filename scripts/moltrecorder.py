#!/usr/bin/env python3
"""
MoltRecorder — Capture CSS selectors during browser sessions and auto-generate configs.

Launches a headed Playwright browser, records user interactions (clicks, fills,
navigations), captures CSS selectors for each interaction, and generates a
MoltBook config JSON ready for MoltContrib submission.

Usage:
    python3 moltrecorder.py https://www.adrreports.eu     # Record a session
    python3 moltrecorder.py --replay config.json           # Replay a recorded config
    python3 moltrecorder.py --contribute config.json       # Submit to MoltContrib

The recorder produces:
1. A MoltBook config JSON with tools, selectors, and extraction rules
2. A proxy script via MoltProxy (optional, with --generate-proxy)

Requires: playwright (pip install playwright && playwright install chromium)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse


def record_session(url: str, output_path: str | None = None) -> dict:
    """Launch a headed browser and record user interactions.

    Records:
    - Page navigations (URL changes)
    - Clicks (element selector + text content)
    - Form fills (input selector + field name)
    - Table structures (for result extraction)

    Returns a MoltBook config JSON.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Error: playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path

    print(f"MoltRecorder — Recording session on {domain}")
    print(f"Navigate the site manually. Press Ctrl+C when done.")
    print(f"Recording clicks, fills, and page structure...\n")

    interactions = []
    tables_found = []
    pages_visited = []

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False)  # HEADED — user sees the browser
    context = browser.new_context()
    page = context.new_page()

    # Inject interaction recorder script
    recorder_js = """
    window.__moltRecorder = {
        interactions: [],
        record: function(type, selector, value, text) {
            this.interactions.push({
                type: type,
                selector: selector,
                value: value || null,
                text: text || null,
                timestamp: Date.now(),
                url: window.location.href
            });
        }
    };

    // Record clicks
    document.addEventListener('click', function(e) {
        var el = e.target;
        var selector = '';

        // Build best selector: data-testid > id > name > css path
        if (el.dataset && el.dataset.testid) {
            selector = '[data-testid="' + el.dataset.testid + '"]';
        } else if (el.id) {
            selector = '#' + el.id;
        } else if (el.name) {
            selector = el.tagName.toLowerCase() + '[name="' + el.name + '"]';
        } else if (el.className && typeof el.className === 'string') {
            var classes = el.className.trim().split(/\\s+/).slice(0, 2).join('.');
            if (classes) selector = el.tagName.toLowerCase() + '.' + classes;
        }

        if (!selector) {
            // CSS path fallback
            var path = [];
            var current = el;
            while (current && current !== document.body) {
                var tag = current.tagName.toLowerCase();
                if (current.id) { path.unshift('#' + current.id); break; }
                var idx = 1;
                var sib = current.previousElementSibling;
                while (sib) { if (sib.tagName === current.tagName) idx++; sib = sib.previousElementSibling; }
                path.unshift(tag + ':nth-of-type(' + idx + ')');
                current = current.parentElement;
            }
            selector = path.join(' > ');
        }

        window.__moltRecorder.record('click', selector, null, (el.textContent || '').trim().substring(0, 100));
    }, true);

    // Record input changes
    document.addEventListener('input', function(e) {
        var el = e.target;
        var selector = '';
        if (el.id) selector = '#' + el.id;
        else if (el.name) selector = el.tagName.toLowerCase() + '[name="' + el.name + '"]';
        else selector = el.tagName.toLowerCase() + '[type="' + (el.type || 'text') + '"]';

        window.__moltRecorder.record('fill', selector, el.value, el.name || el.id || '');
    }, true);

    // Record form submissions
    document.addEventListener('submit', function(e) {
        var form = e.target;
        var selector = form.id ? '#' + form.id : 'form';
        window.__moltRecorder.record('submit', selector, null, null);
    }, true);
    """

    def inject_recorder():
        """Inject recorder script into current page."""
        try:
            page.evaluate(recorder_js)
        except Exception:
            pass

    def collect_interactions():
        """Collect recorded interactions from the page."""
        try:
            data = page.evaluate("JSON.stringify(window.__moltRecorder ? window.__moltRecorder.interactions : [])")
            return json.loads(data)
        except Exception:
            return []

    def scan_tables():
        """Scan page for table structures."""
        try:
            table_data = page.evaluate("""
                (function() {
                    var tables = document.querySelectorAll('table');
                    var results = [];
                    for (var i = 0; i < tables.length; i++) {
                        var t = tables[i];
                        var headers = [];
                        var ths = t.querySelectorAll('th');
                        for (var j = 0; j < ths.length; j++) {
                            headers.push(ths[j].textContent.trim());
                        }
                        var rows = t.querySelectorAll('tr').length;
                        var selector = t.id ? '#' + t.id :
                            (t.className ? 'table.' + t.className.trim().split(/\\s+/)[0] : 'table');
                        if (rows > 1) {
                            results.push({selector: selector, headers: headers, rows: rows});
                        }
                    }
                    return results;
                })()
            """)
            return table_data
        except Exception:
            return []

    # Navigate and start recording
    page.goto(url, wait_until="domcontentloaded")
    inject_recorder()
    pages_visited.append(url)

    # Re-inject on navigation
    page.on("load", lambda: inject_recorder())

    # Monitor for URL changes and collect data
    try:
        while True:
            time.sleep(2)

            # Collect interactions
            new_interactions = collect_interactions()
            if new_interactions:
                interactions.extend(new_interactions)
                # Clear collected interactions
                try:
                    page.evaluate("if(window.__moltRecorder) window.__moltRecorder.interactions = [];")
                except Exception:
                    pass

            # Track page changes
            try:
                current_url = page.url
                if current_url not in pages_visited:
                    pages_visited.append(current_url)
                    inject_recorder()
                    print(f"  Page: {current_url}")
            except Exception:
                pass

            # Scan for tables periodically
            new_tables = scan_tables()
            for t in new_tables:
                if t not in tables_found:
                    tables_found.append(t)

    except KeyboardInterrupt:
        print(f"\n\nRecording stopped.")
        # Final collection
        interactions.extend(collect_interactions())

    browser.close()
    pw.stop()

    # Deduplicate interactions
    seen = set()
    unique_interactions = []
    for i in interactions:
        key = (i.get("type"), i.get("selector"), i.get("value"))
        if key not in seen:
            seen.add(key)
            unique_interactions.append(i)

    print(f"Recorded: {len(unique_interactions)} interactions, {len(tables_found)} tables, {len(pages_visited)} pages")

    # Generate MoltBook config from recorded interactions
    config = generate_config(domain, unique_interactions, tables_found, pages_visited)

    # Save config
    if output_path is None:
        slug = domain.replace(".", "-").replace("/", "_")
        output_path = f"configs/{slug}-recorded.json"

    Path(output_path).write_text(json.dumps(config, indent=2))
    print(f"Config saved: {output_path}")
    print(f"Tools generated: {len(config.get('tools', []))}")

    return config


def generate_config(domain: str, interactions: list, tables: list, pages: list) -> dict:
    """Generate a MoltBook config from recorded session data."""
    tools = []

    # Group interactions by type
    clicks = [i for i in interactions if i.get("type") == "click"]
    fills = [i for i in interactions if i.get("type") == "fill"]
    submits = [i for i in interactions if i.get("type") == "submit"]

    # Generate extraction tools for tables found
    for i, table in enumerate(tables):
        tool_name = f"get-table-{i+1}"
        if table.get("headers"):
            # Use first header word as tool name hint
            hint = table["headers"][0].lower().replace(" ", "-")[:20]
            tool_name = f"get-{hint}"

        tools.append({
            "name": tool_name,
            "description": f"Extract table data ({table.get('rows', 0)} rows, headers: {', '.join(table.get('headers', [])[:5])})",
            "parameters": [],
            "execution": {
                "selector": table.get("selector", "table"),
                "resultSelector": f"{table.get('selector', 'table')} tr",
                "resultExtract": "table",
            },
        })

    # Generate click tools for navigation elements
    nav_clicks = [c for c in clicks if c.get("text") and len(c.get("text", "")) > 2]
    for click in nav_clicks[:10]:  # Cap at 10 click tools
        text = click.get("text", "")[:30].strip()
        slug = text.lower().replace(" ", "-").replace("/", "-")[:20]
        tools.append({
            "name": f"click-{slug}",
            "description": f"Click: {text}",
            "execution": {
                "steps": [{"action": "click", "selector": click.get("selector", "")}],
            },
        })

    # Generate fill tools for form inputs
    for fill in fills[:10]:
        field_name = fill.get("text") or fill.get("selector", "field")
        slug = field_name.lower().replace(" ", "-").replace("[", "").replace("]", "")[:20]
        tools.append({
            "name": f"fill-{slug}",
            "description": f"Fill field: {field_name}",
            "parameters": [
                {"name": "value", "type": "string", "description": f"Value for {field_name}", "required": True},
            ],
            "execution": {
                "selector": fill.get("selector", ""),
                "fields": [{"type": "text", "selector": fill.get("selector", ""), "name": "value", "description": f"Value for {field_name}"}],
            },
        })

    # Generate search tool if form submission was recorded
    if submits:
        search_fields = [{"name": f.get("text", "query"), "type": "string",
                         "description": f"Search input", "required": True} for f in fills[:3]]
        tools.insert(0, {
            "name": "search",
            "description": f"Submit search form on {domain}",
            "parameters": search_fields if search_fields else [
                {"name": "query", "type": "string", "description": "Search query", "required": True}
            ],
            "execution": {
                "selector": submits[0].get("selector", "form"),
                "fields": [{"type": "text", "selector": f.get("selector", ""), "name": f.get("text", "query"),
                           "description": "Search input"} for f in fills[:3]],
                "autosubmit": True,
            },
        })

    # If no tools were generated, create a basic get-content tool
    if not tools:
        tools.append({
            "name": "get-content",
            "description": f"Extract page content from {domain}",
            "parameters": [],
            "execution": {
                "selector": "body",
                "resultSelector": "body",
                "resultExtract": "text",
            },
        })

    return {
        "domain": domain,
        "url_pattern": "/*",
        "title": f"{domain} (MoltRecorder)",
        "description": f"Auto-generated config from MoltRecorder session. {len(interactions)} interactions recorded across {len(pages)} pages.",
        "tools": tools,
        "metadata": {
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pages_visited": pages,
            "interaction_count": len(interactions),
            "table_count": len(tables),
        },
    }


def contribute_config(config_path: str, station_url: str = "https://mcp.nexvigilant.com") -> None:
    """Submit a recorded config to MoltContrib."""
    import urllib.request
    import urllib.error

    with open(config_path) as f:
        config = json.load(f)

    # Strip metadata before submitting
    config.pop("metadata", None)

    data = json.dumps(config).encode("utf-8")
    req = urllib.request.Request(
        f"{station_url}/configs/contribute",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read().decode("utf-8"))
        print(f"Contributed: {result.get('status')}")
        print(f"  Domain: {result.get('domain')}")
        print(f"  Tools: {result.get('toolCount')}")
        print(f"  Path: {result.get('configPath')}")
    except urllib.error.HTTPError as e:
        error = json.loads(e.read().decode("utf-8"))
        print(f"Error: {error.get('message')}")


def main() -> None:
    if len(sys.argv) < 2:
        print("MoltRecorder — Capture CSS selectors and auto-generate configs")
        print()
        print("Usage:")
        print("  python3 moltrecorder.py <url>                    # Record a session")
        print("  python3 moltrecorder.py <url> -o output.json     # Record to specific file")
        print("  python3 moltrecorder.py --contribute config.json # Submit to MoltContrib")
        print("  python3 moltrecorder.py --generate-proxy config  # Also generate proxy script")
        sys.exit(1)

    if sys.argv[1] == "--contribute":
        if len(sys.argv) < 3:
            print("Error: --contribute requires a config.json path")
            sys.exit(1)
        contribute_config(sys.argv[2])
        return

    url = sys.argv[1]
    if not url.startswith("http"):
        url = f"https://{url}"

    output = None
    if "-o" in sys.argv:
        idx = sys.argv.index("-o")
        if idx + 1 < len(sys.argv):
            output = sys.argv[idx + 1]

    config = record_session(url, output)

    # Optionally generate proxy script
    if "--generate-proxy" in sys.argv:
        import importlib.util
        spec = importlib.util.spec_from_file_location("moltproxy", Path(__file__).parent / "moltproxy_generate.py")
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            script = mod.generate_proxy(config, use_browser=True)
            slug = mod.slugify(config.get("domain", "unknown"))
            proxy_path = Path(__file__).parent / f"{slug}_proxy.py"
            proxy_path.write_text(script)
            print(f"Proxy script: {proxy_path}")


if __name__ == "__main__":
    main()
