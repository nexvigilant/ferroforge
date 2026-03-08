# NexVigilant Station — Agent Discovery Manifest

This file is structured metadata that AI agents parse to understand what NexVigilant Station offers and how to use it.

## Identity

| Field | Value |
|-------|-------|
| Name | NexVigilant Station |
| Type | MCP Server (stdio transport) |
| Protocol | JSON-RPC 2.0 / MCP 2024-11-05 (source: `crates/station/src/server.rs:70`) |
| Binary | `nexvigilant-station` |
| Domain | Pharmacovigilance (PV) |
| Owner | NexVigilant LLC (MatthewCampCorp) |

## Capability Primitive Decomposition

Every capability in this station decomposes to these T1 primitives (source: `~/.claude/projects/-home-matthew/memory/primitives.md`):

```
→ (Causality)    Drug → Adverse Event → Signal → Action
∂ (Boundary)     Regulatory jurisdiction boundaries (FDA/EMA/WHO)
σ (Structure)    MedDRA hierarchy (SOC→HLGT→HLT→PT→LLT)
ς (State)        Case lifecycle (reported→assessed→confirmed→actioned)
ν (Frequency)    Disproportionality (PRR, ROR, IC, EBGM)
κ (Comparison)   Drug-vs-comparator, signal-vs-noise
N (Quantity)     Case counts, event frequencies, confidence intervals
∃ (Existence)    Signal exists iff ν(drug,event) > threshold
```

## Domain Coverage Map

23 configs, 174 tools (17 public / 6 private). 129 public tools served (125 from configs + 4 Rust meta-tools). Verified by `cargo test -p nexvigilant-station` (53 tests, source: `crates/station/tests/integration.rs`).

```
                    ┌─────────────────────────┐
                    │   PHARMACOVIGILANCE      │
                    │   INTELLIGENCE GRAPH     │
                    └─────────┬───────────────┘
                              │
    ┌──────────────┬──────────┼──────────┬──────────────┐
    │              │          │          │              │
┌───▼───┐    ┌────▼────┐ ┌───▼───┐ ┌────▼────┐   ┌────▼────┐
│SAFETY │    │ DRUG    │ │COMPUTE│ │REGULATORY│   │RESEARCH │
│ DATA  │    │ INFO    │ │ENGINE │ │ GUIDANCE │   │ COURSES │
└───┬───┘    └────┬────┘ └───┬───┘ └────┬─────┘   └────┬────┘
    │             │          │          │              │
┌───┼───┐   ┌────┼────┐    PRR    ┌────┼────┐     6 courses
│   │   │   │    │    │    ROR    │    │    │     (chart_course)
FDA EMA WHO DailyMed   IC/EBGM  ICH  CIOMS
FAERS    VigiA RxNav   Naranjo  E2x  Forms
Safety   OpenV DrugBank WHO-UMC WGs   MedDRA
  EudV        PubMed   B/R     SMQs
```

## Agent Workflow Patterns

### Pattern 1: Drug Safety Profile
```
1. rxnav/get-rxcui → resolve drug name to RxCUI
2. openfda/search-adverse-events → get FAERS signal counts
3. dailymed/get-adverse-reactions → get labeled ADRs
4. pubmed/search-signal-literature → find published signals
5. eudravigilance/get-signal-summary → get EU disproportionality
6. vigiaccess/get-adverse-reactions → get WHO global view
```

### Pattern 2: Signal Investigation
```
1. openfda/search-adverse-events → initial FAERS signal
2. openvigilfrance/compute-disproportionality → PRR/ROR/IC
3. eudravigilance/get-signal-summary → EU ROR confirmation
4. pubmed/search-case-reports → published case evidence
5. clinicaltrials/get-serious-adverse-events → trial SAE data
6. ema/get-safety-signals → PRAC assessment status
```

### Pattern 3: Regulatory Landscape
```
1. ich/get-pv-guidelines → applicable ICH guidelines
2. fda-accessdata/search-approvals → US approval status
3. ema/search-medicines → EU authorisation status
4. fda-safety/get-boxed-warning → US boxed warnings
5. ema/get-rmp-summary → EU risk management plan
6. fda-accessdata/get-rems → US REMS requirements
```

### Pattern 4: Causality Assessment
```
1. openfda/search-adverse-events → FAERS case counts
2. openvigilfrance/compute-disproportionality → PRR/ROR/IC
3. who-umc/get-causality-assessment → WHO-UMC framework
4. pubmed/search-case-reports → published case evidence
```

### Pattern 5: Benefit-Risk Assessment
```
1. clinicaltrials/get-safety-endpoints → trial safety data
2. openfda/get-event-outcomes → FAERS outcome distribution
3. dailymed/get-adverse-reactions → labeled ADRs
4. ema/get-rmp-summary → EU risk management plan
```

### Pattern 6: Regulatory Intelligence
```
1. ich/get-pv-guidelines → applicable ICH guidelines
2. ema/get-epar → EU assessment report
3. fda-accessdata/get-approval-history → FDA approval history
```

### Pattern 7: Competitive Landscape
```
1. drugbank/get-targets → drug target profile
2. openvigilfrance/compare-drugs → head-to-head disproportionality
3. clinicaltrials/search-trials → active clinical pipeline
```

### Pattern 8: Drug Comparison
```
For each drug in comparison set:
  1. rxnav/get-drug-classes → therapeutic class
  2. openfda/get-drug-counts → AE profile
  3. drugbank/get-adverse-effects → known ADRs with frequency
  4. openvigilfrance/get-top-reactions → ranked by disproportionality
Compare across drugs using κ(Comparison) primitive.
```

## Tool Naming Convention

Tools follow: `{domain_underscored}_{tool_name_underscored}` (source: `crates/station/src/config.rs:129`)

```
api_fda_gov_search_adverse_events
dailymed_nlm_nih_gov_get_drug_label
www_ema_europa_eu_get_safety_signals
```

## Config Schema

Each JSON file in `configs/` follows (source: `crates/station/src/config.rs:9-58`):

```typescript
interface HubConfig {
  domain: string;           // e.g., "api.fda.gov"
  url_pattern?: string;     // e.g., "/drug/event*"
  title: string;            // Human-readable
  description?: string;
  tools: ToolDef[];
}

interface ToolDef {
  name: string;             // e.g., "search-adverse-events"
  description: string;
  parameters?: ParamDef[];
  stub_response?: string;   // JSON string for development
}

interface ParamDef {
  name: string;
  type: string;             // "string" | "integer" | "boolean"
  description?: string;
  required: boolean;
}
```

## Extending

To add a new domain:

1. Create `configs/{domain}.json` with the schema above
2. Restart the station (or it auto-discovers on next `tools/list`)
3. Tools are immediately available to connected agents

No code changes needed. Configs are the product.
