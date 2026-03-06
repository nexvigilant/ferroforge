# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## FerroForge — NexVigilant Station

Rust MCP server + 19 PV domain configs (97 tools). The station binary reads JSON configs from `configs/` and exposes them as MCP tools over stdio.

## Build & Test

```bash
cargo build -p nexvigilant-station --release    # Build station binary
cargo test -p nexvigilant-station               # 29 integration tests
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
| `scripts/*_proxy.py` | Per-domain API proxy scripts (7 live, rest stub) |
| `scripts/config_forge.py` | Config generator + WebMCP Hub deployer |

## Config Inventory (19 configs, 97 tools)

**Live proxies (7):** openfda (7), clinicaltrials (5), pubmed (5), dailymed (3), rxnav (6), openvigilfrance (4), fda-accessdata (6)

**Stub configs (12):** ema (6), eudravigilance (4), vigiaccess (5), drugbank (5), meddra (4), ich (4), cioms (3), who-umc (4), fda-safety (4), science-drug-targets (6), science-genomics (6), science-hexim1 (10)

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

# Deploy (requires HUB_API_KEY env var)
HUB_API_KEY=<key> python3 scripts/config_forge.py deploy configs/openfda.json
```

Deploy only configs with live proxy scripts. Each deployment auto-adds NexVigilant branding and liability disclaimer.

## Key Gotchas

- **MCP client caching:** After rebuilding the binary, must `/mcp` restart in Claude Code or stale process returns old tools
- **Tool naming:** `{domain_underscored}_{tool_name_underscored}` (e.g., `api_fda_gov_search_adverse_events`)
- **outputSchema:** All 97 tools have outputSchema defined — required for MCP spec compliance
- **dispatch.py routes by domain prefix** — 8/8 domain prefixes smoke-tested
- **Science configs** route via `science_proxy.py`, not individual proxy files
- **Telemetry JSONL** at `~/ferroforge/station-telemetry.jsonl` — owner dashboard via `nexvigilant_station_health` meta-tool

## Workspace Members

| Crate | Purpose |
|-------|---------|
| `nexvigilant-station` | MCP server binary (the product) |
| `borrow_miner` | Educational Rust ownership game (Bevy) — separate product |
