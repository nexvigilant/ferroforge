#!/usr/bin/env python3
"""
NexCore Bridge Proxy — routes Station tool calls to the nexcore-mcp binary.

Covers all rust-native configs without dedicated try_handle in the Station
router. Translates Station tool names back to nexcore MCP names and calls
the binary via stdio JSON-RPC.

Station receives: stem_nexvigilant_com_stem_bio_cell_division
This proxy strips: stem_nexvigilant_com_ → stem_bio_cell_division
Calls nexcore-mcp: tools/call(stem_bio_cell_division, args)
Returns the result.
"""

import json
import os
import subprocess
import sys
import threading

def _find_nexcore_mcp() -> str:
    """Find nexcore-mcp binary — Cloud Run path first, then local dev."""
    env = os.environ.get("NEXCORE_MCP_BINARY")
    if env:
        return env
    for path in ["/usr/local/bin/nexcore-mcp",
                 os.path.expanduser("~/Projects/Active/nexcore/target/release/nexcore-mcp")]:
        if os.path.isfile(path):
            return path
    return "/usr/local/bin/nexcore-mcp"  # default (will error clearly if missing)

NEXCORE_MCP = _find_nexcore_mcp()

REQUEST_TIMEOUT = 25  # seconds


def strip_station_prefix(tool_name: str) -> str:
    """Strip the Station domain prefix to recover the nexcore MCP tool name."""
    marker = "_nexvigilant_com_"
    idx = tool_name.find(marker)
    if idx >= 0:
        return tool_name[idx + len(marker):]
    return tool_name


def call_nexcore(tool_name: str, arguments: dict) -> dict:
    """Call the nexcore-mcp binary via stdio JSON-RPC with proper handshake."""
    if not os.path.isfile(NEXCORE_MCP):
        return {"status": "error", "message": f"nexcore-mcp binary not found at {NEXCORE_MCP}"}

    try:
        proc = subprocess.Popen(
            [NEXCORE_MCP],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        return {"status": "error", "message": f"nexcore-mcp binary not found: {NEXCORE_MCP}"}

    # Collect stdout lines in a thread (non-blocking)
    lines: list[str] = []
    def read_stdout():
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            lines.append(line.strip())

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()

    try:
        # Step 1: Initialize
        init_req = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "nexvigilant-station-bridge", "version": "1.0.0"},
            },
        }) + "\n"
        proc.stdin.write(init_req)
        proc.stdin.flush()

        # Wait for init response
        _wait_for_response(lines, 1, timeout=5)

        # Step 2: initialized notification
        notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        proc.stdin.write(notif)
        proc.stdin.flush()

        # Step 3: tools/call via the `nexcore` unified dispatcher
        # The nexcore-mcp binary registers tools via #[tool] on the server handler,
        # but the 1,378 unified dispatch tools are only accessible through the
        # `nexcore` mega-tool which routes internally via unified.rs match table.
        call_req = json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {
                "name": "nexcore",
                "arguments": {"command": tool_name, "params": arguments},
            },
        }) + "\n"
        proc.stdin.write(call_req)
        proc.stdin.flush()

        # Wait for call response
        response = _wait_for_response(lines, 2, timeout=REQUEST_TIMEOUT)

        if response is None:
            return {"status": "error", "message": "No response from nexcore-mcp within timeout"}

        if "error" in response:
            err = response["error"]
            return {"status": "error", "message": err.get("message", "MCP error"), "code": err.get("code", -1)}

        # Extract text content
        mcp_result = response.get("result", {})
        content = mcp_result.get("content", [])
        if content:
            text = content[0].get("text", "")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"status": "ok", "raw": text}
        return {"status": "ok", "result": mcp_result}

    finally:
        try:
            proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            proc.kill()


def _wait_for_response(lines: list[str], expected_id: int, timeout: float) -> dict | None:
    """Poll collected lines for a JSON-RPC response with the expected id."""
    import time
    deadline = time.monotonic() + timeout
    seen = 0
    while time.monotonic() < deadline:
        while seen < len(lines):
            line = lines[seen]
            seen += 1
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("id") == expected_id:
                    return data
            except json.JSONDecodeError:
                continue
        time.sleep(0.01)
    return None


def main():
    try:
        raw = sys.stdin.read()
        envelope = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        json.dump({"status": "error", "message": f"Invalid JSON: {exc}"}, sys.stdout)
        return

    station_tool = envelope.get("tool", "")
    arguments = envelope.get("arguments", envelope.get("args", {}))

    nexcore_tool = strip_station_prefix(station_tool)
    result = call_nexcore(nexcore_tool, arguments)
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
