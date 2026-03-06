#!/usr/bin/env bash
set -euo pipefail

# NexVigilant Station — Cloud Run Deployment
# Deploys the station as an HTTP/SSE service on Cloud Run
#
# Usage:
#   ./scripts/deploy-cloud-run.sh              # Deploy HTTP transport (Skyway)
#   ./scripts/deploy-cloud-run.sh --sse        # Deploy SSE transport (Highway)
#   ./scripts/deploy-cloud-run.sh --dry-run    # Show what would be deployed

PROJECT="nexvigilant-digital-clubhouse"
REGION="us-central1"
SERVICE="nexvigilant-station"
IMAGE="gcr.io/${PROJECT}/${SERVICE}:latest"
PORT=8080
TRANSPORT="http"
DRY_RUN=false

for arg in "$@"; do
    case "$arg" in
        --sse) TRANSPORT="sse" ;;
        --dry-run) DRY_RUN=true ;;
        *) echo "Unknown arg: $arg"; exit 1 ;;
    esac
done

echo "=== NexVigilant Station Deploy ==="
echo "Project:   $PROJECT"
echo "Region:    $REGION"
echo "Service:   $SERVICE"
echo "Transport: $TRANSPORT"
echo "Image:     $IMAGE"
echo ""

if $DRY_RUN; then
    echo "[DRY RUN] Would build and deploy. Exiting."
    exit 0
fi

# Build container image
echo "--- Building container image ---"
cd "$(dirname "$0")/.."
gcloud builds submit \
    --project="$PROJECT" \
    --tag="$IMAGE" \
    --timeout=600s

# Deploy to Cloud Run
echo "--- Deploying to Cloud Run ---"
gcloud run deploy "$SERVICE" \
    --project="$PROJECT" \
    --region="$REGION" \
    --image="$IMAGE" \
    --platform=managed \
    --allow-unauthenticated \
    --port="$PORT" \
    --cpu=1 \
    --memory=256Mi \
    --min-instances=0 \
    --max-instances=3 \
    --timeout=300s \
    --cpu-boost \
    --set-env-vars="RUST_LOG=nexvigilant_station=info" \
    --args="--config-dir,/app/configs,--telemetry-log,/tmp/station-telemetry.jsonl,--transport,$TRANSPORT,--host,0.0.0.0,--port,$PORT" \
    --description="NexVigilant Station — PV agent traffic routing (${TRANSPORT} transport)"

# Get the service URL
URL=$(gcloud run services describe "$SERVICE" \
    --project="$PROJECT" \
    --region="$REGION" \
    --format="value(status.url)")

echo ""
echo "=== Deployed ==="
echo "URL: $URL"
echo "Health: $URL/health"
echo ""
echo "Test:"
echo "  curl $URL/health"
echo "  curl $URL/tools | python3 -c 'import sys,json; print(len(json.load(sys.stdin)), \"tools\")'"
echo ""

if [ "$TRANSPORT" = "sse" ]; then
    echo "Highway (mcp-remote) config for external Claude Code users:"
    echo '  "nexvigilant-station": {'
    echo "    \"type\": \"sse\","
    echo "    \"url\": \"$URL/sse\""
    echo '  }'
else
    echo "Skyway (REST) endpoints:"
    echo "  GET  $URL/tools           — list all tools"
    echo "  POST $URL/tools/{name}    — call a tool (body = arguments)"
    echo "  POST $URL/rpc             — JSON-RPC 2.0 (full MCP protocol)"
    echo "  GET  $URL/health          — liveness check"
fi
