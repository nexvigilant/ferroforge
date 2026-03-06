# Ferro Forge

**NexVigilant Station + Borrow Miner** — A Rust workspace powering pharmacovigilance agent infrastructure and educational gaming.

## NexVigilant Station

MCP (Model Context Protocol) server hub that routes AI agent traffic through pharmacovigilance tooling. Drop a config file → expose tools to any MCP-compatible agent.

### What It Does

```
Agent connects via stdio → Station loads configs/ → Agent discovers 70+ PV tools → Agent calls tools
```

**16 domain configs. 70 tools. One binary.**

| Domain | Tools | Coverage |
|--------|-------|----------|
| api.fda.gov | 2 | FAERS adverse event search, drug counts |
| accessdata.fda.gov | 6 | Approvals, Orange Book, REMS, recalls |
| www.fda.gov/safety | 4 | Safety communications, MedWatch, boxed warnings |
| dailymed.nlm.nih.gov | 3 | Drug labels, adverse reactions, search |
| clinicaltrials.gov | 5 | Trial search, safety endpoints, SAEs |
| www.ema.europa.eu | 6 | EPARs, PRAC signals, PSURs, RMPs |
| eudravigilance.ema.europa.eu | 4 | EU ICSRs, signal summaries, case counts |
| vigiaccess.org | 5 | WHO global reports, demographics, regions |
| who-umc.org | 4 | VigiBase, causality assessment, methodology |
| ich.org | 4 | ICH guidelines, E2x PV series, MedDRA |
| meddra.org | 4 | Term search, hierarchy, SOC, SMQs |
| pubmed.ncbi.nlm.nih.gov | 5 | Articles, case reports, signal literature |
| rxnav.nlm.nih.gov | 6 | RxNorm, drug interactions, NDCs, classes |
| go.drugbank.com | 5 | Pharmacology, interactions, targets, ADRs |
| open-vigil.fr | 4 | Disproportionality (PRR/ROR/IC), rankings |
| cioms.ch | 3 | Working groups, CIOMS form, publications |

### Quick Start

```bash
# Build
cargo build -p nexvigilant-station --release

# Run (reads configs from configs/ directory)
./target/release/nexvigilant-station --config-dir configs

# Test MCP protocol
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | ./target/release/nexvigilant-station --config-dir configs
```

### MCP Integration

Add to your MCP client config (e.g., `~/.claude.json`):

```json
{
  "mcpServers": {
    "nexvigilant-station": {
      "command": "/path/to/nexvigilant-station",
      "args": ["--config-dir", "/path/to/configs"]
    }
  }
}
```

### Adding Tools

Drop a JSON file in `configs/`:

```json
{
  "domain": "example.com",
  "title": "My Tools",
  "tools": [
    {
      "name": "get-data",
      "description": "Extract structured data",
      "parameters": [
        {"name": "query", "type": "string", "required": true}
      ],
      "stub_response": "{\"status\": \"ok\"}"
    }
  ]
}
```

Tools are instantly available to any connected agent. No rebuild needed.

### Architecture

```
configs/*.json  →  ConfigRegistry  →  MCP tools/list  →  Agent discovery
                                   →  MCP tools/call  →  Router  →  Handler
```

**Primitives:**
- `→ (Causality)` — Config → Registry → Tool → Response
- `∂ (Boundary)` — JSON-RPC 2.0 protocol boundary, domain isolation
- `σ (Structure)` — HubConfig schema: domain + tools + parameters
- `ς (State)` — ConfigRegistry holds mutable tool catalog
- `ν (Frequency)` — Each config adds N tools; total = Σ(config.tools.len())
- `∃ (Existence)` — Tool exists iff config file exists in configs/

### Validation

29 integration tests covering protocol, config loading, routing, and real config verification.

```bash
cargo test -p nexvigilant-station
```

---

## Borrow Miner

Educational arcade game teaching Rust ownership through gameplay. Built with Bevy.

```bash
# Requires: libasound2-dev libudev-dev pkg-config
cargo run -p borrow_miner
```

See `crates/borrow_miner/README.md` for full documentation.

---

## Workspace Structure

```
ferroforge/
├── Cargo.toml              # Workspace root
├── configs/                # Hub config files (16 domains, 70 tools)
│   ├── openfda.json
│   ├── dailymed.json
│   ├── clinicaltrials.json
│   ├── ema.json
│   ├── eudravigilance.json
│   ├── vigiaccess.json
│   ├── ich.json
│   ├── meddra.json
│   ├── pubmed.json
│   ├── rxnav.json
│   ├── drugbank.json
│   ├── openvigilfrance.json
│   ├── fda-accessdata.json
│   ├── fda-safety.json
│   ├── who-umc.json
│   └── cioms.json
└── crates/
    ├── station/            # NexVigilant Station MCP server
    │   ├── src/
    │   │   ├── lib.rs      # Public API
    │   │   ├── main.rs     # CLI entry point
    │   │   ├── config.rs   # HubConfig schema + ConfigRegistry
    │   │   ├── protocol.rs # JSON-RPC 2.0 + MCP types
    │   │   ├── router.rs   # Tool dispatch
    │   │   └── server.rs   # Stdio MCP server loop
    │   └── tests/
    │       └── integration.rs  # 29 tests
    └── borrow_miner/       # Educational Rust game
```

## License

MIT — NexVigilant LLC

*"Empowerment Through Vigilance"*
