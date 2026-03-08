# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## FerroForge — NexVigilant Station

Rust MCP server + 23 PV domain configs (180 tools). The station binary reads JSON configs from `configs/` and exposes them as MCP tools over stdio (source: `ls configs/*.json | wc -l` = 23, tool count from JSON parsing = 180, measured 2026-03-08).

## Build & Test

```bash
cargo build -p nexvigilant-station --release    # Build station binary
cargo test -p nexvigilant-station               # 37 integration tests
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
| `scripts/*_proxy.py` | Per-domain API proxy scripts (17 files: 6 clean live, ~6 partial, ~5 new/untested — source: Matthew's 3-tier classification, 2026-03-06) |
| `scripts/config_forge.py` | Config generator + WebMCP Hub deployer |

## Config Inventory (23 configs, 180 tools — source: measured 2026-03-08)

**Proxy scripts with HTTP calls (10):** openfda, clinicaltrials, pubmed, dailymed, rxnav, openvigilfrance, fda-accessdata, eudravigilance, fda-safety, science

**Pure computation proxy (1):** calculation (17 tools — PRR/ROR/IC/EBGM, disproportionality table, Naranjo, WHO-UMC, ICH E2A, QBR, reporting rate, signal half-life, expectedness, time-to-onset, case completeness, NNH, Wilson CI, signal trend)

**Stub configs without proxies (3):** cioms, who-umc, science-hexim1

**NOTE:** Matthew reclassified proxies (2026-03-06) into 3 tiers: clean live (real API data) / partial (some mocked tools) / new-untested. The above 10 are files containing `requests.get/post` calls. For per-proxy tier classification, see MEMORY.md FerroForge section.

## Adding a New Config

1. Create `configs/{domain}.json` following the HubConfig schema (see `config.rs:9-58`)
2. Add proxy script at `scripts/{domain}_proxy.py` if tool needs live API calls
3. Wire domain prefix in `scripts/dispatch.py`
4. Run `cargo test -p nexvigilant-station` to verify config loads
5. Tools are immediately available to connected agents — no binary rebuild needed

## Hub Deployment (webmcp-hub.com)

```bash
# Preview what would be sent to the hub
python3 scripts/config_forge.py preview configs/openfda.json

# Deploy single config (requires HUB_API_KEY env var)
HUB_API_KEY=<key> python3 scripts/config_forge.py deploy configs/openfda.json

# Direct PATCH to known Hub ID (required at 50-config cap)
HUB_API_KEY=<key> python3 scripts/config_forge.py deploy configs/openfda.json --hub-id UUID

# Batch deploy all 20 configs using mapping file
HUB_API_KEY=<key> python3 scripts/config_forge.py batch-deploy hub-mapping.json
```

**Hub state (2026-03-08):** 20/22 configs deployed, 149 hub tools, 100% NexVigilant branded. 50-config cap, 30 remaining. 2 not deployed: linkedin, wikipedia. Use `--hub-id` or `batch-deploy` with `hub-mapping.json` for updates.

## Self-Hosted Hub (`hub/`)

NexVigilant Hub — self-hosted WebMCP config registry. Eliminates the 50-config cap.

```bash
# Start the hub (requires HUB_TOKEN)
HUB_TOKEN=<secret> python3 hub/app.py                      # Port 8787
HUB_TOKEN=<secret> python3 hub/app.py --port 9090          # Custom port

# Seed from local configs (no server needed)
python3 hub/seed.py --direct

# Seed via API (server must be running)
HUB_TOKEN=<token> python3 hub/seed.py

# Deploy via config_forge.py pointed at self-hosted hub
HUB_URL=http://127.0.0.1:8787 HUB_API_KEY=<token> python3 scripts/config_forge.py deploy configs/openfda.json
```

| File | Role |
|------|------|
| `hub/app.py` | FastAPI server — API-compatible with webmcp-hub.com |
| `hub/seed.py` | Seeds hub.db from `configs/` directory |
| `hub/hub.db` | SQLite database (23 configs, 180 tools) |

**Key endpoints:** POST/PATCH/GET/DELETE `/api/configs`, GET `/api/tools` (agent discovery), GET `/mcp/tools/list` (MCP-compatible), POST `/api/import` (bulk), GET `/api/stats`, GET `/health`.

## Key Gotchas

- **MCP client caching:** After rebuilding the binary, must `/mcp` restart in Claude Code or stale process returns old tools
- **Tool naming:** `{domain_underscored}_{tool_name_underscored}` (e.g., `api_fda_gov_search_adverse_events`)
- **outputSchema:** All 180 tools have outputSchema defined — required for MCP spec compliance
- **dispatch.py routes by domain prefix** — 8/8 domain prefixes smoke-tested
- **Science configs** route via `science_proxy.py`, not individual proxy files
- **Telemetry JSONL** at `~/ferroforge/station-telemetry.jsonl` — owner dashboard via `nexvigilant_station_health` meta-tool

## Workspace Members

| Crate | Purpose |
|-------|---------|
| `nexvigilant-station` | MCP server binary (the product) |
| `borrow_miner` | Educational Rust ownership game (Bevy) — separate product |
