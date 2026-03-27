#!/usr/bin/env bash
set -euo pipefail

# Prepare Docker build context by copying nexcore crate dependencies
# into the ferroforge repo so the Dockerfile can resolve them.

STATION_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NEXCORE_DIR="$HOME/Projects/Active/nexcore/crates"
DEPS_DIR="$STATION_DIR/nexcore-deps"

# Crates that Station depends on (from Cargo.toml)
CRATES=(
    nexcore-pv-core
    nexcore-qbr
    nexcore-primitives
    nexcore-constants
    nexcore-error
    nexcore-signal-theory
    nexcore-stoichiometry
    nexcore-lex-primitiva
    nexcore-preemptive-pv
)

echo "=== Preparing nexcore deps for Docker build ==="

rm -rf "$DEPS_DIR"
mkdir -p "$DEPS_DIR"

for crate in "${CRATES[@]}"; do
    src="$NEXCORE_DIR/$crate"
    if [ ! -d "$src" ]; then
        echo "ERROR: $src not found"
        exit 1
    fi
    echo "  Copying $crate..."
    mkdir -p "$DEPS_DIR/$crate"
    cp -a "$src/src" "$DEPS_DIR/$crate/src"
    cp "$src/Cargo.toml" "$DEPS_DIR/$crate/Cargo.toml"
done

# Transitive deps referenced via path by the above crates
for crate in nexcore-error-derive nexcore-chrono nexcore-id stem-math stem-bio stem-phys; do
    src="$NEXCORE_DIR/$crate"
    if [ -d "$src" ]; then
        echo "  Copying $crate (transitive)..."
        mkdir -p "$DEPS_DIR/$crate"
        cp -a "$src/src" "$DEPS_DIR/$crate/src"
        cp "$src/Cargo.toml" "$DEPS_DIR/$crate/Cargo.toml"
    fi
done

# Patch Cargo.toml paths for Docker context
CARGO_TOML="$STATION_DIR/crates/station/Cargo.toml"
cp "$CARGO_TOML" "$CARGO_TOML.local"
sed -i 's|path = "../../../Projects/Active/nexcore/crates/|path = "../../nexcore-deps/|g' "$CARGO_TOML"

echo ""
echo "=== Done: $(ls "$DEPS_DIR" | wc -l) crates copied ==="
echo "Restore local paths after deploy: cp $CARGO_TOML.local $CARGO_TOML"
