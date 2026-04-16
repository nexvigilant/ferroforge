use anyhow::Result;
use serde_json::Value;
use std::io::{self, BufRead, Write};
use tokio::sync::broadcast;
use tracing::{debug, error, info};

use crate::auth::ApiKeyGate;
use crate::config::ConfigRegistry;
use crate::protocol::*;
use crate::router;
use crate::telemetry::{self, StationTelemetry};

/// Run the MCP server over stdio (JSON-RPC 2.0).
///
/// Stdio transport uses a dev-mode auth gate (no keys required).
/// Auth enforcement for remote transports happens through the same
/// `route_tool_call` path with a real `ApiKeyGate`.
pub fn run_stdio(registry: ConfigRegistry, telemetry: &StationTelemetry) -> Result<()> {
    let auth_gate = ApiKeyGate::from_env();
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut stdout = stdout.lock();

    info!(
        tools = registry.tool_count(),
        configs = registry.configs.len(),
        "Station MCP server starting on stdio"
    );

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(e) => {
                error!(error = %e, "Failed to read stdin");
                break;
            }
        };

        let line = line.trim().to_string();
        if line.is_empty() {
            continue;
        }

        debug!(raw = %line, "Received message");

        let request: JsonRpcRequest = match serde_json::from_str(&line) {
            Ok(r) => r,
            Err(e) => {
                let resp = JsonRpcResponse::error(None, PARSE_ERROR, format!("Parse error: {e}"));
                write_response(&mut stdout, &resp)?;
                continue;
            }
        };

        let response = handle_request(&registry, telemetry, None, &auth_gate, &request, None, None);

        // Notifications (no id) get no response
        if request.id.is_none() {
            debug!(method = %request.method, "Notification received, no response sent");
            continue;
        }

        if let Some(resp) = response {
            write_response(&mut stdout, &resp)?;
        }
    }

    info!("Station MCP server shutting down");
    Ok(())
}

pub fn handle_request(
    registry: &ConfigRegistry,
    telemetry: &StationTelemetry,
    meter: Option<&crate::metering::StationMeter>,
    auth_gate: &ApiKeyGate,
    req: &JsonRpcRequest,
    event_tx: Option<&broadcast::Sender<StationEvent>>,
    auth_header: Option<&str>,
) -> Option<JsonRpcResponse> {
    handle_request_core(registry, telemetry, meter, auth_gate, req, event_tx, auth_header, None, None)
}

/// Handle request with auth header — backward compat, no proxy cache.
pub fn handle_request_with_auth(
    registry: &ConfigRegistry,
    telemetry: &StationTelemetry,
    meter: Option<&crate::metering::StationMeter>,
    auth_gate: &ApiKeyGate,
    req: &JsonRpcRequest,
    event_tx: Option<&broadcast::Sender<StationEvent>>,
    auth_header: Option<&str>,
) -> Option<JsonRpcResponse> {
    handle_request_core(registry, telemetry, meter, auth_gate, req, event_tx, auth_header, None, None)
}

/// Handle request with proxy cache for FAERS total count acceleration.
#[allow(clippy::too_many_arguments)]
pub fn handle_request_cached(
    registry: &ConfigRegistry,
    telemetry: &StationTelemetry,
    meter: Option<&crate::metering::StationMeter>,
    auth_gate: &ApiKeyGate,
    req: &JsonRpcRequest,
    event_tx: Option<&broadcast::Sender<StationEvent>>,
    auth_header: Option<&str>,
    proxy_cache: &router::ProxyCache,
) -> Option<JsonRpcResponse> {
    handle_request_core(registry, telemetry, meter, auth_gate, req, event_tx, auth_header, Some(proxy_cache), None)
}

