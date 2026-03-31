# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## FerroForge — NexVigilant Station

Rust MCP server + 243 domain configs (2,018 tools). The station binary reads JSON configs from `configs/` and exposes them as MCP tools over stdio, SSE, and Streamable HTTP. Forge pipeline: `forge.py` (YAML→config), `forge_from_crates.py` (nexcore→config), `forge_nucleus.py` (config→page). Nexcore bridge proxy covers 119 rust-native gap configs via `nexcore_proxy.py`. 55 proxy scripts total. (measured 2026-03-31)

## Build & Test

```bash
cargo build -p nexvigilant-station --release    # Build station binary
cargo test -p nexvigilant-station               # 136 tests (75 integration + 47 unit + 14 lib)
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
| `scripts/*_proxy.py` | Per-domain API proxy scripts (39 files — source: measured 2026-03-29) |
| `scripts/forge.py` | Config generator from YAML specs |
| `scripts/forge_from_crates.py` | Config generator from nexcore MCP tool introspection |
| `scripts/forge_nucleus.py` | Nucleus page scaffolder from Station configs |
| `scripts/nexcore_proxy.py` | Bridge proxy: routes rust-native gaps to nexcore-mcp binary |
| `scripts/config_forge.py` | Config generator + hub deployer (self-hosted or Cloud Run) |

## Config Inventory (243 configs, 2,018 tools — source: measured 2026-03-31)

**Live API proxies (10):** openfda, clinicaltrials, pubmed, dailymed, rxnav, openvigilfrance, fda-accessdata, eudravigilance, fda-safety, science

**Pure computation proxies (3):** calculation (17 tools), microgram (33 tools — chains + singles including SOTA tracker), primitives

**Rust-native handlers (17):** signal-theory, preemptive-pv, epidemiology, stoichiometry, molecular-weight, game-theory, entropy, combinatorics, formula, markov, relay, brain, marketing, crystalbook, bicone, helix, heligram

**Reference configs:** ich, cioms, who-umc, meddra, drugbank, vigiaccess, ema, fda-safety, wikipedia, compliance, algovigilance, chemivigilance, cccp, harm-taxonomy, tov, pvdsl, dtree, dataframe, edit-distance, energy, zeta, dna, benefit-risk, vigilance

**All 243 configs have proxy scripts or Rust-native handlers** — 0 stubs remaining. 55 proxy files serve 243 configs. 119 rust-native gap configs routed through nexcore bridge proxy (`nexcore_proxy.py` → `nexcore-mcp` binary via stdio JSON-RPC).

**Metering:** Live toll billing at 1.30x harness premium. `/billing/usage`, `/billing/rates`, `/billing/balance` endpoints. Per-key usage tracking with token estimation and cost computation.

## Adding New Configs

**Preferred: Forge pipeline (fast path)**
```bash
# From nexcore crate tools (auto-introspect unified.rs)
python3 scripts/forge_from_crates.py generate

# From YAML spec (external APIs)
python3 scripts/forge.py from-spec domains/spec.yaml

# Scaffold Nucleus pages for new configs
python3 scripts/forge_nucleus.py batch

# Audit for gaps
python3 scripts/forge.py audit
```

**Manual path:**
1. Create `configs/{domain}.json` following the HubConfig schema (see `config.rs:9-58`)
2. Add proxy script at `scripts/{domain}_proxy.py` if tool needs live API calls
3. Wire domain prefix in `scripts/dispatch.py`
4. Run `cargo test -p nexvigilant-station` to verify config loads
5. Tools are immediately available to connected agents — no binary rebuild needed

## Production Deployment — Cloud Run (`mcp.nexvigilant.com`)

**Primary deployment target.** The station binary runs on Google Cloud Run with combined transport (Streamable HTTP + SSE + HTTP REST), CORS enabled, and all tools annotated with MCP annotations (`readOnlyHint: true`, `destructiveHint: false`).

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
- **Tools visible:** ~340 (public configs only — `--exclude-private` filters private configs)

Source: `crates/station/src/server_streamable.rs`. Session-optional design: Claude.ai doesn't forward `Mcp-Session-Id` header, so all requests process statelessly.

### Public vs Private Configs

`--exclude-private` flag in Dockerfile CMD filters configs with `"private": true`. Public configs are exposed on Cloud Run (~340 tools). Private configs are available locally via stdio but not on the public endpoint.

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
| `hub/hub.db` | SQLite database (legacy — local dev only) |

## Key Gotchas

- **MCP client caching:** After rebuilding the binary, must `/mcp` restart in Claude Code or stale process returns old tools
- **Tool naming:** `{domain_underscored}_{tool_name_underscored}` (e.g., `api_fda_gov_search_adverse_events`)
- **outputSchema:** All tools have outputSchema defined — required for MCP spec compliance
- **MCP annotations:** All tools have `readOnlyHint: true`, `destructiveHint: false` — required for agent auto-approval
- **dispatch.py routes by domain prefix** — 8/8 domain prefixes smoke-tested
- **Science configs** route via `science_proxy.py`, not individual proxy files
- **Telemetry JSONL** at `~/ferroforge/station-telemetry.jsonl` — owner dashboard via `nexvigilant_station_health` meta-tool
- **DO NOT deploy to webmcp-hub.com** — production target is `mcp.nexvigilant.com` (Cloud Run)

## Workspace Members

| Crate | Purpose |
|-------|---------|
| `nexvigilant-station` | MCP server binary (the product) |
| `borrow_miner` | Educational Rust ownership game (Bevy) — separate product |
