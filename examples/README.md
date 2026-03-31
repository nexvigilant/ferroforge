# NexVigilant Station -- Framework Integration Examples

NexVigilant Station at [mcp.nexvigilant.com](https://mcp.nexvigilant.com) is a production MCP server providing 2,023 pharmacovigilance tools for AI agents. It covers FDA FAERS adverse event data, disproportionality signal detection (PRR/ROR/IC/EBGM), DailyMed drug labeling, PubMed literature search, clinical trials, EudraVigilance, WHO-UMC causality assessment, ICH regulatory guidelines, and more. No authentication required. CORS enabled for browser-based agents.

## Transports

| Transport | Endpoint | Spec |
|-----------|----------|------|
| Streamable HTTP | `POST https://mcp.nexvigilant.com/mcp` | MCP 2025-03-26 |
| SSE | `GET https://mcp.nexvigilant.com/sse` | Legacy MCP SSE |
| REST (JSON-RPC) | `POST https://mcp.nexvigilant.com/rpc` | JSON-RPC 2.0 |
| Tool Discovery | `GET https://mcp.nexvigilant.com/tools` | HTTP GET |
| Health | `GET https://mcp.nexvigilant.com/health` | HTTP GET |

Zero-cold-start alternative: replace `mcp.nexvigilant.com` with `station.nexvigilant.com` (always warm, same API).

## Examples

| Framework | File | Transport | Description |
|-----------|------|-----------|-------------|
| CrewAI | [crewai-nexvigilant.py](crewai-nexvigilant.py) | SSE | PV Signal Investigator agent investigating semaglutide + pancreatitis |
| LangChain | [langchain-nexvigilant.py](langchain-nexvigilant.py) | SSE | ReAct agent querying adverse reactions for metformin |

## Quick Start

1. Install dependencies for your framework:

```bash
# CrewAI
pip install crewai crewai-tools mcp

# LangChain
pip install langchain-mcp-adapters langchain-anthropic langgraph
```

2. Set your LLM API key:

```bash
export ANTHROPIC_API_KEY="your-key-here"
```

3. Run an example:

```bash
python crewai-nexvigilant.py
# or
python langchain-nexvigilant.py
```

No NexVigilant API key is needed. The Station is open for all agents.

## Tool Discovery

Browse all 2,023 tools: [mcp.nexvigilant.com/tools](https://mcp.nexvigilant.com/tools)

Start any investigation by calling `nexvigilant_chart_course` with one of six guided courses:

| Course | Steps | What It Does |
|--------|-------|-------------|
| `drug-safety-profile` | 6 | Name resolution, FAERS, ADRs, literature, EU signals, WHO |
| `signal-investigation` | 6 | FAERS, disproportionality, EU, case reports, trial SAEs, PRAC |
| `causality-assessment` | 4 | FAERS counts, disproportionality, WHO-UMC, case reports |
| `benefit-risk-assessment` | 4 | Trial safety, FAERS outcomes, label ADRs, EU RMP |
| `regulatory-intelligence` | 3 | ICH guidelines, EU EPAR, FDA approval history |
| `competitive-landscape` | 3 | Drug targets, head-to-head disproportionality, clinical pipeline |

## Direct REST Usage

No MCP client required for simple queries:

```bash
# List tools
curl https://mcp.nexvigilant.com/tools | python3 -c "import sys,json; print(len(json.load(sys.stdin)))"

# Call a tool via JSON-RPC
curl -X POST https://mcp.nexvigilant.com/rpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"nexvigilant_chart_course","arguments":{"course":"drug-safety-profile"}},"id":1}'
```

## License

NexVigilant Source Available License v1.0. Personal non-commercial use permitted. Organizational use requires written permission from matthew@nexvigilant.com.