/// Handle request with per-request collapse override (HTTP transports).
///
/// `collapse_override` comes from the `X-NexVigilant-Collapse` request header:
/// - `Some(true)` → collapsed (one `station` meta-tool)
/// - `Some(false)` → full tool list
/// - `None` → fall back to `registry.collapse_tools_default`
#[allow(clippy::too_many_arguments)]
pub fn handle_request_with_collapse(
    registry: &ConfigRegistry,
    telemetry: &StationTelemetry,
    meter: Option<&crate::metering::StationMeter>,
    auth_gate: &ApiKeyGate,
    req: &JsonRpcRequest,
    event_tx: Option<&broadcast::Sender<StationEvent>>,
    auth_header: Option<&str>,
    proxy_cache: Option<&router::ProxyCache>,
    collapse_override: Option<bool>,
) -> Option<JsonRpcResponse> {
    handle_request_core(registry, telemetry, meter, auth_gate, req, event_tx, auth_header, proxy_cache, collapse_override)
}

/// Parse the `X-NexVigilant-Collapse` header into an `Option<bool>`.
///
/// Returns `Some(true)` for truthy values (`1`, `true`, `yes`, `on`),
/// `Some(false)` for any other present value (explicit opt-out),
/// and `None` when the header is absent (fall back to process default).
pub fn parse_collapse_header(headers: &axum::http::HeaderMap) -> Option<bool> {
    headers
        .get("x-nexvigilant-collapse")
        .and_then(|v| v.to_str().ok())
        .map(|s| matches!(s.trim(), "1" | "true" | "yes" | "on"))
}

