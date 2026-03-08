# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## FerroForge — NexVigilant Station

Rust MCP server + 23 PV domain configs (174 tools). The station binary reads JSON configs from `configs/` and exposes them as MCP tools over stdio (source: `ls configs/*.json | wc -l` = 23, tool count from JSON parsing = 174, measured 2026-03-08).

## Build & Test

```bash
cargo build -p nexvigilant-station --release    # Build station binary
cargo test -p nexvigilant-station               # 44 integration tests
cargo clippy -p nexvigilant-station -- -D warnings

# MCP protocol test
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | ./target/release/nexvigilant-station --config-dir configs

# Telemetry log (ring buffer 10K + JSONL at station-telemetry.jsonl)
./target/release/nexvigilant-station --config-dir configs --telemetry-log
```

## Architecture

```
configs/*.json  -->  ConfigRegistry  -->  MCP tools/list  -->  Agent discovery
                                     -->  MCP tools/call  -->  Router  -->  dispatch.py  -->  proxy script
```

| Source | Role |
|--------|------|
| `crates/station/src/config.rs` | HubConfig schema + ConfigRegistry |
| `crates/station/src/protocol.rs` | JSON-RPC 2.0 + MCP types |
| `crates/station/src/router.rs` | Tool dispatch |
| `crates/station/src/server.rs` | Stdio MCP server loop |
| `crates/station/src/telemetry.rs` | Per-tool-call metrics (timestamp, domain, duration_ms, status) |
| `scripts/dispatch.py` | Unified proxy router — routes by domain prefix to per-domain proxy scripts |
| `scripts/*_proxy.py` | Per-domain API proxy scripts (21 files — source: measured 2026-03-08) |
| `scripts/config_forge.py` | Config generator + hub deployer (self-hosted or Cloud Run) |

## Config Inventory (23 configs, 174 tools — source: measured 2026-03-08)

**Proxy scripts with HTTP calls (10):** openfda, clinicaltrials, pubmed, dailymed, rxnav, openvigilfrance, fda-accessdata, eudravigilance, fda-safety, science

**Pure computation proxy (1):** calculation (17 tools — PRR/ROR/IC/EBGM, disproportionality table, Naranjo, WHO-UMC, ICH E2A, QBR, reporting rate, signal half-life, expectedness, time-to-onset, case completeness, NNH, Wilson CI, signal trend)

**All configs have proxy scripts** — 0 stubs remaining (measured 2026-03-08)

**NOTE:** Matthew reclassified proxies (2026-03-06) into 3 tiers: clean live (real API data) / partial (some mocked tools) / new-untested. The above 10 are files containing `requests.get/post` calls. For per-proxy tier classification, see MEMORY.md FerroForge section.

## Adding a New Config

1. Create `configs/{domain}.json` following the HubConfig schema (see `config.rs:9-58`)
2. Add proxy script at `scripts/{domain}_proxy.py` if tool needs live API calls
3. Wire domain prefix in `scripts/dispatch.py`
4. Run `cargo test -p nexvigilant-station` to verify config loads
5. Tools are immediately available to connected agents — no binary rebuild needed

## Production Deployment — Cloud Run (`mcp.nexvigilant.com`)

**Primary deployment target.** The station binary runs on Google Cloud Run with combined transport (SSE + HTTP REST), CORS enabled, and all 174 tools annotated with MCP annotations (`readOnlyHint: true`, `destructiveHint: false`).

```bash
# Build container and deploy
gcloud run deploy nexvigilant-station \
  --source . \
  --region us-central1 \
  --allow-unauthenticated

# Health check
curl https://mcp.nexvigilant.com/health

# MCP tools list (HTTP REST)
curl https://mcp.nexvigilant.com/tools

# SSE transport
curl https://mcp.nexvigilant.com/sse
```

**DNS:** `mcp.nexvigilant.com` and `station.nexvigilant.com` → `ghs.googlehosted.com` (Cloudflare DNS-only, not proxied). Google-managed TLS.

