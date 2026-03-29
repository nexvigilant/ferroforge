# NexVigilant Station — Multi-transport MCP server
# Supports: stdio (local), sse (mcp-remote), http (REST API), combined (SSE + HTTP)

# Single-stage image — binary is pre-built locally via `cargo build --release`
# because Station depends on nexcore crates via local path deps that aren't
# available in the Docker build context.
FROM python:3.12-slim

# Station binary (pre-built locally)
COPY target/release/nexvigilant-station /usr/local/bin/nexvigilant-station

# Stable binaries first (change infrequently → better layer caching)
COPY bin/rsk /usr/local/bin/rsk

# NexCore MCP binary — enables the nexcore bridge proxy to handle
# 114+ rust-native configs that lack dedicated Station try_handle wiring.
# dispatch.py → nexcore_proxy.py → nexcore-mcp (stdio JSON-RPC)
COPY bin/nexcore-mcp /usr/local/bin/nexcore-mcp

# Config files + proxy scripts (change with each feature)
COPY configs/ /app/configs/
COPY scripts/ /app/scripts/

# Microgram decision trees + chains (change with PV logic updates)
COPY micrograms/ /app/micrograms/
COPY chains/ /app/chains/

# Relay chain definitions for the hopper engine
COPY relays/ /app/relays/

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