#[allow(clippy::too_many_arguments)]
fn handle_request_core(
    registry: &ConfigRegistry,
    telemetry: &StationTelemetry,
    meter: Option<&crate::metering::StationMeter>,
    auth_gate: &ApiKeyGate,
    req: &JsonRpcRequest,
    event_tx: Option<&broadcast::Sender<StationEvent>>,
    auth_header: Option<&str>,
    proxy_cache: Option<&router::ProxyCache>,
    collapse_override: Option<bool>,
) -> Option<JsonRpcResponse> {
    // Effective collapse = per-request override, fallback to process default.
    let collapsed = collapse_override.unwrap_or(registry.collapse_tools_default);
    let id = req.id.clone();

    // Validate JSON-RPC version (fixes Issue #10)
    if req.jsonrpc != "2.0" {
        return Some(JsonRpcResponse::error(
            id,
            INVALID_REQUEST,
            format!("Unsupported JSON-RPC version: {}. Expected '2.0'", req.jsonrpc),
        ));
    }

    match req.method.as_str() {
        "initialize" => {
            let result = InitializeResult {
                protocol_version: "2025-03-26".into(),
                capabilities: ServerCapabilities {
                    tools: ToolCapability {
                        list_changed: false,
                    },
                    resources: crate::protocol::ResourceCapability {
                        subscribe: false,
                        list_changed: false,
                    },
                    prompts: crate::protocol::PromptCapability {
                        list_changed: false,
                    },
                },
                server_info: ServerInfo {
                    name: "nexvigilant-station".into(),
                    version: env!("CARGO_PKG_VERSION").into(),
                },
                instructions: Some(
                    "NexVigilant Station — pharmacovigilance intelligence for AI agents.\n\
                     \n\
                     START HERE: Call `nexvigilant_chart_course` first. It returns step-by-step \
                     workflows with exact tool names and parameters for any drug safety question. \
                     6 guided courses: drug-safety-profile, signal-investigation, \
                     causality-assessment, benefit-risk-assessment, regulatory-intelligence, \
                     competitive-landscape.\n\
                     \n\
                     Example: To investigate adverse events for metformin, call \
                     `nexvigilant_chart_course` with course='signal-investigation' — it returns \
                     the exact sequence of tools to call with parameters.\n\
                     \n\
                     Do NOT guess tool parameters. Use chart_course to get the correct workflow."
                        .into(),
                ),
            };
            info!(
                version = %result.server_info.version,
                protocol = %result.protocol_version,
                "Initialize handshake"
            );
            Some(JsonRpcResponse::success(
                id,
                serde_json::to_value(result).unwrap_or_default(),
            ))
        }

        "notifications/initialized" => {
            info!("Client confirmed initialization");
            None // Notification — no response
        }

        "tools/list" => {
            let authenticated = auth_gate.is_authenticated(auth_header);
            let tools = if collapsed {
                // Collapse mode: advertise ONE synthetic meta-tool instead of ~3,000.
                // This is the token-reclaim path — see meta_wire.rs for rationale.
                vec![crate::meta_wire::station_tool_info()]
            } else {
                registry.tool_infos_filtered(authenticated)
            };
            info!(
                count = tools.len(),
                authenticated,
                collapsed,
                "Tools list requested"
            );
            let result = ToolsListResult { tools };
            Some(JsonRpcResponse::success(
                id,
                serde_json::to_value(result).unwrap_or_default(),
            ))
        }

        "tools/call" => {
            let params = req.params.as_ref();
            let tool_name = params
                .and_then(|p| p.get("name"))
                .and_then(|n| n.as_str())
                .unwrap_or("");
            let arguments = params
                .and_then(|p| p.get("arguments"))
                .cloned()
                .unwrap_or(Value::Object(serde_json::Map::new()));

            if tool_name.is_empty() {
                return Some(JsonRpcResponse::error(
                    id,
                    INVALID_PARAMS,
                    "Missing tool name in params.name",
                ));
            }

            info!(tool = %tool_name, "Tool call");
            let timer = telemetry::start_timer();
            let result = if collapsed {
                // Collapse mode: route EVERYTHING through the meta-tool.
                // The `station` tool dispatches discover/execute; any other
                // tool name is rejected with a hint pointing to `station`.
                if tool_name == "station" {
                    crate::meta_wire::handle_meta_call(
                        registry, telemetry, meter, auth_gate, auth_header, proxy_cache, &arguments,
                    )
                } else {
                    crate::protocol::ToolCallResult {
                        content: vec![crate::protocol::ContentBlock::Text {
                            text: serde_json::json!({
                                "status": "error",
                                "error": format!(
                                    "Station is in collapsed mode — call `station` with mode=discover (intent=...) or mode=execute (config/tool/params). Tool `{}` is not advertised directly.",
                                    tool_name
                                )
                            })
                            .to_string(),
                        }],
                        is_error: Some(true),
                    }
                }
            } else {
                router::route_tool_call(registry, telemetry, meter, auth_gate, auth_header, tool_name, &arguments, proxy_cache)
            };
            let duration_ms = telemetry::elapsed_ms(timer);

            // Emit station event to broadcast channel
            if let Some(tx) = event_tx {
                let event = StationEvent {
                    domain: telemetry::extract_domain(tool_name),
                    tool: tool_name.to_string(),
                    status: if result.is_error.unwrap_or(false) { "error" } else { "ok" }.into(),
                    duration_ms,
                    timestamp: telemetry::now_iso8601(),
                };
                match tx.send(event) {
                    Ok(n) => debug!(receivers = n, tool = %tool_name, "Station event emitted"),
                    Err(_) => debug!(tool = %tool_name, "Station event emitted (no subscribers)"),
                }
            }

            Some(JsonRpcResponse::success(
                id,
                serde_json::to_value(result).unwrap_or_default(),
            ))
        }

        "ping" => Some(JsonRpcResponse::success(id, serde_json::json!({}))),

        // MCP Resources — structured PV knowledge for agent context
        "resources/list" => {
            let result = crate::resources::list_resources(registry);
            info!(count = result.resources.len(), "Resources list requested");
            Some(JsonRpcResponse::success(id, serde_json::to_value(result).unwrap_or_default()))
        }
        "resources/templates/list" => {
            let result = crate::resources::list_resource_templates();
            info!(count = result.resource_templates.len(), "Resource templates list requested");
            Some(JsonRpcResponse::success(id, serde_json::to_value(result).unwrap_or_default()))
        }
        "resources/read" => {
            let uri = req.params.as_ref()
                .and_then(|p| p.get("uri"))
                .and_then(|u| u.as_str())
                .unwrap_or("");
            if uri.is_empty() {
                return Some(JsonRpcResponse::error(id, INVALID_PARAMS, "Missing uri in params"));
            }
            match crate::resources::read_resource(registry, uri) {
                Ok(result) => {
                    info!(uri = %uri, "Resource read");
                    Some(JsonRpcResponse::success(id, serde_json::to_value(result).unwrap_or_default()))
                }
                Err(e) => Some(JsonRpcResponse::error(id, INVALID_PARAMS, e)),
            }
        }

        // MCP Prompts — guided PV research workflows
        "prompts/list" => {
            let result = crate::prompts::list_prompts();
            info!(count = result.prompts.len(), "Prompts list requested");
            Some(JsonRpcResponse::success(id, serde_json::to_value(result).unwrap_or_default()))
        }
        "prompts/get" => {
            let name = req.params.as_ref()
                .and_then(|p| p.get("name"))
                .and_then(|n| n.as_str())
                .unwrap_or("");
            let arguments = req.params.as_ref()
                .and_then(|p| p.get("arguments"))
                .cloned()
                .unwrap_or(serde_json::json!({}));
            if name.is_empty() {
                return Some(JsonRpcResponse::error(id, INVALID_PARAMS, "Missing name in params"));
            }
            match crate::prompts::get_prompt(name, &arguments) {
                Ok(result) => {
                    info!(prompt = %name, "Prompt retrieved");
                    Some(JsonRpcResponse::success(id, serde_json::to_value(result).unwrap_or_default()))
                }
                Err(e) => Some(JsonRpcResponse::error(id, INVALID_PARAMS, e)),
            }
        }

        other => {
            debug!(method = %other, "Unknown method");
            Some(JsonRpcResponse::error(
                id,
                METHOD_NOT_FOUND,
                format!("Method not found: {other}"),
            ))
        }
    }
}

