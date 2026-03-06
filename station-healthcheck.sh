#!/usr/bin/env bash
set -euo pipefail

# Station Health Check — hits the public endpoint and verifies MCP response
ENDPOINT="https://station.nexvigilant.com/mcp"
TIMEOUT=10

response=$(curl -s -m "$TIMEOUT" -X POST "$ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' 2>&1)

if echo "$response" | grep -q '"tools"'; then
    echo "OK: station.nexvigilant.com responding with tools list"
    exit 0
else
    echo "FAIL: station.nexvigilant.com not responding correctly"
    echo "Response: $response"
    exit 1
fi
