# NexVigilant Station

Pharmacovigilance intelligence for AI agents. **347 tools** across **50 domains** for drug safety data, signal detection, causality assessment, and regulatory intelligence. Open, no auth required.

**Production:** [mcp.nexvigilant.com](https://mcp.nexvigilant.com)

## Connect

### Claude.ai / Claude Code

Add as a connector in Claude.ai Settings or `~/.claude.json`:

```
URL: https://mcp.nexvigilant.com/mcp
Auth: None
Protocol: MCP 2025-03-26 (Streamable HTTP)
```

### Any MCP Client

```json
{
  "mcpServers": {
    "nexvigilant-station": {
      "url": "https://mcp.nexvigilant.com/mcp"
    }
  }
}
```

### HTTP REST (No MCP Required)

```bash
# List all tools
curl https://mcp.nexvigilant.com/tools

# Call a tool directly
curl -X POST https://mcp.nexvigilant.com/rpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"api_fda_gov_search_adverse_events","arguments":{"drug":"metformin","limit":5}}}'

# Health check
curl https://mcp.nexvigilant.com/health
```

### Transports

| Transport | Endpoint | Spec |
|-----------|----------|------|
| Streamable HTTP | `POST /mcp` | MCP 2025-03-26 |
| SSE | `GET /sse` + `POST /message` | MCP legacy |
| HTTP REST | `GET /tools`, `POST /rpc` | Direct REST |
| Health | `GET /health` | Liveness + stats |

All transports on a single endpoint. CORS enabled for browser-based agents.

## Guided Research Courses

Don't know where to start? Call `nexvigilant_chart_course` with a course name. It returns the exact sequence of tools to call with parameters for any drug safety question.

| Course | Steps | What It Does |
|--------|-------|-------------|
| `drug-safety-profile` | 6 | RxNorm resolve, FAERS query, DailyMed labeling, PubMed literature, EudraVigilance, VigiAccess |
| `signal-investigation` | 6 | FAERS search, disproportionality (PRR/ROR), EU signals, case reports, trial SAEs, PRAC review |
| `causality-assessment` | 4 | FAERS counts, disproportionality, WHO-UMC causality, case reports |
| `benefit-risk-assessment` | 4 | Trial safety endpoints, FAERS outcomes, label ADRs, EU risk management |
| `regulatory-intelligence` | 3 | ICH guidelines, EMA EPAR, FDA approval history |
| `competitive-landscape` | 3 | Drug targets, head-to-head disproportionality, clinical pipeline |

**Example:** Investigate a safety signal for metformin:

```
1. Call nexvigilant_chart_course(course="signal-investigation", drug="metformin")
2. Follow the returned steps — each step names the exact tool and parameters
```

## Tool Catalog

### Safety Databases (8 domains, 56 tools)

| Domain | Tools | Data Source |
|--------|-------|------------|
| `api.fda.gov` | 8 | FDA FAERS adverse events, drug counts, outcomes, timelines |
| `eudravigilance.ema.europa.eu` | 7 | EU spontaneous reports, signal summaries, demographics |
| `vigiaccess.org` | 7 | WHO global safety reports (VigiBase) |
| `open-vigil.fr` | 7 | Disproportionality analysis, drug comparison, rankings |
| `who-umc.org` | 7 | Uppsala Monitoring Centre — causality, signal methodology |
| `accessdata.fda.gov` | 6 | FDA approvals, Orange Book, REMS, recalls |
| `www.fda.gov` | 7 | Safety communications, MedWatch alerts, boxed warnings |
| `www.ema.europa.eu` | 6 | EPARs, PRAC signals, PSURs, RMPs, referrals |

### Drug Information (3 domains, 19 tools)

| Domain | Tools | Data Source |
|--------|-------|------------|
| `dailymed.nlm.nih.gov` | 6 | Drug labels, adverse reactions, interactions |
| `rxnav.nlm.nih.gov` | 6 | RxNorm identifiers, drug interactions, NDCs, classes |
| `go.drugbank.com` | 7 | Pharmacology, targets, ADRs, classification |

### Literature & Trials (2 domains, 14 tools)

| Domain | Tools | Data Source |
|--------|-------|------------|
| `pubmed.ncbi.nlm.nih.gov` | 7 | Articles, case reports, signal literature, citations |
| `clinicaltrials.gov` | 7 | Trial search, safety endpoints, SAEs, study design |

### Regulatory Guidance (3 domains, 21 tools)

| Domain | Tools | Data Source |
|--------|-------|------------|
| `ich.org` | 7 | ICH guidelines (E2x PV series, quality, safety) |
| `meddra.org` | 7 | MedDRA terminology — hierarchy, SOC, SMQ, multiaxiality |
| `cioms.ch` | 7 | CIOMS working groups, forms, publications, causality categories |

### Signal Detection & Computation (4 domains, 38 tools)

| Domain | Tools | What It Computes |
|--------|-------|-----------------|
| `calculate.nexvigilant.com` | 17 | PRR, ROR, IC, EBGM, Naranjo, WHO-UMC, benefit-risk, NNH, seriousness, time-to-onset |
| `signal-theory.nexvigilant.com` | 8 | Signal detection framework — cascade, parallel, pipeline, conservation |
| `preemptive-pv.nexvigilant.com` | 10 | Three-tier signal detection — reactive, predictive, preemptive |
| `compliance.nexvigilant.com` | 3 | Regulatory compliance assessment against ICH catalog |

### Decision Trees (1 domain, 33 tools)

| Domain | Tools | What It Runs |
|--------|-------|-------------|
| `microgram.nexvigilant.com` | 33 | Self-testing decision programs: case assessment, signal-to-action, Bradford Hill, Naranjo quick, seriousness-to-deadline, and 28 more |

### Chemical Safety (1 domain, 13 tools)

| Domain | Tools | What It Does |
|--------|-------|-------------|
| `chemivigilance.nexvigilant.com` | 13 | SMILES parsing, structural alerts, toxicity prediction, metabolite prediction, molecular descriptors |

### Epidemiology & Benefit-Risk (2 domains, 17 tools)

| Domain | Tools | What It Computes |
|--------|-------|-----------------|
| `epidemiology.nexvigilant.com` | 11 | Relative risk, odds ratio, NNT/NNH, Kaplan-Meier, attributable fraction, SMR |
| `benefit-risk.nexvigilant.com` | 6 | Quantitative Benefit-Risk Index (QBRI), therapeutic window |

### Reference & Knowledge (4 domains, 25 tools)

| Domain | Tools | Coverage |
|--------|-------|---------|
| `crystalbook.nexvigilant.com` | 7 | Eight Laws of System Homeostasis |
| `harm-taxonomy.nexvigilant.com` | 6 | 8-type harm classification from conservation law violations |
| `en.wikipedia.org` | 6 | Article search, sections, summaries, references |
| `vigilance.nexvigilant.com` | 5 | Harm classification and risk scoring |

### STEM Computing (22 domains, 101 tools)

Computational tools spanning mathematics, biology, and information theory:

| Domain | Tools | What It Does |
|--------|-------|-------------|
| `combinatorics.nexvigilant.com` | 12 | Binomial, Catalan, derangement, Josephus, grid paths |
| `stoichiometry.nexvigilant.com` | 8 | Primitive equation encoding/decoding, isomer detection |
| `dna.nexvigilant.com` | 6 | Codon translation, sequence alignment, evolution simulation |
| `energy.nexvigilant.com` | 6 | Token budget management via ATP/ADP biochemistry |
| `formula.nexvigilant.com` | 5 | Signal strength, flywheel velocity, spectral overlap |
| `zeta.nexvigilant.com` | 5 | Riemann zeta function, zero analysis, GUE comparison |
| `helix.nexvigilant.com` | 5 | Conservation law as computable geometry |
| `dtree.nexvigilant.com` | 5 | Decision tree training, prediction, pruning |
| `cccp.nexvigilant.com` | 5 | PV competency framework evaluation |
| `molecular-weight.nexvigilant.com` | 4 | Concept mass, periodic table, transfer prediction |
| `pvdsl.nexvigilant.com` | 4 | Domain-specific language compilation and evaluation |
| `relay.nexvigilant.com` | 4 | Pipeline fidelity analysis |
| `heligram.nexvigilant.com` | 4 | Helical decision programs |
| `edit-distance.nexvigilant.com` | 4 | String similarity (Levenshtein, traceback) |
| `dataframe.nexvigilant.com` | 7 | Columnar data operations (filter, group, join, sort) |
| `tov.nexvigilant.com` | 3 | Signal strength and system stability |
| `game-theory.nexvigilant.com` | 3 | Nash equilibria, payoff matrices |
| `bicone.nexvigilant.com` | 3 | Shape analysis for convergent-divergent systems |
| `markov.nexvigilant.com` | 2 | Markov chain analysis |
| `algovigilance.nexvigilant.com` | 6 | AI/ML safety monitoring, triage, deduplication |
| `entropy.nexvigilant.com` | 1 | Shannon entropy |
| `marketing.nexvigilant.com` | 6 | Capability discovery and onboarding workflows |

### Meta Tools (5 tools)

| Tool | What It Does |
|------|-------------|
| `nexvigilant_chart_course` | Returns step-by-step workflows for any drug safety question |
| `nexvigilant_capabilities` | Lists all available tool domains and capabilities |
| `nexvigilant_directory` | Domain directory with tool counts and descriptions |
| `nexvigilant_station_health` | Server health, uptime, error rates, latency |
| `nexvigilant_ring_health` | Ring topology health across all domains |

## Tool Naming Convention

All tools follow the pattern `{domain_underscored}_{tool_name}`:

```
api_fda_gov_search_adverse_events
calculate_nexvigilant_com_compute_prr
pubmed_ncbi_nlm_nih_gov_search_articles
```

## Self-Hosting

Build from source and run locally:

```bash
# Build
cargo build -p nexvigilant-station --release

# Run (reads configs from configs/ directory)
./target/release/nexvigilant-station --config-dir configs

# Test MCP protocol
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | \
  ./target/release/nexvigilant-station --config-dir configs
```

Add to your local MCP client:

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

## Architecture

```
configs/*.json  →  ConfigRegistry  →  MCP tools/list  →  Agent discovery
                                   →  MCP tools/call  →  Router  →  Handler
```

- **58 JSON config files** define tool schemas, parameters, and routing
- **22 proxy scripts** handle live API calls (Python, routed via `dispatch.py`)
- **17 Rust-native handlers** run computation in-process (sub-millisecond)
- **5 meta-tools** provide discovery, health, and guided workflows

136 tests (75 integration + 47 unit + 14 lib).

## MCP Spec Compliance

- Protocol: MCP 2025-03-26
- All tools have `outputSchema` defined
- All tools annotated: `readOnlyHint: true`, `destructiveHint: false`
- Session tracking: optional (stateless by default)

---

## Borrow Miner

This workspace also includes an educational Rust ownership game built with Bevy. See `crates/borrow_miner/README.md`.

## License

MIT — NexVigilant LLC

*Empowerment Through Vigilance* — [nexvigilant.com](https://nexvigilant.com)
