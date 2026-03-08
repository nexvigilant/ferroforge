# Ferro Forge

**NexVigilant Station + Borrow Miner** — A Rust workspace powering pharmacovigilance agent infrastructure and educational gaming.

## NexVigilant Station

MCP (Model Context Protocol) server that routes AI agent traffic through pharmacovigilance tooling. Drop a config file → expose tools to any MCP-compatible agent.

### What It Does

```
Agent connects → Station loads configs/ → Agent discovers 174 PV tools → Agent calls tools
```

**23 domain configs. 174 tools. One binary.** (17 public configs / 6 private)

| Domain | Tools | Coverage |
|--------|-------|----------|
| api.fda.gov | 7 | FAERS adverse event search, drug counts, outcomes |
| accessdata.fda.gov | 6 | Approvals, Orange Book, REMS, recalls, labeling changes |
| www.fda.gov | 7 | Safety communications, MedWatch, boxed warnings |
| dailymed.nlm.nih.gov | 6 | Drug labels, adverse reactions, interactions, search |
| clinicaltrials.gov | 7 | Trial search, safety endpoints, SAEs, study design |
| www.ema.europa.eu | 6 | EPARs, PRAC signals, PSURs, RMPs, referrals |
| eudravigilance.ema.europa.eu | 7 | EU ICSRs, signal summaries, case counts, demographics |
| vigiaccess.org | 7 | WHO global reports, demographics, regions, reporters |
| who-umc.org | 7 | VigiBase, causality assessment, signal methodology |
| ich.org | 7 | ICH guidelines, E2x PV series, MedDRA, quality |
| meddra.org | 7 | Term search, hierarchy, SOC, SMQs, multiaxiality |
| pubmed.ncbi.nlm.nih.gov | 7 | Articles, case reports, signal literature, citations |
| rxnav.nlm.nih.gov | 6 | RxNorm, drug interactions, NDCs, classes |
| go.drugbank.com | 7 | Pharmacology, interactions, targets, ADRs, classification |
| open-vigil.fr | 7 | Disproportionality (PRR/ROR/IC), compare drugs, rankings |
| cioms.ch | 7 | Working groups, CIOMS forms, publications, causality |
| calculate.nexvigilant.com | 17 | PRR, ROR, IC, EBGM, Naranjo, WHO-UMC, benefit-risk, NNH |

Plus 4 Rust meta-tools: `nexvigilant_chart_course`, `nexvigilant_capabilities`, `nexvigilant_directory`, `nexvigilant_station_health`.

### Research Courses

6 predefined multi-tool workflows via `nexvigilant_chart_course`:

| Course | Steps | Description |
|--------|-------|-------------|
| `drug-safety-profile` | 6 | RxNorm → FAERS → DailyMed → PubMed → EudraVigilance → VigiAccess |
| `signal-investigation` | 6 | FAERS → disproportionality → EU signals → case reports → trial SAEs → PRAC |
| `causality-assessment` | 4 | FAERS → disproportionality → WHO-UMC causality → case reports |
| `benefit-risk-assessment` | 4 | Trial endpoints → FAERS outcomes → label ADRs → EU RMP |
| `regulatory-intelligence` | 3 | ICH guidelines → EMA EPAR → FDA approval history |
| `competitive-landscape` | 3 | Drug targets → head-to-head comparison → clinical pipeline |

### Quick Start

```bash
# Build
cargo build -p nexvigilant-station --release

# Run (reads configs from configs/ directory)
./target/release/nexvigilant-station --config-dir configs

# Test MCP protocol
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | ./target/release/nexvigilant-station --config-dir configs
```

### Production — Cloud Run

Live at `mcp.nexvigilant.com`. Combined transport (Streamable HTTP + SSE + HTTP REST). CORS enabled. 129 public tools (125 from configs + 4 meta-tools).

```bash
# Deploy
./scripts/deploy-cloud-run.sh

# Health check
curl https://mcp.nexvigilant.com/health

# Tool count
curl https://mcp.nexvigilant.com/tools | python3 -c "import sys,json; print(len(json.load(sys.stdin)))"
```

**Claude.ai Connector:** `https://mcp.nexvigilant.com/mcp` — authless, MCP 2025-03-26 Streamable HTTP.

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

### Validation

44 integration tests covering protocol, config loading, routing, auth, and real config verification.

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
├── configs/                # Hub config files (23 domains, 174 tools)
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
│   ├── cioms.json
│   ├── calculation.json
│   ├── primitives.json       (private)
│   ├── linkedin.json         (private)
│   ├── wikipedia.json        (private)
│   ├── science-hexim1.json   (private)
│   ├── science-drug-targets.json (private)
│   └── science-genomics.json (private)
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
    │       └── integration.rs  # 44 tests
    └── borrow_miner/       # Educational Rust game
```

## License

MIT — NexVigilant LLC

*"Empowerment Through Vigilance"*
