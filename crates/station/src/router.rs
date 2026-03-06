use serde_json::Value;
use std::process::Command;
use tracing::{info, warn};

use crate::config::{ConfigRegistry, HubConfig, ToolDef};
use crate::protocol::{ContentBlock, ToolCallResult};

/// Route a tool call to the appropriate handler.
pub fn route_tool_call(
    registry: &ConfigRegistry,
    tool_name: &str,
    arguments: &Value,
) -> ToolCallResult {
    // Meta-tools handled directly
    if tool_name == "nexvigilant_directory" {
        return handle_directory(registry);
    }
    if tool_name == "nexvigilant_capabilities" {
        return handle_capabilities(registry, arguments);
    }

    match registry.find_tool(tool_name) {
        Some((config, tool)) => execute_tool(config, tool, tool_name, arguments, &registry.station_root),
        None => ToolCallResult {
            content: vec![ContentBlock::Text {
                text: format!("Unknown tool: {tool_name}. Use nexvigilant_directory to list all available tools."),
            }],
            is_error: Some(true),
        },
    }
}

/// Execute a resolved tool via its proxy script or stub.
fn execute_tool(
    config: &HubConfig,
    tool: &ToolDef,
    mcp_name: &str,
    arguments: &Value,
    station_root: &str,
) -> ToolCallResult {
    info!(
        domain = %config.domain,
        tool = %tool.name,
        "Executing tool"
    );

    // If the tool has a stub response, return it directly
    if let Some(stub) = &tool.stub_response {
        return ToolCallResult {
            content: vec![ContentBlock::Text {
                text: stub.clone(),
            }],
            is_error: None,
        };
    }

    // Try proxy execution: config-level proxy or tool-level proxy
    let proxy_path = tool
        .proxy
        .as_ref()
        .or(config.proxy.as_ref());

    if let Some(proxy) = proxy_path {
        return execute_proxy(proxy, mcp_name, arguments, station_root);
    }

    // No proxy, no stub — return structured info
    let result = serde_json::json!({
        "domain": config.domain,
        "tool": tool.name,
        "arguments": arguments,
        "status": "no_handler",
        "message": format!(
            "Tool '{}' on domain '{}' has no proxy or stub. \
             Add a 'proxy' field to the config or tool definition.",
            tool.name, config.domain
        ),
    });

    ToolCallResult {
        content: vec![ContentBlock::Text {
            text: serde_json::to_string_pretty(&result).unwrap_or_default(),
        }],
        is_error: None,
    }
}

/// Execute a tool via the unified dispatch.py script (or direct proxy fallback).
///
/// The dispatcher reads a JSON envelope from stdin:
///   {"tool": "api_fda_gov_search_adverse_events", "arguments": {...}}
///
/// It routes by domain prefix to the correct proxy script, which hits the live API.
fn execute_proxy(
    _proxy_path: &str,
    tool_name: &str,
    arguments: &Value,
    station_root: &str,
) -> ToolCallResult {
    let dispatch_path = format!("{}/scripts/dispatch.py", station_root);

    info!(
        tool = %tool_name,
        "Dispatching via unified dispatcher"
    );

    // The tool_name coming in is already the full MCP-prefixed name
    // (e.g., "api_fda_gov_search_adverse_events") from config.rs prefixing
    let envelope = serde_json::json!({
        "tool": tool_name,
        "arguments": arguments,
    });
    let envelope_str = serde_json::to_string(&envelope).unwrap_or_else(|_| "{}".into());

    let output = Command::new("python3")
        .arg(&dispatch_path)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .current_dir(station_root)
        .spawn()
        .and_then(|mut child| {
            use std::io::Write;
            if let Some(ref mut stdin) = child.stdin {
                let _ = stdin.write_all(envelope_str.as_bytes());
            }
            drop(child.stdin.take());
            child.wait_with_output()
        });

    match output {
        Ok(result) => {
            let stdout = String::from_utf8_lossy(&result.stdout).to_string();
            let stderr = String::from_utf8_lossy(&result.stderr).to_string();

            if !result.status.success() {
                warn!(
                    proxy = %dispatch_path,
                    tool = %tool_name,
                    stderr = %stderr,
                    "Proxy returned non-zero exit"
                );
                return ToolCallResult {
                    content: vec![ContentBlock::Text {
                        text: if stderr.is_empty() {
                            format!("Proxy error (exit {}): {}", result.status, stdout)
                        } else {
                            format!("Proxy error: {}", stderr)
                        },
                    }],
                    is_error: Some(true),
                };
            }

            // Try to parse as JSON for clean output, fall back to raw text
            let text = if stdout.trim().is_empty() {
                "Proxy returned empty response".into()
            } else if let Ok(json) = serde_json::from_str::<Value>(stdout.trim()) {
                serde_json::to_string_pretty(&json).unwrap_or(stdout)
            } else {
                stdout
            };

            ToolCallResult {
                content: vec![ContentBlock::Text { text }],
                is_error: None,
            }
        }
        Err(e) => {
            warn!(
                proxy = %dispatch_path,
                error = %e,
                "Failed to spawn proxy"
            );
            ToolCallResult {
                content: vec![ContentBlock::Text {
                    text: format!("Failed to execute proxy {dispatch_path}: {e}"),
                }],
                is_error: Some(true),
            }
        }
    }
}

