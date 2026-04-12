#!/usr/bin/env python3
"""
Bot Tunnel proxy — routes Station tool calls to nexvigilant.com/api/bot/*

Tools:
  bot-signal-run    → GET /api/bot/signal?drug=X&event=Y
  bot-signal-custom → POST /api/bot/signal {targets: [...]}
  bot-stream-connect → Returns stream URL (SSE endpoint info)
"""

import json
import sys
import urllib.request
import urllib.error

BOT_BASE = "https://www.nexvigilant.com/api/bot"


def bot_signal_run(params: dict) -> dict:
    """GET /api/bot/signal with optional drug/event filters."""
    qs = []
    if params.get("drug"):
        qs.append(f"drug={urllib.parse.quote(params['drug'])}")
    if params.get("event"):
        qs.append(f"event={urllib.parse.quote(params['event'])}")

    url = f"{BOT_BASE}/signal"
    if qs:
        url += "?" + "&".join(qs)

    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read().decode("utf-8"))


def bot_signal_custom(params: dict) -> dict:
    """POST /api/bot/signal with custom targets."""
    targets = params.get("targets", [])
    if not targets:
        return {"error": "targets array is required"}

    payload = json.dumps({"targets": targets}).encode("utf-8")
    req = urllib.request.Request(
        f"{BOT_BASE}/signal",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read().decode("utf-8"))


def bot_stream_connect(params: dict) -> dict:
    """Return SSE stream URL — agents connect directly."""
    return {
        "stream_url": f"{BOT_BASE}/stream",
        "protocol": "text/event-stream",
        "events": ["health", "ml_model", "signal", "complete"],
        "note": "Connect via EventSource or curl -N. Signals stream as they arrive. Keep-alive health pings every 30s for 5 min.",
        "example": f"curl -N {BOT_BASE}/stream",
    }


import urllib.parse

DISPATCH = {
    "bot-signal-run": bot_signal_run,
    "bot-signal-custom": bot_signal_custom,
    "bot-stream-connect": bot_stream_connect,
}


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"error": "no input"}))
        sys.exit(1)

    try:
        req = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"error": "invalid JSON"}))
        sys.exit(1)

    tool = req.get("tool", "")
    params = req.get("params", req.get("arguments", {}))

    handler = DISPATCH.get(tool)
    if not handler:
        print(json.dumps({"error": f"unknown tool: {tool}", "available": list(DISPATCH.keys())}))
        sys.exit(1)

    try:
        result = handler(params)
        print(json.dumps(result))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(json.dumps({"error": f"HTTP {e.code}", "body": body[:500]}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


if __name__ == "__main__":
    main()
