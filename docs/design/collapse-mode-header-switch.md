# Collapse-Mode Header Switch — Design Sketch

Status: **proposed, not implemented**. Requires sign-off before coding.
Authored: 2026-04-16, token-conservation session.

## Problem

Today, `--collapse-tools` is a startup-time CLI flag on `nexvigilant-station`.
It affects the whole process:

- **ON** → `tools/list` returns the single `station` meta-tool (~56k tokens
  reclaimed per Claude Code session).
- **OFF** (default) → `tools/list` returns all 3,089 public tools.

The production Cloud Run deployment at `mcp.nexvigilant.com` runs with
`--collapse-tools` OFF. Flipping it to ON gains token savings for Claude Code
users connecting through the SSE/HTTP bridge — but **simultaneously collapses
the claude.ai custom connector view**, which is a public product surface. Third
parties who added `mcp.nexvigilant.com/mcp` as a connector would suddenly see
one tool instead of 3,089. Product regression.

## Options

| Option | Surface change | Ops change | Verdict |
|--------|---------------|------------|---------|
| **A. Two Cloud Run services** (one collapsed, one full) | None — different URLs | +1 service, +1 DNS, +1 cert, +1 deploy pipeline | Heavy. Worse cache locality. |
| **B. Per-request header switch** on ONE service | None — same URLs, client chooses | Zero — still one binary, one deploy | **Recommended.** |
| **C. API-key-gated collapse** | Key holders get collapsed, anonymous gets full | Requires auth on a currently authless endpoint | Couples collapse to auth, overloaded semantics. |
| **D. URL path variant** (`/mcp-collapsed`) | Clients pick endpoint | Trivial | Acceptable, but header is more MCP-idiomatic. |

Option **B** (header switch) wins on every axis except implementation surface
area (~100 lines of refactor across 4 transport files vs option D's ~20 lines
of routing config). Option D is the "safe punt" fallback.

## Proposed header

```
X-NexVigilant-Collapse: 1
```

Any truthy value (`1`, `true`, `yes`) → collapsed.
Missing, empty, or falsy → full (preserves default/product behavior).

Tested on every HTTP-based transport:
- **HTTP REST** (`POST /rpc`) — header on request
- **SSE** (`GET /sse` opens channel, `POST /message` sends) — header on POST
- **Streamable HTTP** (`POST /mcp`) — header on request

Stdio transport has no headers — keeps using the CLI flag (`--collapse-tools`).

## Code changes required

### 1. `ConfigRegistry` — rename field (semantic clarification)

```rust
pub struct ConfigRegistry {
    // ...
    pub collapse_tools_default: bool,   // was: collapse_tools
}
```

The field becomes the fallback when no header is present.

### 2. `server.rs` — thread `collapse_override: Option<bool>` through handlers

```rust
pub fn handle_request_core(
    registry: &ConfigRegistry,
    // ... existing params ...
    collapse_override: Option<bool>,  // NEW
) -> Option<JsonRpcResponse> {
    let collapsed = collapse_override.unwrap_or(registry.collapse_tools_default);
    // use `collapsed` instead of `registry.collapse_tools` at both branch points
    // (tools/list + tools/call)
}
```

All existing call sites pass `None` to preserve default behavior.

### 3. HTTP transports — parse the header, pass to core

```rust
// server_http.rs, server_sse.rs, server_combined.rs, server_streamable.rs
fn is_collapse_requested(headers: &HeaderMap) -> Option<bool> {
    headers
        .get("x-nexvigilant-collapse")
        .and_then(|v| v.to_str().ok())
        .map(|s| matches!(s.trim(), "1" | "true" | "yes" | "on"))
}
```

Pass the result into `handle_request_core` as `collapse_override`.

### 4. Stdio transport — unchanged

Stdio has no headers. Keeps using `registry.collapse_tools_default` directly.
This is fine because stdio is local-only and the developer controls the flag.

## Testing plan

1. Unit: `is_collapse_requested` handles the three transport header maps
   (axum `HeaderMap`, the hand-rolled SSE parser, etc.).
2. Integration: start the binary (default flag OFF), curl `/rpc` with and
   without the header, assert `tools/list` count differs (3,089 vs 1).
3. Regression: existing stdio smoke tests keep working because `collapse_override`
   defaults to `None`.

## Rollout plan

1. Deploy new binary to Cloud Run. Default behavior **unchanged** (3,089 tools
   visible to anonymous callers, preserves product).
2. Update Claude Code MCP config in `~/.claude.json` to include the header on
   the SSE/Streamable connection to `mcp.nexvigilant.com`:
   ```json
   "nexvigilant-station-remote": {
     "url": "https://mcp.nexvigilant.com/mcp",
     "headers": {"X-NexVigilant-Collapse": "1"}
   }
   ```
3. Measure first-run token count. Should drop by ~56k per the Step D
   measurement.
4. If a regression surfaces, remove the header from `~/.claude.json` — instantly
   reverts to full mode on next session. Zero redeploy needed.

## Blast radius (for you to evaluate before approving)

- **Binary size:** +0. Adding `Option<bool>` parameters doesn't change
  generated code meaningfully.
- **Latency:** +0 on anonymous requests. Header parsing is microseconds.
- **Third-party clients:** +0 impact. Missing header → full mode (today's
  behavior).
- **Deploy risk:** low. The header path is additive. Worst case if it
  breaks: roll back to previous image (standard Cloud Run revert).
- **Review surface:** ~100 lines across 4 transport files. Mechanical,
  pattern-matchable refactor.

## What this does NOT solve

- **Stdio sessions** still need `--collapse-tools` in the binary invocation.
  Acceptable because stdio is dev-only.
- **Anonymous callers can't opt into collapse** without knowing to send the
  header. Fine — they shouldn't care; they get the product surface by default.
- **Authenticated bulk-tooling agents** get no special treatment. If we later
  want "all authenticated callers get collapse," that's an orthogonal auth
  layer — not this change.

## Decision required from Matthew

1. **Yes to header-switch approach (Option B)** → I implement the ~100-line
   refactor, add tests, verify, hand back for deploy.
2. **Yes to URL-path variant (Option D)** instead → smaller surface, more
   fragmented semantics (two paths that do nearly the same thing).
3. **Defer** → keep the `--collapse-tools` flag local-only for now; no
   Cloud Run change.

Your call. Until you say which, the 55.7k/session reclaim stays code-only.
