#!/usr/bin/env python3
"""
Wikipedia Proxy — routes MCP tool calls to the MediaWiki and REST APIs.

Usage:
    echo '{"tool": "search-articles", "arguments": {"query": "metformin"}}' | python3 wikipedia_proxy.py

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.

Two API surfaces:
  - MediaWiki Action API: en.wikipedia.org/w/api.php (search, parse, categories, links)
  - REST API v1: en.wikipedia.org/api/rest_v1/ (summaries, structured page data)
"""

import json
import re
import sys
import urllib.parse
import urllib.request
import urllib.error

MEDIAWIKI_API = "https://en.wikipedia.org/w/api.php"
REST_API = "https://en.wikipedia.org/api/rest_v1"
REQUEST_TIMEOUT_SECONDS = 15
USER_AGENT = "NexVigilant-FerroForge/1.0 (ferroforge@nexvigilant.com)"


def _fetch(url: str) -> dict:
    """Execute an HTTP GET and return parsed JSON."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        error_body = ""
        try:
            error_body = exc.read().decode("utf-8")[:500]
        except Exception:
            pass
        raise RuntimeError(f"HTTP {exc.code}: {exc.reason} — {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def _mediawiki(params: dict) -> dict:
    """Call the MediaWiki Action API with given parameters."""
    params["format"] = "json"
    params["formatversion"] = "2"
    qs = urllib.parse.urlencode(params, safe="")
    return _fetch(f"{MEDIAWIKI_API}?{qs}")


def _strip_html(html: str) -> str:
    """Remove HTML tags for plain-text output."""
    text = re.sub(r"<[^>]+>", "", html)
    return text.strip()


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def search_articles(args: dict) -> dict:
    """
    Tool: search-articles

    Full-text search across Wikipedia articles via the MediaWiki opensearch/query API.
    Returns titles, snippets, page IDs, and word counts.
    """
    query = args.get("query", "").strip()
    if not query:
        return {"status": "error", "message": "query is required", "count": 0, "results": []}

    limit = int(args.get("limit", 10))
    limit = max(1, min(limit, 50))

    data = _mediawiki({
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": str(limit),
        "srprop": "snippet|wordcount|timestamp",
    })

    search_info = data.get("query", {}).get("searchinfo", {})
    raw = data.get("query", {}).get("search", [])

    results = []
    for item in raw:
        results.append({
            "title": item.get("title", ""),
            "pageid": item.get("pageid"),
            "snippet": _strip_html(item.get("snippet", "")),
            "wordcount": item.get("wordcount", 0),
        })

    return {
        "status": "ok",
        "query": {"query": query, "limit": limit},
        "total_hits": search_info.get("totalhits", 0),
        "count": len(results),
        "results": results,
    }


def get_article_summary(args: dict) -> dict:
    """
    Tool: get-article-summary

    Get a structured summary via the Wikipedia REST API /page/summary endpoint.
    Returns title, description, extract, thumbnail, and content URLs.
    """
    title = args.get("title", "").strip()
    if not title:
        return {"status": "error", "message": "title is required"}

    encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url = f"{REST_API}/page/summary/{encoded}"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc)}

    thumbnail = data.get("thumbnail")
    thumb_out = None
    if thumbnail:
        thumb_out = {
            "source": thumbnail.get("source", ""),
            "width": thumbnail.get("width", 0),
            "height": thumbnail.get("height", 0),
        }

    content_urls = data.get("content_urls", {})
    urls_out = {}
    if content_urls:
        desktop = content_urls.get("desktop", {})
        mobile = content_urls.get("mobile", {})
        urls_out = {
            "desktop": desktop.get("page", ""),
            "mobile": mobile.get("page", ""),
        }

    return {
        "status": "ok",
        "title": data.get("title", title),
        "description": data.get("description", ""),
        "extract": data.get("extract", ""),
        "thumbnail": thumb_out,
        "content_urls": urls_out,
        "timestamp": data.get("timestamp", ""),
    }


def get_article_sections(args: dict) -> dict:
    """
    Tool: get-article-sections

    Get the section structure and plain-text content of a Wikipedia article.
    Uses MediaWiki parse API to extract sections with their text.
    """
    title = args.get("title", "").strip()
    if not title:
        return {"status": "error", "message": "title is required", "count": 0, "sections": []}

    section_idx = args.get("section")

    # First get section list
    data = _mediawiki({
        "action": "parse",
        "page": title,
        "prop": "sections",
    })

    if "error" in data:
        return {
            "status": "error",
            "message": data["error"].get("info", "Article not found"),
            "count": 0,
            "sections": [],
        }

    raw_sections = data.get("parse", {}).get("sections", [])

    # If a specific section is requested, fetch its text
    if section_idx is not None:
        section_idx = int(section_idx)
        text_data = _mediawiki({
            "action": "parse",
            "page": title,
            "prop": "wikitext",
            "section": str(section_idx),
        })
        wikitext = text_data.get("parse", {}).get("wikitext", "")
        # Find matching section title
        sec_title = ""
        sec_level = 2
        for s in raw_sections:
            if int(s.get("index", -1)) == section_idx:
                sec_title = s.get("line", "")
                sec_level = int(s.get("level", 2))
                break

        return {
            "status": "ok",
            "title": title,
            "count": 1,
            "sections": [{
                "index": section_idx,
                "title": sec_title,
                "level": sec_level,
                "text": wikitext[:5000],
            }],
        }

    # Return section outline (no text, to keep response lean)
    sections = []
    for s in raw_sections:
        sections.append({
            "index": int(s.get("index", 0)),
            "title": s.get("line", ""),
            "level": int(s.get("level", 2)),
            "text": "",
        })

    return {
        "status": "ok",
        "title": title,
        "count": len(sections),
        "sections": sections,
    }


def get_references(args: dict) -> dict:
    """
    Tool: get-references

    Extract external references from a Wikipedia article.
    Uses the MediaWiki parse API to get external links.
    """
    title = args.get("title", "").strip()
    if not title:
        return {"status": "error", "message": "title is required", "count": 0, "references": []}

    data = _mediawiki({
        "action": "parse",
        "page": title,
        "prop": "externallinks",
    })

    if "error" in data:
        return {
            "status": "error",
            "message": data["error"].get("info", "Article not found"),
            "count": 0,
            "references": [],
        }

    raw_links = data.get("parse", {}).get("externallinks", [])

    references = []
    for url in raw_links:
        references.append({
            "url": url,
            "text": "",
        })

    return {
        "status": "ok",
        "title": title,
        "count": len(references),
        "references": references,
    }


def get_categories(args: dict) -> dict:
    """
    Tool: get-categories

    Get all categories for a Wikipedia article via the MediaWiki query API.
    """
    title = args.get("title", "").strip()
    if not title:
        return {"status": "error", "message": "title is required", "count": 0, "categories": []}

    data = _mediawiki({
        "action": "query",
        "titles": title,
        "prop": "categories",
        "cllimit": "500",
    })

    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return {"status": "error", "message": "Article not found", "count": 0, "categories": []}

    page = pages[0] if isinstance(pages, list) else list(pages.values())[0]

    if "missing" in page:
        return {"status": "error", "message": f"Article '{title}' not found", "count": 0, "categories": []}

    raw_cats = page.get("categories", [])
    categories = [cat.get("title", "").replace("Category:", "") for cat in raw_cats]

    return {
        "status": "ok",
        "title": title,
        "count": len(categories),
        "categories": categories,
    }


def get_links(args: dict) -> dict:
    """
    Tool: get-links

    Get internal Wikipedia article links from a page.
    Useful for knowledge graph traversal and related article discovery.
    """
    title = args.get("title", "").strip()
    if not title:
        return {"status": "error", "message": "title is required", "count": 0, "links": []}

    limit = int(args.get("limit", 50))
    limit = max(1, min(limit, 500))

    data = _mediawiki({
        "action": "query",
        "titles": title,
        "prop": "links",
        "pllimit": str(limit),
        "plnamespace": "0",
    })

    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return {"status": "error", "message": "Article not found", "count": 0, "links": []}

    page = pages[0] if isinstance(pages, list) else list(pages.values())[0]

    if "missing" in page:
        return {"status": "error", "message": f"Article '{title}' not found", "count": 0, "links": []}

    raw_links = page.get("links", [])
    links = [link.get("title", "") for link in raw_links]

    return {
        "status": "ok",
        "title": title,
        "count": len(links),
        "links": links,
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

TOOL_DISPATCH = {
    "search-articles": search_articles,
    "get-article-summary": get_article_summary,
    "get-article-sections": get_article_sections,
    "get-references": get_references,
    "get-categories": get_categories,
    "get-links": get_links,
}


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        result = {"status": "error", "message": "No input received on stdin", "count": 0, "results": []}
        print(json.dumps(result))
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        result = {"status": "error", "message": f"Invalid JSON input: {exc}", "count": 0, "results": []}
        print(json.dumps(result))
        sys.exit(1)

    tool_name = payload.get("tool", "").strip()
    args = payload.get("arguments", payload.get("args", {}))

    if tool_name not in TOOL_DISPATCH:
        known = list(TOOL_DISPATCH.keys())
        result = {
            "status": "error",
            "message": f"Unknown tool '{tool_name}'. Known tools: {known}",
            "count": 0,
            "results": [],
        }
        print(json.dumps(result))
        sys.exit(1)

    handler = TOOL_DISPATCH[tool_name]
    try:
        result = handler(args)
    except RuntimeError as exc:
        result = {"status": "error", "error": True, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        result = {
            "status": "error",
            "error": True,
            "message": f"Unexpected error in '{tool_name}': {type(exc).__name__}: {exc}",
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
