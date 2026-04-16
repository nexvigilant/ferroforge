//! Meta-tool wiring — collapses ~3,000 per-domain tools behind ONE MCP tool.
//!
//! When `ConfigRegistry::collapse_tools` is `true`, `tools/list` advertises
//! only the synthetic `station` tool defined here, and `tools/call` with
//! `name == "station"` is routed through this module instead of the per-domain
//! proxy dispatcher. This reduces prompt-advertising cost from ~80–100k tokens
//! to a few hundred.
//!
//! Discovery is served from an in-memory `station_meta::ConfigIndex` built
//! lazily on first use. Execution forwards to the existing `router::route_tool_call`
//! via a tiny `LocalRouterClient` adapter — zero new transport cost.

use serde_json::{Value, json};
use std::sync::OnceLock;

use crate::auth::ApiKeyGate;
use crate::config::ConfigRegistry;
use crate::metering::StationMeter;
use crate::protocol::{ContentBlock, ToolAnnotations, ToolCallResult, ToolInfo};
use crate::router;
use crate::telemetry::StationTelemetry;

use station_meta::{
    ConfigIndex, ExecutionRequest, ExecutionResult, MetaRequest, MetaResponse, StationClient,
    build_mcp_tool_name, dispatch,
};

/// Lazy-built index of `(config, tool)` rows for discovery.
///
/// Built from `ConfigRegistry.configs_dir` the first time the meta-tool is
/// called. Subsequent calls reuse the index — no per-call I/O cost.
static DISCOVERY_INDEX: OnceLock<ConfigIndex> = OnceLock::new();

fn discovery_index(registry: &ConfigRegistry) -> &'static ConfigIndex {
    DISCOVERY_INDEX.get_or_init(|| match ConfigIndex::load(&registry.configs_dir) {
        Ok(idx) => {
            tracing::info!(rows = idx.len(), "meta_wire: discovery index built");
            idx
        }
        Err(err) => {
            tracing::warn!(error = %err, "meta_wire: failed to build discovery index; using empty");
            ConfigIndex::default()
        }
    })
}

