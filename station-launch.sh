#!/usr/bin/env bash
set -euo pipefail

# NexVigilant Station Launch Script
# Native axum HTTP transport on :8808 — no supergateway wrapper

STATION_BIN="$HOME/ferroforge/target/release/nexvigilant-station"
CONFIG_DIR="$HOME/ferroforge/configs"
TELEMETRY_LOG="$HOME/ferroforge/station-telemetry.jsonl"
PORT=8808

if ! [ -f "$STATION_BIN" ]; then
    echo "ERROR: Station binary not found at $STATION_BIN" >&2
    exit 1
fi

exec "$STATION_BIN" \
    --config-dir "$CONFIG_DIR" \
    --telemetry-log "$TELEMETRY_LOG" \
    --transport http \
    --port "$PORT"