/// Meta-tool: List all NexVigilant capabilities as a structured directory.
fn handle_directory(registry: &ConfigRegistry) -> ToolCallResult {
    let mut domains: Vec<Value> = Vec::new();

    for config in &registry.configs {
        let tools: Vec<Value> = config
            .tools
            .iter()
            .map(|t| {
                let params: Vec<String> = t.parameters.iter().map(|p| {
                    let req = if p.required { " (required)" } else { "" };
                    format!("{}: {}{}", p.name, p.param_type, req)
                }).collect();

                serde_json::json!({
                    "name": t.name,
                    "description": t.description,
                    "parameters": params,
                    "has_handler": t.proxy.is_some() || t.stub_response.is_some() || config.proxy.is_some(),
                })
            })
            .collect();

        domains.push(serde_json::json!({
            "domain": config.domain,
            "title": config.title,
            "description": config.description,
            "tool_count": config.tools.len(),
            "has_proxy": config.proxy.is_some(),
            "tools": tools,
        }));
    }

    let directory = serde_json::json!({
        "station": "NexVigilant Station",
        "version": env!("CARGO_PKG_VERSION"),
        "description": "Pharmacovigilance intelligence platform — drug safety monitoring, signal detection, regulatory data extraction across FDA, EMA, WHO, and clinical trial registries.",
        "total_domains": registry.configs.len(),
        "total_tools": registry.tool_count(),
        "domains": domains,
        "access_surfaces": [
            "MCP server (stdio) — direct tool invocation",
            "WebMCP Hub configs — browser-based agent discovery",
            "REST API — programmatic access via nexcore-api",
            "Standalone MCP — mcp-remote via Cloudflare Worker"
        ],
        "data_flow": "Hub Config (extraction) → Structured Data → Signal Detection (PRR/ROR/IC/EBGM) → Causality Assessment → Action",
    });

    ToolCallResult {
        content: vec![ContentBlock::Text {
            text: serde_json::to_string_pretty(&directory).unwrap_or_default(),
        }],
        is_error: None,
    }
}

/// Meta-tool: Search capabilities by domain or keyword.
fn handle_capabilities(registry: &ConfigRegistry, arguments: &Value) -> ToolCallResult {
    let query = arguments
        .get("query")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_lowercase();

    let domain_filter = arguments
        .get("domain")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_lowercase();

    let mut matches: Vec<Value> = Vec::new();

    for config in &registry.configs {
        let domain_match = domain_filter.is_empty()
            || config.domain.to_lowercase().contains(&domain_filter);

        for tool in &config.tools {
            let text_match = query.is_empty()
                || tool.name.to_lowercase().contains(&query)
                || tool.description.to_lowercase().contains(&query);

            if domain_match && text_match {
                let prefixed = format!(
                    "{}_{}",
                    config.domain.replace('.', "_"),
                    tool.name.replace('-', "_")
                );
                matches.push(serde_json::json!({
                    "mcp_name": prefixed,
                    "domain": config.domain,
                    "tool": tool.name,
                    "description": tool.description,
                    "live": tool.proxy.is_some() || tool.stub_response.is_some() || config.proxy.is_some(),
                }));
            }
        }
    }

    let result = serde_json::json!({
        "query": query,
        "domain_filter": domain_filter,
        "matches": matches.len(),
        "tools": matches,
    });

    ToolCallResult {
        content: vec![ContentBlock::Text {
            text: serde_json::to_string_pretty(&result).unwrap_or_default(),
        }],
        is_error: None,
    }
}