/// Build the single synthetic tool descriptor exposed when collapse is on.
///
/// The schema is deliberately compact — the model needs enough info to know
/// WHEN to call `discover` vs `execute`, not the full per-tool schema.
#[must_use]
pub fn station_tool_info() -> ToolInfo {
    ToolInfo {
        name: "station".into(),
        description: "NexVigilant Station meta-tool. One tool replaces ~3,000. \
            Mode=discover returns ranked tool candidates for a natural-language intent \
            (e.g. 'search FAERS adverse events'). Mode=execute runs a specific tool by \
            config+tool+params (use fields returned by discover). Mode=explain returns the \
            token-budget taxonomy (regime bands, waste classes, strategy tiers) so you can \
            self-assess your session; pass `pool: {t_atp, t_adp, t_amp}` for current-state computation. \
            Start with discover if you don't already know the exact tool."
            .into(),
        input_schema: json!({
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["discover", "execute", "explain"],
                    "description": "discover = search tools by intent; execute = call a specific tool; explain = return token-budget taxonomy"
                },
                "intent": {
                    "type": "string",
                    "description": "(discover) Natural-language description of what you need"
                },
                "limit": {
                    "type": "integer",
                    "description": "(discover) Max candidates to return (default 5)",
                    "minimum": 1,
                    "maximum": 50
                },
                "config": {
                    "type": "string",
                    "description": "(execute) Config stem from a discover result"
                },
                "tool": {
                    "type": "string",
                    "description": "(execute) Tool name from a discover result"
                },
                "params": {
                    "type": "object",
                    "description": "(execute) Parameters object passed to the tool"
                },
                "pool": {
                    "type": "object",
                    "description": "(explain, optional) Token-pool snapshot — {t_atp, t_adp, t_amp} as u64. If provided, explain computes your current regime.",
                    "properties": {
                        "t_atp": {"type": "integer", "minimum": 0, "description": "Tokens remaining"},
                        "t_adp": {"type": "integer", "minimum": 0, "description": "Tokens spent productively"},
                        "t_amp": {"type": "integer", "minimum": 0, "description": "Tokens wasted"}
                    }
                },
                "ranker": {
                    "type": "string",
                    "enum": ["jaccard", "idf"],
                    "description": "(discover, optional) Ranking algorithm. `jaccard` (default) = Jaccard + exact-name boost. `idf` = IDF-weighted presence — rare terms like `faers` outweigh common terms like `search`. Try `idf` when your intent has distinctive vocabulary and Jaccard's top result isn't the one you expected."
                }
            },
            "required": ["mode"]
        }),
        output_schema: Some(json!({
            "type": "object",
            "properties": {
                "mode": {"type": "string"},
                "candidates": {
                    "type": "array",
                    "description": "Populated on mode=discover",
                    "items": {
                        "type": "object",
                        "properties": {
                            "config": {"type": "string"},
                            "tool": {"type": "string"},
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "score": {"type": "number"}
                        }
                    }
                },
                "execution": {
                    "type": "object",
                    "description": "Populated on mode=execute",
                    "properties": {
                        "status": {"type": "string"},
                        "result": {},
                        "error": {"type": "string"}
                    }
                },
                "explanation": {
                    "type": "object",
                    "description": "Populated on mode=explain — contains regime bands, waste classes, strategy tiers, and optional current state",
                    "properties": {
                        "summary": {"type": "string"},
                        "regimes": {"type": "array"},
                        "waste_classes": {"type": "array"},
                        "strategy_tiers": {"type": "array"},
                        "current": {"type": "object"}
                    }
                },
                "error": {"type": "string"}
            }
        })),
        // Annotations deliberately omitted.
        //
        // The meta-tool dispatches to ~3,000 heterogeneous downstream tools.
        // An audit on 2026-04-16 (73 of 3,082 public tools) found mutating
        // operations behind the router: `claude-fs-delete`, `claude-fs-write`,
        // `gsheets-write-range`, `fda-create-plan`, `edu-*-create`, etc.
        //
        // Claiming `readOnlyHint: true` would be a protocol-level lie —
        // claude.ai's auto-approval heuristic would skip confirmation on calls
        // that mutate user state. Claiming `destructiveHint: false` is equally
        // wrong (delete is irreversible).
        //
        // Omitting both hints is MCP-spec's "unspecified" state. That's the
        // honest signal: "this is a router, check the specific tool behavior
        // before auto-approving." Downstream per-tool annotations (preserved
        // on the non-collapsed surface) carry the real hints.
        annotations: None,
    }
}

/// Adapter: makes Station's `router::route_tool_call` look like a `StationClient`.
///
/// Reconstructs the per-domain tool name from `(config, tool)` so the router
/// can resolve it. Naming convention matches what configs produce:
/// `{domain_underscored}_{tool_underscored}`, so we rebuild from the config's
/// domain rather than the filename stem.
struct LocalRouterClient<'a> {
    registry: &'a ConfigRegistry,
    telemetry: &'a StationTelemetry,
    meter: Option<&'a StationMeter>,
    auth_gate: &'a ApiKeyGate,
    auth_header: Option<&'a str>,
    proxy_cache: Option<&'a router::ProxyCache>,
}

impl StationClient for LocalRouterClient<'_> {
    fn call(&self, req: &ExecutionRequest) -> anyhow::Result<ExecutionResult> {
        // Resolve the config by stem → domain, then rebuild the MCP tool name.
        let Some(cfg) = self
            .registry
            .configs
            .iter()
            .find(|c| config_stem_matches(c, &req.config))
        else {
            return Ok(ExecutionResult::error(format!(
                "unknown config `{}`",
                req.config
            )));
        };

        // Shared helper — same logic HttpStationClient uses. Single source of truth.
        let mcp_tool_name = build_mcp_tool_name(&cfg.domain, &req.tool);

        let result = router::route_tool_call(
            self.registry,
            self.telemetry,
            self.meter,
            self.auth_gate,
            self.auth_header,
            &mcp_tool_name,
            &req.params,
            self.proxy_cache,
        );

        // Flatten ToolCallResult back into the meta-tool's ExecutionResult shape.
        let payload: Value = result
            .content
            .iter()
            .map(|c| match c {
                ContentBlock::Text { text } => serde_json::from_str::<Value>(text)
                    .unwrap_or_else(|_| Value::String(text.clone())),
            })
            .next()
            .unwrap_or(Value::Null);

        if result.is_error.unwrap_or(false) {
            Ok(ExecutionResult::error(
                payload
                    .get("error")
                    .and_then(|v| v.as_str())
                    .map(str::to_string)
                    .unwrap_or_else(|| payload.to_string()),
            ))
        } else {
            Ok(ExecutionResult::ok(payload))
        }
    }
}

