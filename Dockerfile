# NexVigilant Station — Multi-transport MCP server
# Supports: stdio (local), sse (mcp-remote), http (REST API)

# Stage 1: Build the Rust binary
FROM rust:1.93-slim AS builder

WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY crates/ crates/

# Build release binary
RUN cargo build -p nexvigilant-station --release

# Stage 2: Minimal runtime image
FROM python:3.12-slim

# Station binary
COPY --from=builder /build/target/release/nexvigilant-station /usr/local/bin/nexvigilant-station

# Config files + proxy scripts
COPY configs/ /app/configs/
COPY scripts/ /app/scripts/

WORKDIR /app

# Cloud Run sends traffic to $PORT (default 8080)
ENV PORT=8080
ENV RUST_LOG=nexvigilant_station=info

# Cloud Run uses its own startup probe at /health — Docker HEALTHCHECK not needed

# Default: HTTP transport on Cloud Run's $PORT
# Override with --transport sse for Highway mode
ENTRYPOINT ["nexvigilant-station"]
CMD ["--config-dir", "/app/configs", "--telemetry-log", "/tmp/station-telemetry.jsonl", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]
