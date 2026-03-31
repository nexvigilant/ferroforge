#!/usr/bin/env bash
set -euo pipefail

# NexVigilant Station — Persistent Local Server + Cloudflare Tunnel
# Run at boot via cron @reboot or manually.
# Manages both station HTTP server and cloudflared tunnel.
#
# Usage:
#   ./station-persistent.sh start    # Start station + tunnel
#   ./station-persistent.sh stop     # Stop both
#   ./station-persistent.sh status   # Health check
#   ./station-persistent.sh restart  # Stop + start

STATION_BIN="$HOME/ferroforge/target/release/nexvigilant-station"
CONFIG_DIR="$HOME/ferroforge/configs"
TELEMETRY_LOG="$HOME/ferroforge/station-telemetry.jsonl"
PORT=8808
STATION_PID_FILE="/tmp/nexvigilant-station-local.pid"
TUNNEL_PID_FILE="/tmp/cloudflared-station.pid"
STATION_LOG="/tmp/station-local.log"
TUNNEL_LOG="/tmp/cloudflared-tunnel.log"

start_station() {
    if [ -f "$STATION_PID_FILE" ] && kill -0 "$(cat "$STATION_PID_FILE")" 2>/dev/null; then
        echo "Station already running (PID $(cat "$STATION_PID_FILE"))"
        return 0
    fi

    if ! [ -f "$STATION_BIN" ]; then
        echo "ERROR: Binary not found at $STATION_BIN" >&2
        exit 1
    fi

    echo "Starting station on :${PORT}..."
    nohup "$STATION_BIN" \
        --config-dir "$CONFIG_DIR" \
        --telemetry-log "$TELEMETRY_LOG" \
        --transport combined \
        --host 0.0.0.0 \
        --port "$PORT" \
        --exclude-private \
        > "$STATION_LOG" 2>&1 &
    echo $! > "$STATION_PID_FILE"
    sleep 2

    if curl -s --max-time 5 "http://localhost:${PORT}/health" > /dev/null 2>&1; then
        echo "Station UP on :${PORT} (PID $(cat "$STATION_PID_FILE"))"
    else
        echo "WARN: Station started but health check failed. Check $STATION_LOG"
    fi
}

start_tunnel() {
    if [ -f "$TUNNEL_PID_FILE" ] && kill -0 "$(cat "$TUNNEL_PID_FILE")" 2>/dev/null; then
        echo "Tunnel already running (PID $(cat "$TUNNEL_PID_FILE"))"
        return 0
    fi

    echo "Starting cloudflare tunnel..."
    nohup /usr/local/bin/cloudflared tunnel run nexvigilant-station \
        > "$TUNNEL_LOG" 2>&1 &
    echo $! > "$TUNNEL_PID_FILE"
    sleep 3

    if grep -q "Registered tunnel connection" "$TUNNEL_LOG" 2>/dev/null; then
        local conns
        conns=$(grep -c "Registered tunnel connection" "$TUNNEL_LOG" 2>/dev/null || echo 0)
        echo "Tunnel UP ($conns connections, PID $(cat "$TUNNEL_PID_FILE"))"
    else
        echo "WARN: Tunnel started but no connections registered yet. Check $TUNNEL_LOG"
    fi
}

stop_all() {
    for pidfile in "$STATION_PID_FILE" "$TUNNEL_PID_FILE"; do
        if [ -f "$pidfile" ]; then
            local pid
            pid=$(cat "$pidfile")
            local name="${pidfile##*/}"
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid"
                echo "Stopped $name (PID $pid)"
            fi
            rm -f "$pidfile"
        fi
    done
    # Cleanup any orphaned processes
    pkill -f "nexvigilant-station.*${PORT}" 2>/dev/null || true
    pkill -f "cloudflared tunnel run nexvigilant-station" 2>/dev/null || true
}

status() {
    echo "=== NexVigilant Station Local ==="

    # Station
    if [ -f "$STATION_PID_FILE" ] && kill -0 "$(cat "$STATION_PID_FILE")" 2>/dev/null; then
        local health
        health=$(curl -s --max-time 3 "http://localhost:${PORT}/health" 2>/dev/null)
        if [ -n "$health" ]; then
            local configs tools transport
            configs=$(echo "$health" | python3 -c "import sys,json; print(json.load(sys.stdin)['configs'])" 2>/dev/null || echo "?")
            tools=$(echo "$health" | python3 -c "import sys,json; print(json.load(sys.stdin)['tools'])" 2>/dev/null || echo "?")
            transport=$(echo "$health" | python3 -c "import sys,json; print(json.load(sys.stdin)['transport'])" 2>/dev/null || echo "?")
            echo "Station: UP (PID $(cat "$STATION_PID_FILE")) | ${configs} configs | ${tools} tools | ${transport}"
        else
            echo "Station: PROCESS RUNNING (PID $(cat "$STATION_PID_FILE")) but health check failed"
        fi
    else
        echo "Station: DOWN"
    fi

    # Tunnel
    if [ -f "$TUNNEL_PID_FILE" ] && kill -0 "$(cat "$TUNNEL_PID_FILE")" 2>/dev/null; then
        local conns
        conns=$(grep -c "Registered tunnel connection" "$TUNNEL_LOG" 2>/dev/null || echo 0)
        echo "Tunnel:  UP (PID $(cat "$TUNNEL_PID_FILE")) | ${conns} QUIC connections"
    else
        echo "Tunnel:  DOWN"
    fi

    # DNS
    local dns_target
    dns_target=$(dig +short station.nexvigilant.com CNAME 2>/dev/null || echo "?")
    echo "DNS:     station.nexvigilant.com → ${dns_target:-[no CNAME]}"

    echo ""
    echo "Logs: $STATION_LOG | $TUNNEL_LOG"
}

case "${1:-status}" in
    start)
        start_station
        start_tunnel
        ;;
    stop)
        stop_all
        ;;
    restart)
        stop_all
        sleep 2
        start_station
        start_tunnel
        ;;
    status)
        status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