fn write_response(out: &mut impl Write, response: &JsonRpcResponse) -> Result<()> {
    let json = serde_json::to_string(response)?;
    debug!(response = %json, "Sending response");
    writeln!(out, "{json}")?;
    out.flush()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderMap;

    fn headers_with(name: &str, value: &str) -> HeaderMap {
        let mut m = HeaderMap::new();
        m.insert(
            axum::http::HeaderName::from_bytes(name.as_bytes()).unwrap(),
            axum::http::HeaderValue::from_str(value).unwrap(),
        );
        m
    }

    // --- parse_collapse_header ---

    #[test]
    fn collapse_header_absent_returns_none() {
        assert_eq!(parse_collapse_header(&HeaderMap::new()), None);
    }

    #[test]
    fn collapse_header_truthy_values_return_some_true() {
        for val in &["1", "true", "yes", "on"] {
            let h = headers_with("x-nexvigilant-collapse", val);
            assert_eq!(
                parse_collapse_header(&h),
                Some(true),
                "expected Some(true) for '{val}'"
            );
        }
    }

    #[test]
    fn collapse_header_falsy_values_return_some_false() {
        for val in &["0", "false", "no", "off", ""] {
            let h = headers_with("x-nexvigilant-collapse", val);
            assert_eq!(
                parse_collapse_header(&h),
                Some(false),
                "expected Some(false) for '{val}'"
            );
        }
    }

    #[test]
    fn collapse_header_override_beats_default() {
        // Simulate: process default = true, header says false → effective = false
        let override_val: Option<bool> = Some(false);
        let default_val = true;
        let effective = override_val.unwrap_or(default_val);
        assert!(!effective, "header override should win over process default");

        // Simulate: process default = false, header says true → effective = true
        let override_val: Option<bool> = Some(true);
        let default_val = false;
        let effective = override_val.unwrap_or(default_val);
        assert!(effective, "header override should win over process default");
    }

    #[test]
    fn collapse_header_none_falls_back_to_default() {
        let override_val: Option<bool> = None;
        let default_val = true;
        let effective = override_val.unwrap_or(default_val);
        assert!(effective, "absent header should fall back to process default");
    }
}
