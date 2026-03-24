#!/usr/bin/env bash
set -euo pipefail

# NexVigilant Station — Pre-Deploy Preflight Check
#
# Runs all validation gates before hub deployment.
# Exit 0 = safe to deploy. Exit 1 = blocker found.
#
# Usage:
#   ./scripts/preflight.sh                # Full preflight
#   ./scripts/preflight.sh --quick        # Skip Rust build (Python only)
#   ./scripts/preflight.sh --domain calc  # Filter test harness by domain

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPTS_DIR")"
QUICK=false
DOMAIN_FILTER=""

while [ $# -gt 0 ]; do
    case "$1" in
        --quick) QUICK=true ;;
        --domain) shift; DOMAIN_FILTER="$1" ;;
        --domain=*) DOMAIN_FILTER="${1#--domain=}" ;;
    esac
    shift
done

passed=0
failed=0
total=0

run_gate() {
    local name="$1"
    shift
    total=$((total + 1))
    echo ""
    echo "── Gate $total: $name ──"
    if "$@"; then
        echo "  ✓ $name"
        passed=$((passed + 1))
    else
        echo "  ✗ $name FAILED"
        failed=$((failed + 1))
    fi
}

echo "NexVigilant Station — Preflight Check"
echo "======================================"

# Gate 1: Config validity (Rust)
if [ "$QUICK" = false ]; then
    run_gate "Rust integration tests (37 tests)" \
        cargo test -p nexvigilant-station --quiet
fi

# Gate 2: Config file count
run_gate "Config inventory" bash -c '
    count=$(ls '"$PROJECT_DIR"'/configs/*.json 2>/dev/null | wc -l)
    echo "  Configs found: $count"
    if [ "$count" -lt 1 ]; then
        echo "  ERROR: No configs found"
        exit 1
    fi
    # Verify all configs parse as valid JSON
    errors=0
    for f in '"$PROJECT_DIR"'/configs/*.json; do
        if ! python3 -m json.tool "$f" > /dev/null 2>&1; then
            echo "  ERROR: Invalid JSON: $f"
            errors=$((errors + 1))
        fi
    done
    if [ "$errors" -gt 0 ]; then
        exit 1
    fi
    echo "  All $count configs parse as valid JSON"
'

# Gate 3: outputSchema coverage
run_gate "outputSchema on all tools" python3 "$SCRIPTS_DIR/gate_outputschema.py" "$PROJECT_DIR"

# Gate 4: Test harness (all tools)
harness_args=""
if [ -n "$DOMAIN_FILTER" ]; then
    harness_args="--domain $DOMAIN_FILTER"
fi
run_gate "Test harness smoke test" \
    python3 "$SCRIPTS_DIR/test_harness.py" $harness_args

# Gate 5: Calculation validation (math correctness — Rust parity tests)
run_gate "Calculation parity tests (47 cases)" \
    cargo test -p nexvigilant-station --test compute_parity

# Gate 6: Dispatch routing coverage
run_gate "Dispatch route coverage" python3 "$SCRIPTS_DIR/gate_dispatch.py" "$PROJECT_DIR"

echo ""
echo "======================================"
echo "Preflight: $passed/$total gates passed, $failed failed"
if [ "$failed" -gt 0 ]; then
    echo "BLOCKED — fix failures before deploying"
    exit 1
else
    echo "CLEAR — safe to deploy"
fi
