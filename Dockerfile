# NexVigilant Station — Multi-transport MCP server
# Supports: stdio (local), sse (mcp-remote), http (REST API), combined (SSE + HTTP)

# Stage 1: Build the Rust binary
FROM rust:1.93-slim AS builder

# Git SHA for version stamping — passed by CI, defaults to "unknown" for local builds.
# build.rs reads this env var since .git/ is excluded from the Docker context.
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}

WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY crates/ crates/

# Build release binary
RUN cargo build -p nexvigilant-station --release

# Stage 2: Minimal runtime image
FROM python:3.12-slim

# Station binary
COPY --from=builder /build/target/release/nexvigilant-station /usr/local/bin/nexvigilant-station

# Stable binaries first (change infrequently → better layer caching)
COPY bin/rsk /usr/local/bin/rsk

# Config files + proxy scripts (change with each feature)
COPY configs/ /app/configs/
COPY scripts/ /app/scripts/

# Microgram decision trees + chains (change with PV logic updates)
COPY micrograms/ /app/micrograms/
COPY chains/ /app/chains/

WORKDIR /app

# Cloud Run sends traffic to $PORT (default 8080)
ENV PORT=8080
ENV RUST_LOG=nexvigilant_station=info
ENV RSK_BINARY=/usr/local/bin/rsk
ENV MCG_DIR=/app/micrograms
ENV CHAINS_DIR=/app/chains

# Cloud Run uses its own startup probe at /health — Docker HEALTHCHECK not needed

# Combined transport: SSE (MCP protocol) + HTTP REST on one port
# SSE for mcp-remote/Claude Code, HTTP REST for any agent framework
ENTRYPOINT ["nexvigilant-station"]
CMD ["--config-dir", "/app/configs", "--telemetry-log", "/tmp/station-telemetry.jsonl", "--transport", "combined", "--host", "0.0.0.0", "--port", "8080", "--exclude-private"]