**Transports:**
- **Streamable HTTP** (`POST/GET/DELETE /mcp`) — MCP 2025-03-26 spec. Primary transport for Claude.ai Connectors. Session tracking optional (stateless when no `Mcp-Session-Id` header). Supports JSON-RPC batch arrays.
- **SSE** (`/sse`, `/message`) — Legacy MCP transport for mcp-remote / Claude Code.
- **HTTP REST** (`/rpc`, `/tools`, `/tools/{name}`) — Direct REST for any agent framework.
- **Health** (`/health`) — Liveness + stats.

All on single port. CORS enabled (`Access-Control-Allow-Origin: *`, `mcp-session-id` exposed).

### Claude.ai Custom Connector

Add as connector in Claude.ai Settings → Connectors:
- **URL:** `https://mcp.nexvigilant.com/mcp`
- **Auth:** None (authless — `NEXVIGILANT_API_KEYS` not set on Cloud Run)
- **Protocol:** MCP 2025-03-26 Streamable HTTP
- **Tools visible:** 129 (public configs only — `--exclude-private` filters 6 private configs)

Source: `crates/station/src/server_streamable.rs`. Session-optional design: Claude.ai doesn't forward `Mcp-Session-Id` header, so all requests process statelessly.

### Public vs Private Configs

`--exclude-private` flag in Dockerfile CMD filters configs with `"private": true`. 17 public configs (125 config tools + 4 Rust meta-tools = 129 served) are exposed on Cloud Run. 6 private configs (49 tools) are available locally via stdio/mcp-lazy-proxy but not on the public endpoint.

**DO NOT deploy to webmcp-hub.com.** The third-party hub has a 50-config cap and is no longer the primary deployment target. All agent traffic routes through `mcp.nexvigilant.com`.

**Deployment:** Use `scripts/deploy-cloud-run.sh` (canary by default: 10% → health check → 100%). Pass `--no-canary` for immediate full deploy.

### Service Level Objectives

| Metric | Target | Measurement |
|--------|--------|-------------|
| Availability | 99.5% monthly | Cloud Run uptime (allows ~3.6h downtime/month) |
| Latency P99 | <5s per tool call | Telemetry ring buffer `duration_ms` P99 |
| Error rate | <5% of tool calls | `StationHealth.error_rate_pct` |
| Proxy timeout | 30s hard kill | `router.rs` timeout on subprocess spawn |
| Rate limit response | <1ms | In-memory ring buffer scan |

**Error budget:** At 99.5%, the monthly budget is ~3.6 hours. Cloud Run cold starts (~2-5s) do NOT count against availability — only failed health checks do.

## Local Hub (`hub/`)

Self-hosted config registry for local development and seeding. Not the production deployment target.

```bash
# Start local hub
HUB_TOKEN=<secret> python3 hub/app.py                      # Port 8787

# Seed from local configs
python3 hub/seed.py --direct
```

| File | Role |
|------|------|
| `hub/app.py` | FastAPI server (local dev only) |
| `hub/seed.py` | Seeds hub.db from `configs/` directory |
| `hub/hub.db` | SQLite database (23 configs, 174 tools) |

## Key Gotchas

- **MCP client caching:** After rebuilding the binary, must `/mcp` restart in Claude Code or stale process returns old tools
- **Tool naming:** `{domain_underscored}_{tool_name_underscored}` (e.g., `api_fda_gov_search_adverse_events`)
- **outputSchema:** All 174 tools have outputSchema defined — required for MCP spec compliance
- **MCP annotations:** All 174 tools have `readOnlyHint: true`, `destructiveHint: false` — required for agent auto-approval
- **dispatch.py routes by domain prefix** — 8/8 domain prefixes smoke-tested
- **Science configs** route via `science_proxy.py`, not individual proxy files
- **Telemetry JSONL** at `~/ferroforge/station-telemetry.jsonl` — owner dashboard via `nexvigilant_station_health` meta-tool
- **DO NOT deploy to webmcp-hub.com** — production target is `mcp.nexvigilant.com` (Cloud Run)

## Workspace Members

| Crate | Purpose |
|-------|---------|
| `nexvigilant-station` | MCP server binary (the product) |
| `borrow_miner` | Educational Rust ownership game (Bevy) — separate product |
