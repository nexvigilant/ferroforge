# NexVigilant Station — Multi-transport MCP server
# Supports: stdio (local), sse (mcp-remote), http (REST API)

# Stage 1: Build the Rust binary
FROM rust:1.85-slim AS builder

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

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD curl -f http://localhost:${PORT}/health || exit 1

# Default: HTTP transport on Cloud Run's port
# Override with --transport sse for Highway mode
ENTRYPOINT ["nexvigilant-station"]
CMD ["--config-dir", "/app/configs", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]
