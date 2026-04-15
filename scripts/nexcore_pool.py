#!/usr/bin/env python3
"""
NexCore Connection Pool — persistent nexcore-mcp process for zero-handshake calls.

Instead of spawning a fresh nexcore-mcp per tool call (200-500ms overhead),
this module keeps a single process alive and reuses it across calls.

Usage:
    from nexcore_pool import get_pool
    pool = get_pool()
    result = pool.call("signal_detect", {"drug": "metformin", "event": "lactic acidosis"})

Architecture:
    Pool maintains one nexcore-mcp subprocess with stdin/stdout pipes.
    On first call: spawn + initialize handshake (~200ms one-time cost).
    Subsequent calls: JSON-RPC write + read (~5-20ms per call).
    Auto-respawns if process dies. Thread-safe via lock.
"""

import json
import os
import threading
import time

_REQUEST_TIMEOUT = 25  # seconds


def _find_nexcore_mcp() -> str:
    """Find nexcore-mcp binary — Cloud Run path first, then local dev."""
    env = os.environ.get("NEXCORE_MCP_BINARY")
    if env:
        return env
    for path in ["/usr/local/bin/nexcore-mcp",
                 os.path.expanduser("~/.cargo/bin/nexcore-mcp"),
                 os.path.expanduser("~/Projects/Active/nexcore/target/release/nexcore-mcp")]:
        if os.path.isfile(path):
            return path
    return "/usr/local/bin/nexcore-mcp"


class NexCorePool:
    """Persistent connection to a single nexcore-mcp process."""

    def __init__(self, binary: str | None = None):
        self._binary = binary or _find_nexcore_mcp()
        self._proc = None
        self._reader_thread = None
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._next_id = 10  # start after handshake IDs
        self._initialized = False

    def _spawn(self):
        """Spawn nexcore-mcp and complete the MCP handshake."""
        import subprocess
        self._lines.clear()
        self._next_id = 10
        self._initialized = False

        self._proc = subprocess.Popen(
            [self._binary],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Background reader thread
        def _read():
            while True:
                line = self._proc.stdout.readline()
                if not line:
                    break
                stripped = line.strip()
                if stripped:
                    self._lines.append(stripped)

        self._reader_thread = threading.Thread(target=_read, daemon=True)
        self._reader_thread.start()

        # MCP handshake: initialize
        init_req = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "nexcore-pool", "version": "1.0.0"},
            },
        }) + "\n"
        self._proc.stdin.write(init_req)
        self._proc.stdin.flush()
        self._wait_for_id(1, timeout=5)

        # MCP handshake: initialized notification
        notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        self._proc.stdin.write(notif)
        self._proc.stdin.flush()

        self._initialized = True

    def _is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _ensure_alive(self):
        if not self._is_alive():
            self._spawn()

    def _wait_for_id(self, expected_id: int, timeout: float = _REQUEST_TIMEOUT) -> dict | None:
        deadline = time.monotonic() + timeout
        seen = 0
        while time.monotonic() < deadline:
            while seen < len(self._lines):
                line = self._lines[seen]
                seen += 1
                try:
                    data = json.loads(line)
                    if data.get("id") == expected_id:
                        return data
                except json.JSONDecodeError:
                    continue
            time.sleep(0.005)
        return None

    def _send_and_wait(self, req_id: int, name: str, arguments: dict) -> dict | None:
        """Send a tools/call request and wait for response."""
        call_req = json.dumps({
            "jsonrpc": "2.0", "id": req_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }) + "\n"
        self._proc.stdin.write(call_req)
        self._proc.stdin.flush()
        return self._wait_for_id(req_id)

    def _parse_response(self, response: dict | None) -> dict:
        """Parse MCP response into a simple dict."""
        if response is None:
            return {"status": "error", "message": "No response from nexcore-mcp within timeout"}
        if "error" in response:
            err = response["error"]
            return {"status": "error", "message": err.get("message", "MCP error"), "code": err.get("code", -1)}
        mcp_result = response.get("result", {})
        content = mcp_result.get("content", [])
        if content:
            text = content[0].get("text", "")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"status": "ok", "raw": text}
        return {"status": "ok", "result": mcp_result}

    def call(self, tool_name: str, arguments: dict) -> dict:
        """Call a nexcore tool. Tries direct first-class, falls back to unified.

        Strategy: first-class #[tool] methods → unified nexcore dispatcher.
        This handles both 488 first-class tools and legacy unified-only tools.
        """
        with self._lock:
            self._ensure_alive()

            # 1. Try direct first-class tool call
            req_id = self._next_id
            self._next_id += 1
            try:
                response = self._send_and_wait(req_id, tool_name, arguments)
            except (BrokenPipeError, OSError):
                self._spawn()
                req_id = self._next_id
                self._next_id += 1
                response = self._send_and_wait(req_id, tool_name, arguments)

            result = self._parse_response(response)

            # 2. If "tool not found", fall back to unified dispatcher
            if result.get("status") == "error" and "not found" in result.get("message", "").lower():
                req_id = self._next_id
                self._next_id += 1
                try:
                    response = self._send_and_wait(
                        req_id, "nexcore",
                        {"command": tool_name, "params": arguments},
                    )
                except (BrokenPipeError, OSError):
                    self._spawn()
                    req_id = self._next_id
                    self._next_id += 1
                    response = self._send_and_wait(
                        req_id, "nexcore",
                        {"command": tool_name, "params": arguments},
                    )
                result = self._parse_response(response)

            return result

    def close(self):
        """Gracefully shut down the persistent process."""
        if self._proc:
            try:
                self._proc.stdin.close()
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                if self._proc:
                    self._proc.kill()
            self._proc = None
            self._initialized = False


# Module-level singleton
_pool: NexCorePool | None = None
_pool_lock = threading.Lock()


def get_pool() -> NexCorePool:
    """Get or create the module-level connection pool singleton."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = NexCorePool()
        return _pool


def strip_station_prefix(tool_name: str) -> str:
    """Strip the Station domain prefix to recover the nexcore MCP tool name."""
    marker = "_nexvigilant_com_"
    idx = tool_name.find(marker)
    if idx >= 0:
        name = tool_name[idx + len(marker):]
    else:
        name = tool_name
    # Station configs use hyphens, nexcore dispatch uses underscores
    return name.replace("-", "_")