/// Match a config by the identifier the caller passed.
///
/// Accepts (in order of preference):
/// 1. Exact domain (e.g. `api.fda.gov`) — this is what `discover` emits now.
/// 2. Underscored domain (e.g. `api_fda_gov`) — MCP-style.
/// 3. Dash-preserved domain (e.g. `api-fda-gov`) — URL-safe variant.
///
/// The filename stem (e.g. `openfda`) is NOT matched here because it's not
/// carried on `HubConfig` — the station crate doesn't store it. Discover
/// emits the domain as `config` to ensure this round-trip works.
fn config_stem_matches(cfg: &crate::config::HubConfig, want: &str) -> bool {
    if cfg.domain == want {
        return true;
    }
    let domain_us = cfg.domain.replace('.', "_").replace('-', "_");
    if domain_us == want {
        return true;
    }
    let domain_dash = cfg.domain.replace('.', "-");
    domain_dash == want
}

/// Handle a `tools/call` for `name == "station"` by dispatching through
/// `station_meta::dispatch` with local Router as the transport.
#[allow(clippy::too_many_arguments)]
pub fn handle_meta_call(
    registry: &ConfigRegistry,
    telemetry: &StationTelemetry,
    meter: Option<&StationMeter>,
    auth_gate: &ApiKeyGate,
    auth_header: Option<&str>,
    proxy_cache: Option<&router::ProxyCache>,
    arguments: &Value,
) -> ToolCallResult {
    let req: MetaRequest = match serde_json::from_value(arguments.clone()) {
        Ok(r) => r,
        Err(e) => {
            return ToolCallResult {
                content: vec![ContentBlock::Text {
                    text: json!({"status":"error","error":format!("invalid arguments: {e}")})
                        .to_string(),
                }],
                is_error: Some(true),
            };
        }
    };

    let index = discovery_index(registry);
    let client = LocalRouterClient {
        registry,
        telemetry,
        meter,
        auth_gate,
        auth_header,
        proxy_cache,
    };

    let response: MetaResponse = match dispatch(req, index, &client) {
        Ok(r) => r,
        Err(e) => MetaResponse {
            mode: "error".into(),
            candidates: None,
            execution: None,
            explanation: None,
            error: Some(format!("dispatch failed: {e}")),
        },
    };

    let is_error = response.error.is_some()
        || response
            .execution
            .as_ref()
            .is_some_and(|x| !x.is_ok());

    let text = serde_json::to_string(&response).unwrap_or_else(|_| r#"{"error":"serialization"}"#.into());
    ToolCallResult {
        content: vec![ContentBlock::Text { text }],
        is_error: if is_error { Some(true) } else { None },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn station_tool_info_has_expected_shape() {
        let info = station_tool_info();
        assert_eq!(info.name, "station");
        assert!(info.description.contains("Station"));
        // Schema must require `mode`
        let required = info
            .input_schema
            .get("required")
            .and_then(|v| v.as_array())
            .expect("required array");
        assert!(required.iter().any(|v| v.as_str() == Some("mode")));
        // `mode` enum must include both values
        let mode_enum = info
            .input_schema
            .pointer("/properties/mode/enum")
            .and_then(|v| v.as_array())
            .expect("mode enum");
        let modes: Vec<&str> = mode_enum.iter().filter_map(|v| v.as_str()).collect();
        assert!(modes.contains(&"discover"));
        assert!(modes.contains(&"execute"));
        assert!(modes.contains(&"explain"), "explain arm must be advertised");
        // Annotations deliberately absent — the meta-tool routes to tools with
        // heterogeneous semantics. See station_tool_info comment for rationale.
        // Asserting absence protects the honesty decision against future drift.
        assert!(
            info.annotations.is_none(),
            "meta-tool must NOT claim read-only or non-destructive — it routes \
             to mutating tools (claude-fs-delete, fda-create-plan, etc.). \
             If this fails, either drop the annotation or split into separate \
             discover/execute meta-tools with correct per-tool hints."
        );
    }
}
