use anyhow::Result;
use serde_json::Value;
use std::io::{self, BufRead, Write};
use tracing::{debug, error, info};

use crate::config::ConfigRegistry;
use crate::protocol::*;
use crate::router;
use crate::telemetry::StationTelemetry;

/// Run the MCP server over stdio (JSON-RPC 2.0).
pub fn run_stdio(registry: ConfigRegistry, telemetry: &StationTelemetry) -> Result<()> {
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

        let response = handle_request(&registry, telemetry, &request);

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

pub fn handle_request(registry: &ConfigRegistry, telemetry: &StationTelemetry, req: &JsonRpcRequest) -> Option<JsonRpcResponse> {
    let id = req.id.clone();

    match req.method.as_str() {
        "initialize" => {
            let result = InitializeResult {
                protocol_version: "2024-11-05".into(),
                capabilities: ServerCapabilities {
                    tools: ToolCapability {
                        list_changed: false,
                    },
                },
                server_info: ServerInfo {
                    name: "nexvigilant-station".into(),
                    version: env!("CARGO_PKG_VERSION").into(),
                },
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
            let tools = registry.tool_infos();
            info!(count = tools.len(), "Tools list requested");
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
            let result = router::route_tool_call(registry, telemetry, tool_name, &arguments);
            Some(JsonRpcResponse::success(
                id,
                serde_json::to_value(result).unwrap_or_default(),
            ))
        }

        "ping" => Some(JsonRpcResponse::success(id, serde_json::json!({}))),

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
