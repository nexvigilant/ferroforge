# NexVigilant Station — Scripts

This directory contains the Python proxy layer for NexVigilant Station.
The dispatcher routes MCP tool calls to domain-specific proxy scripts that
talk to upstream APIs.

## Architecture

```
MCP Client
    │
    │  JSON envelope (stdin)
    │  {"tool": "api_fda_gov_search_adverse_events", "arguments": {...}}
    ▼
dispatch.py   ← single entry point
    │
    │  strips domain prefix, resolves proxy
    ▼
openfda_proxy.py          api.fda.gov
clinicaltrials_proxy.py   clinicaltrials.gov
dailymed_proxy.py         dailymed.nlm.nih.gov
rxnav_proxy.py            rxnav.nlm.nih.gov
pubmed_proxy.py           pubmed.ncbi.nlm.nih.gov
    │
    │  JSON response (stdout)
    ▼
MCP Client
```

## Tool Name Convention

Tool names follow the pattern defined in (source: `../STATION.md`, "Tool Naming Convention" section):

```
{domain_with_dots_replaced_by_underscores}_{tool_name_with_hyphens_replaced_by_underscores}
```

Examples derived from `../configs/openfda.json` and `../configs/pubmed.json`:

| Full tool name | Domain prefix | Unprefixed name |
|----------------|---------------|-----------------|
| `api_fda_gov_search_adverse_events` | `api_fda_gov_` | `search_adverse_events` |
| `dailymed_nlm_nih_gov_get_drug_label` | `dailymed_nlm_nih_gov_` | `get_drug_label` |
| `pubmed_ncbi_nlm_nih_gov_search_articles` | `pubmed_ncbi_nlm_nih_gov_` | `search_articles` |

## dispatch.py

### Input (stdin)

```json
{"tool": "api_fda_gov_search_adverse_events", "arguments": {"drug_name": "aspirin"}}
```

### Output (stdout)

Whatever the proxy script writes to stdout — a single JSON object.

### Fallback behavior

| Situation | Dispatcher behavior |
|-----------|---------------------|
| Domain prefix matches, proxy file exists | Calls proxy, forwards its output |
| Domain prefix matches, proxy file missing | Returns `{"status": "stub", ...}` |
| No domain prefix matches | Returns `{"status": "stub", ...}` with list of registered domains |
| Proxy exits non-zero | Returns `{"status": "error", "stderr": "..."}` |
| Proxy returns invalid JSON | Returns `{"status": "error", "raw_output": "..."}` |
| stdin is empty or malformed | Returns `{"status": "error", "error": "..."}` |

### Smoke test

```bash
python3 dispatch.py --test
```

Runs all test cases defined in `SMOKE_TEST_CASES` inside `dispatch.py` without
hitting real APIs. Verifies routing logic and stub/error fallback paths.
Exits 0 when all cases pass, 1 when any case fails.

## Proxy Script Contract

Each proxy script must satisfy this contract:

1. Reads a JSON envelope from stdin: `{"tool": "<unprefixed_name>", "arguments": {...}}`
2. Performs the upstream API call (or returns a stub if the API is unreachable)
3. Writes a single JSON object to stdout
4. Exits 0 on success (including graceful stub responses), non-zero on hard failure

The dispatcher applies a 30-second timeout per proxy invocation (source: `dispatch.py`, `call_proxy()`, `timeout=30`).

### Minimal proxy template

```python
#!/usr/bin/env python3
"""
<Domain> proxy for NexVigilant Station.
Receives: {"tool": "<unprefixed_name>", "arguments": {...}}
Returns:  JSON object on stdout
"""
import json
import sys

def handle(tool: str, arguments: dict) -> dict:
    if tool == "my_tool_name":
        # ... call upstream API ...
        return {"status": "ok", "data": [...]}
    return {"status": "error", "error": f"Unknown tool: {tool}"}

if __name__ == "__main__":
    envelope = json.loads(sys.stdin.read())
    result = handle(envelope["tool"], envelope.get("arguments", {}))
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
```

## Adding a New Proxy

### Step 1 — Register the domain prefix in dispatch.py

Open `dispatch.py` and add one entry to `DOMAIN_ROUTES`:

```python
DOMAIN_ROUTES: dict[str, str] = {
    ...
    "vigiaccess_org_":  "vigiaccess_proxy.py",   # new entry
}
```

The key is the domain with `.` replaced by `_`, followed by a trailing `_`
(source: `../STATION.md`, "Tool Naming Convention" section).

### Step 2 — Create the proxy script

Create `scripts/vigiaccess_proxy.py` using the template above.
Implement handlers for each tool name defined in the corresponding
`../configs/` JSON file.

### Step 3 — Add a smoke test case

Add an entry to `SMOKE_TEST_CASES` in `dispatch.py`:

```python
{
    "label": "VigiAccess — registered proxy",
    "envelope": {"tool": "vigiaccess_org_search_reports", "arguments": {"drug_name": "warfarin"}},
    "expect_domain": "vigiaccess_org_",
},
```

### Step 4 — Verify

```bash
python3 dispatch.py --test
echo '{"tool": "vigiaccess_org_search_reports", "arguments": {"drug_name": "warfarin"}}' | python3 dispatch.py
```

## Current Domain Map

Proxy targets derived from `../configs/*.json` domain fields:

| Domain prefix | Proxy script | Config source |
|---------------|--------------|---------------|
| `api_fda_gov_` | `openfda_proxy.py` | `../configs/openfda.json` |
| `clinicaltrials_gov_` | `clinicaltrials_proxy.py` | `../configs/clinicaltrials.json` |
| `dailymed_nlm_nih_gov_` | `dailymed_proxy.py` | `../configs/dailymed.json` |
| `rxnav_nlm_nih_gov_` | `rxnav_proxy.py` | `../configs/rxnav.json` |
| `pubmed_ncbi_nlm_nih_gov_` | `pubmed_proxy.py` | `../configs/pubmed.json` |

All other domain prefixes return `{"status": "stub"}` until a proxy is registered.
