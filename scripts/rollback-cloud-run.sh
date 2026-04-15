#!/usr/bin/env bash
# NexVigilant Station — Cloud Run Rollback
#
# Usage:
#   ./scripts/rollback-cloud-run.sh            # Roll back to prior rev (100% traffic)
#   ./scripts/rollback-cloud-run.sh REV_NAME   # Roll back to specific rev
#   ./scripts/rollback-cloud-run.sh --list     # Show last 5 revisions
#
# Safe: Cloud Run revisions are immutable. Rollback = traffic-split update.
# No binary rebuild, no image rebuild, no DB migration to reverse (stateless).

set -euo pipefail

SERVICE="nexvigilant-station"
REGION="us-central1"

if [[ "${1:-}" == "--list" ]]; then
    gcloud run revisions list --service "$SERVICE" --region "$REGION" \
        --limit 5 --format="table(name,metadata.creationTimestamp,active)"
    exit 0
fi

# Determine target rev
if [[ -n "${1:-}" ]]; then
    TARGET="$1"
else
    # Second-most-recent rev (current = most recent active)
    TARGET=$(gcloud run revisions list --service "$SERVICE" --region "$REGION" \
        --limit 2 --sort-by="~metadata.creationTimestamp" \
        --format="value(name)" | tail -1)
fi

if [[ -z "$TARGET" ]]; then
    echo "ERROR: Could not determine rollback target" >&2
    exit 1
fi

CURRENT=$(gcloud run services describe "$SERVICE" --region "$REGION" \
    --format="value(status.latestReadyRevisionName)")

echo "=== Station Rollback ==="
echo "Current: $CURRENT"
echo "Target:  $TARGET"
echo ""

read -rp "Confirm traffic cutover $CURRENT → $TARGET? [y/N] " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { echo "Aborted"; exit 1; }

gcloud run services update-traffic "$SERVICE" \
    --region "$REGION" \
    --to-revisions "$TARGET=100"

echo ""
echo "=== Verifying ==="
sleep 3
curl -sf https://mcp.nexvigilant.com/health > /dev/null && echo "✓ /health OK" || echo "✗ /health FAILED — rolling forward"

echo ""
echo "Rolled back to $TARGET. To revert rollback: $0 $CURRENT"
