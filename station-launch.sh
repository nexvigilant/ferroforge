#!/usr/bin/env bash
set -euo pipefail

# NexVigilant Station Launch Script
# Starts supergateway (StreamableHTTP on :8808) wrapping the station binary

STATION_BIN="$HOME/ferroforge/target/release/nexvigilant-station"
CONFIG_DIR="$HOME/ferroforge/configs"
TELEMETRY_LOG="$HOME/ferroforge/station-telemetry.jsonl"
PORT=8808

if ! [ -f "$STATION_BIN" ]; then
    echo "ERROR: Station binary not found at $STATION_BIN" >&2
    exit 1
fi

exec supergateway \
    --stdio "$STATION_BIN --config-dir $CONFIG_DIR --telemetry-log $TELEMETRY_LOG" \
    --outputTransport streamableHttp \
    --port "$PORT"
