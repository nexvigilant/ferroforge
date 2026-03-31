# NexVigilant Station — Installation Guide

## Quick Connect (Any MCP Client)

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "nexvigilant-station": {
      "url": "https://mcp.nexvigilant.com/mcp"
    }
  }
}
```

No API key required. No installation needed. The server runs on Google Cloud Run.

## Getting Started

After connecting, call `nexvigilant_chart_course` to see 6 guided research workflows:

- **drug-safety-profile** — Full safety profile from drug name to WHO global data
- **signal-investigation** — Investigate a safety signal with FAERS + disproportionality
- **causality-assessment** — Assess drug-event causality with WHO-UMC framework
- **benefit-risk-assessment** — Quantify benefit-risk from trials + post-market data
- **regulatory-intelligence** — Trace ICH + EMA + FDA regulatory lifecycle
- **competitive-landscape** — Map competitive safety terrain

## Transports

| Transport | Endpoint | Use Case |
|-----------|----------|----------|
| Streamable HTTP | `POST /mcp` | Claude.ai, modern MCP clients |
| SSE | `GET /sse` + `POST /message` | Claude Code, mcp-remote |
| HTTP REST | `GET /tools`, `POST /rpc` | Any HTTP client |

## What You Get

1,957 pharmacovigilance tools across 229 domains. Live FDA FAERS data, EudraVigilance signals, DailyMed labeling, PubMed literature, clinical trial safety data, and Rust-native computation (PRR, ROR, IC, EBGM, Naranjo causality, WHO-UMC assessment).
