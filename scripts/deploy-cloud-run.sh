#!/usr/bin/env bash
set -euo pipefail

# NexVigilant Station — Cloud Run Deployment (Canary)
# Deploys with 10% canary traffic, validates health, then promotes to 100%.
#
# Usage:
#   ./scripts/deploy-cloud-run.sh              # Canary deploy (10% → health check → 100%)
#   ./scripts/deploy-cloud-run.sh --sse        # SSE transport
#   ./scripts/deploy-cloud-run.sh --no-canary  # Skip canary, deploy to 100% immediately
#   ./scripts/deploy-cloud-run.sh --dry-run    # Show what would be deployed

PROJECT="nexvigilant-digital-clubhouse"
REGION="us-central1"
SERVICE="nexvigilant-station"
IMAGE="gcr.io/${PROJECT}/${SERVICE}:latest"
PORT=8080
TRANSPORT="combined"
DRY_RUN=false
CANARY=true
CANARY_PCT=10
HEALTH_WAIT=15

for arg in "$@"; do
    case "$arg" in
        --sse) TRANSPORT="sse" ;;
        --dry-run) DRY_RUN=true ;;
        --no-canary) CANARY=false ;;
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

# Build station binary locally (nexcore path deps require local build)
echo "--- Building station binary locally ---"
cd "$(dirname "$0")/.."
cargo build -p nexvigilant-station --release
echo "Binary built: $(ls -lh target/release/nexvigilant-station | awk '{print $5}')"

# Build container image
echo "--- Building container image ---"
gcloud builds submit \
    --project="$PROJECT" \
    --tag="$IMAGE" \
    --timeout=600s

# Deploy to Cloud Run — canary or full
echo "--- Deploying to Cloud Run ---"

deploy_args=(
    --project="$PROJECT"
    --region="$REGION"
    --image="$IMAGE"
    --platform=managed
    --allow-unauthenticated
    --port="$PORT"
    --cpu=1
    --memory=256Mi
    --min-instances=0
    --max-instances=3
    --timeout=300s
    --cpu-boost
    --set-env-vars="RUST_LOG=nexvigilant_station=info"
    --args="--config-dir,/app/configs,--telemetry-log,/tmp/station-telemetry.jsonl,--transport,$TRANSPORT,--host,0.0.0.0,--port,$PORT,--exclude-private"
    --description="NexVigilant Station — PV agent traffic routing (${TRANSPORT} transport)"
)

if $CANARY; then
    # Deploy new revision but do NOT route traffic to it yet
    deploy_args+=(--no-traffic)
    echo "Canary mode: deploying new revision without traffic..."
fi

gcloud run deploy "$SERVICE" "${deploy_args[@]}"

# Get the service URL
URL=$(gcloud run services describe "$SERVICE" \
    --project="$PROJECT" \
    --region="$REGION" \
    --format="value(status.url)")

if $CANARY; then
    # Get the latest revision name
    LATEST_REV=$(gcloud run revisions list \
        --service="$SERVICE" \
        --project="$PROJECT" \
        --region="$REGION" \
        --sort-by="~creationTimestamp" \
        --limit=1 \
        --format="value(metadata.name)")

    echo ""
    echo "--- Canary: routing ${CANARY_PCT}% traffic to ${LATEST_REV} ---"
    gcloud run services update-traffic "$SERVICE" \
        --project="$PROJECT" \
        --region="$REGION" \
        --to-revisions="${LATEST_REV}=${CANARY_PCT}"

    echo "Waiting ${HEALTH_WAIT}s for canary to stabilize..."
    sleep "$HEALTH_WAIT"

    # Health check the canary
    echo "--- Canary health check ---"
    health_response=$(curl -s -m 10 "$URL/health" 2>&1)
    health_status=$(echo "$health_response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unreachable")

    if [ "$health_status" = "ok" ]; then
        echo "Health: OK — promoting to 100%"
        gcloud run services update-traffic "$SERVICE" \
            --project="$PROJECT" \
            --region="$REGION" \
            --to-latest
        echo "Canary promoted to 100% traffic."
    else
        echo "CANARY FAILED — health status: ${health_status}"
        echo "Response: ${health_response}"
        echo ""
        echo "Rolling back: routing 100% to previous revision..."
        gcloud run services update-traffic "$SERVICE" \
            --project="$PROJECT" \
            --region="$REGION" \
            --to-latest
        echo "Rollback complete. New revision receives 0% traffic."
        echo "Investigate, then re-deploy or manually promote."
        exit 1
    fi
fi

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
