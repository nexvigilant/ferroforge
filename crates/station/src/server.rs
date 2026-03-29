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
    handle_request_core(registry, telemetry, meter, auth_gate, req, event_tx, auth_header, None)
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
    handle_request_core(registry, telemetry, meter, auth_gate, req, event_tx, auth_header, None)
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
    handle_request_core(registry, telemetry, meter, auth_gate, req, event_tx, auth_header, Some(proxy_cache))
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
) -> Option<JsonRpcResponse> {
    let id = req.id.clone();

    match req.method.as_str() {
        "initialize" => {
            let result = InitializeResult {
                protocol_version: "2025-03-26".into(),
                capabilities: ServerCapabilities {
                    tools: ToolCapability {
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
            let tools = registry.tool_infos_filtered(authenticated);
            info!(count = tools.len(), authenticated, "Tools list requested");
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
            let result = router::route_tool_call(registry, telemetry, meter, auth_gate, auth_header, tool_name, &arguments, proxy_cache);
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

        // Return empty lists for capabilities we don't support.
        // Claude.ai sends these during bootstrap even when not advertised.
        "resources/list" => {
            debug!("resources/list requested (not supported, returning empty)");
            Some(JsonRpcResponse::success(id, serde_json::json!({ "resources": [] })))
        }
        "prompts/list" => {
            debug!("prompts/list requested (not supported, returning empty)");
            Some(JsonRpcResponse::success(id, serde_json::json!({ "prompts": [] })))
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
