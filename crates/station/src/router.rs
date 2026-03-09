use serde_json::Value;
use std::process::Command;
use tracing::{info, warn};
use uuid::Uuid;

use crate::auth::{ApiKeyGate, AuthResult, auth_error_json};
use crate::config::{ConfigRegistry, HubConfig, ToolDef};
use crate::protocol::{ContentBlock, ToolCallResult};
use crate::telemetry::{
    elapsed_ms, extract_domain, now_iso8601, start_timer, StationTelemetry, ToolCallRecord,
};

/// Route a tool call to the appropriate handler, with auth, telemetry, and rate limiting.
///
/// Auth enforcement lives here — the single chokepoint for all transports.
/// Pass `None` for `auth_header` in stdio/dev mode (auth gate handles it).
pub fn route_tool_call(
    registry: &ConfigRegistry,
    telemetry: &StationTelemetry,
    auth_gate: &ApiKeyGate,
    auth_header: Option<&str>,
    tool_name: &str,
    arguments: &Value,
) -> ToolCallResult {
    // Auth check FIRST — before rate limiting or execution
    let auth_result = auth_gate.check(auth_header, tool_name);
    if !matches!(auth_result, AuthResult::Allowed) {
        let error_json = auth_error_json(&auth_result);
        return ToolCallResult {
            content: vec![ContentBlock::Text {
                text: serde_json::to_string_pretty(&error_json).unwrap_or_default(),
            }],
            is_error: Some(true),
        };
    }

    let domain = extract_domain(tool_name);
    let request_id = Uuid::new_v4().to_string();

    // Rate limit check BEFORE executing
    let rate_check = telemetry.check_rate_limit(&domain);
    if !rate_check.allowed {
        warn!(
            domain = %domain,
            tool = %tool_name,
            count = rate_check.current_count,
            limit = rate_check.limit,
            retry_after = rate_check.retry_after_secs,
            "Rate limit exceeded"
        );

        // Record the rate-limited attempt in telemetry
        telemetry.record(ToolCallRecord {
            timestamp: now_iso8601(),
            tool_name: tool_name.to_string(),
            domain: domain.clone(),
            duration_ms: 0,
            status: "rate_limited".to_string(),
            is_error: true,
            error_message: Some(format!(
                "Rate limit exceeded: {}/{} calls in 60s",
                rate_check.current_count, rate_check.limit
            )),
            client_id: None,
            request_id: Some(request_id.clone()),
        });

        let response = serde_json::json!({
            "status": "rate_limited",
            "domain": domain,
            "tool": tool_name,
            "message": format!(
                "Rate limit exceeded for domain '{}': {}/{} calls in the last 60 seconds. Retry after {} seconds.",
                domain, rate_check.current_count, rate_check.limit, rate_check.retry_after_secs
            ),
            "current_count": rate_check.current_count,
            "limit": rate_check.limit,
            "retry_after_secs": rate_check.retry_after_secs,
        });

        return ToolCallResult {
            content: vec![ContentBlock::Text {
                text: serde_json::to_string_pretty(&response).unwrap_or_default(),
            }],
            is_error: Some(true),
        };
    }

    let timer = start_timer();
    let mut result = route_tool_call_inner(registry, telemetry, tool_name, arguments, &request_id);
    let duration_ms = elapsed_ms(timer);

    // Extract status and error detail from the result content
    let (status, is_error, error_message) = extract_status(&result);

    telemetry.record(ToolCallRecord {
        timestamp: now_iso8601(),
        tool_name: tool_name.to_string(),
        domain,
        duration_ms,
        status,
        is_error,
        error_message,
        client_id: None,
        request_id: Some(request_id.clone()),
    });

    // Inject request_id into the response JSON for client correlation
    inject_request_id(&mut result, &request_id);

    result
}

/// Extract status, error flag, and error message from a tool call result.
///
/// Ensures consistency: if either the MCP `is_error` flag or the JSON `status`
/// field indicates an error, both the returned status and is_error agree.
/// Also extracts error messages for the "why it failed" telemetry field.
fn extract_status(result: &ToolCallResult) -> (String, bool, Option<String>) {
    let mcp_error = result.is_error.unwrap_or(false);

    // Try to parse the content as JSON and extract "status" field
    if let Some(ContentBlock::Text { text }) = result.content.first()
        && let Ok(json) = serde_json::from_str::<Value>(text)
        && let Some(status) = json.get("status").and_then(|s| s.as_str())
    {
        // Reconcile: if EITHER signal says error, mark as error
        let status_signals_error = matches!(status, "error" | "no_handler");
        let is_error = mcp_error || status_signals_error;

        // Extract error message from common fields
        let error_message = if is_error {
            json.get("message")
                .or_else(|| json.get("error"))
                .and_then(|v| v.as_str())
                .map(|s| s.chars().take(256).collect())
        } else {
            None
        };

        return (status.to_string(), is_error, error_message);
    }

    if mcp_error {
        // Extract error message from raw text content
        let error_message = result.content.first().map(|c| match c {
            ContentBlock::Text { text } => text.chars().take(256).collect(),
        });
        ("error".to_string(), true, error_message)
    } else {
        ("ok".to_string(), false, None)
    }
}

/// Inner routing logic (no telemetry wrapping).
fn route_tool_call_inner(
    registry: &ConfigRegistry,
    telemetry: &StationTelemetry,
    tool_name: &str,
    arguments: &Value,
    request_id: &str,
) -> ToolCallResult {
    // Meta-tools handled directly
    if tool_name == "nexvigilant_directory" {
        return handle_directory(registry);
    }
    if tool_name == "nexvigilant_capabilities" {
        return handle_capabilities(registry, arguments);
    }
    if tool_name == "nexvigilant_station_health" {
        return handle_station_health(telemetry, registry);
    }

    // Rust-native handlers — no Python proxy needed
    if let Some(result) = crate::compute::try_handle(tool_name, arguments) {
        return result;
    }
    if let Some(result) = crate::science::try_handle(tool_name, arguments, registry) {
        return result;
    }

    match registry.find_tool(tool_name) {
        Some((config, tool)) => execute_tool(config, tool, tool_name, arguments, &registry.station_root, request_id),
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
    request_id: &str,
) -> ToolCallResult {
    info!(
        domain = %config.domain,
        tool = %tool.name,
        "Executing tool"
    );

    // Try proxy execution first: config-level proxy or tool-level proxy
    let proxy_path = tool
        .proxy
        .as_ref()
        .or(config.proxy.as_ref());

    if let Some(proxy) = proxy_path {
        return execute_proxy(proxy, mcp_name, arguments, station_root, request_id);
    }

    // Fall back to stub response if no proxy is available
    if let Some(stub) = &tool.stub_response {
        return ToolCallResult {
            content: vec![ContentBlock::Text {
                text: stub.clone(),
            }],
            is_error: None,
        };
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

/// Execute a tool via its proxy script.
///
/// Two modes:
/// 1. **Direct proxy** — if proxy_path points to a specific per-tool script
///    (not dispatch.py), run it directly with the unprefixed tool name.
/// 2. **Unified dispatch** — otherwise route through dispatch.py which
///    parses the domain prefix and delegates to the correct proxy.
fn execute_proxy(
    proxy_path: &str,
    tool_name: &str,
    arguments: &Value,
    station_root: &str,
    request_id: &str,
) -> ToolCallResult {
    let resolved_path = if proxy_path.ends_with("dispatch.py") {
        format!("{}/scripts/dispatch.py", station_root)
    } else {
        // Per-tool proxy: resolve relative to station_root
        if proxy_path.starts_with('/') {
            proxy_path.to_string()
        } else {
            format!("{}/{}", station_root, proxy_path)
        }
    };

    let is_dispatch = resolved_path.ends_with("dispatch.py");

    info!(
        tool = %tool_name,
        proxy = %resolved_path,
        direct = !is_dispatch,
        "Executing proxy"
    );

    // For direct proxy: strip domain prefix to get bare tool name.
    // For dispatch: send the full MCP-prefixed name (dispatch parses it).
    let envelope = if is_dispatch {
        serde_json::json!({
            "tool": tool_name,
            "arguments": arguments,
            "request_id": request_id,
        })
    } else {
        // Extract bare tool name: strip everything up to and including the
        // last domain-separator pattern. The config tool name is already
        // bare (kebab-case), but MCP names arrive prefixed.
        let bare = strip_domain_prefix(tool_name);
        serde_json::json!({
            "tool": bare,
            "arguments": arguments,
            "request_id": request_id,
        })
    };
    let envelope_str = serde_json::to_string(&envelope).unwrap_or_else(|_| "{}".into());

    // Proxy timeout: 30 seconds. Upstream APIs should respond in <15s;
    // 30s gives headroom for slow networks without hanging indefinitely.
    let proxy_timeout = std::time::Duration::from_secs(30);

    let output = Command::new("python3")
        .arg(&resolved_path)
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

            // Wait with timeout using a channel — no external crate needed.
            // Spawn a thread to call wait_with_output (blocking), then recv
            // with a deadline on the main thread.
            let (tx, rx) = std::sync::mpsc::channel();
            std::thread::spawn(move || {
                let result = child.wait_with_output();
                let _ = tx.send(result);
            });

            match rx.recv_timeout(proxy_timeout) {
                Ok(result) => result,
                Err(_) => {
                    // Timeout — the spawned thread still owns child, which
                    // will be dropped (and the process killed) when the
                    // thread completes. We return a timeout error immediately.
                    Err(std::io::Error::new(
                        std::io::ErrorKind::TimedOut,
                        "proxy timed out after 30s",
                    ))
                }
            }
        });

    match output {
        Ok(result) => {
            let stdout = String::from_utf8_lossy(&result.stdout).to_string();
            let stderr = String::from_utf8_lossy(&result.stderr).to_string();

            if !result.status.success() {
                warn!(
                    proxy = %resolved_path,
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
                proxy = %resolved_path,
                error = %e,
                "Failed to spawn proxy"
            );
            ToolCallResult {
                content: vec![ContentBlock::Text {
                    text: format!("Failed to execute proxy {resolved_path}: {e}"),
                }],
                is_error: Some(true),
            }
        }
    }
}

/// Inject `request_id` into the tool call response for client-side correlation.
///
/// If the response content is valid JSON (object), adds a top-level `_request_id` field.
/// Non-JSON responses and arrays are left unchanged — the ID only makes sense
/// when there's a natural place to attach it.
fn inject_request_id(result: &mut ToolCallResult, request_id: &str) {
    if let Some(ContentBlock::Text { text }) = result.content.first_mut()
        && let Ok(mut json) = serde_json::from_str::<Value>(text)
        && let Some(obj) = json.as_object_mut()
    {
        obj.insert("_request_id".into(), Value::String(request_id.into()));
        if let Ok(updated) = serde_json::to_string_pretty(&json) {
            *text = updated;
        }
    }
}

/// Strip domain prefix from an MCP tool name.
///
/// Input:  `"api_fda_gov_search_adverse_events"`
/// Output: `"search-adverse-events"`
///
/// Heuristic: domain prefixes end with a known TLD segment followed by `_`.
/// We find the last TLD-like segment (`_gov_`, `_com_`, `_org_`, `_eu_`, `_fr_`,
/// `_ch_`, `_int_`) and strip everything up to and including it.
/// Remaining underscores become hyphens (kebab-case).
fn strip_domain_prefix(mcp_name: &str) -> String {
    let tld_markers = ["_gov_", "_com_", "_org_", "_eu_", "_fr_", "_ch_", "_int_"];

    for marker in &tld_markers {
        if let Some(pos) = mcp_name.rfind(marker) {
            let bare = &mcp_name[pos + marker.len()..];
            return bare.replace('_', "-");
        }
    }

    // No TLD found — return as-is with underscore→hyphen conversion
    mcp_name.replace('_', "-")
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

    let courses: Vec<Value> = crate::science::course_summaries()
        .into_iter()
        .map(|(name, desc, steps)| serde_json::json!({
            "course": name,
            "description": desc,
            "steps": steps,
        }))
        .collect();

    let directory = serde_json::json!({
        "station": "NexVigilant Station",
        "version": env!("CARGO_PKG_VERSION"),
        "git_sha": env!("GIT_SHA"),
        "description": "Pharmacovigilance intelligence platform — drug safety monitoring, signal detection, regulatory data extraction across FDA, EMA, WHO, and clinical trial registries.",
        "total_domains": registry.configs.len(),
        "total_tools": registry.tool_count(),
        "total_courses": crate::science::course_count(),
        "domains": domains,
        "courses": courses,
        "access_surfaces": [
            "MCP server (stdio) — direct tool invocation for Claude Code",
            "Cloud Run (mcp.nexvigilant.com) — SSE + HTTP REST for any MCP client",
            "Standalone MCP — npx mcp-remote https://mcp.nexvigilant.com/sse"
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

/// Meta-tool: Station health — summary telemetry (recent_calls redacted for public surface).
fn handle_station_health(telemetry: &StationTelemetry, registry: &ConfigRegistry) -> ToolCallResult {
    let mut health = telemetry.health();
    health.config_hash = Some(registry.config_hash());

    // Serialize then redact recent_calls — operational intelligence not for public
    let mut health_json = serde_json::to_value(&health).unwrap_or_default();
    if let Some(obj) = health_json.as_object_mut() {
        obj.remove("recent_calls");
        obj.insert("courses".into(), serde_json::json!(crate::science::course_count()));
    }

    ToolCallResult {
        content: vec![ContentBlock::Text {
            text: serde_json::to_string_pretty(&health_json).unwrap_or_default(),
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

    // Also match courses by name or description
    let matching_courses: Vec<Value> = crate::science::course_summaries()
        .into_iter()
        .filter(|(name, desc, _)| {
            query.is_empty()
                || name.to_lowercase().contains(&query)
                || desc.to_lowercase().contains(&query)
        })
        .map(|(name, desc, steps)| serde_json::json!({
            "course": name,
            "description": desc,
            "steps": steps,
        }))
        .collect();

    let result = serde_json::json!({
        "query": query,
        "domain_filter": domain_filter,
        "matches": matches.len(),
        "tools": matches,
        "matching_courses": matching_courses,
    });

    ToolCallResult {
        content: vec![ContentBlock::Text {
            text: serde_json::to_string_pretty(&result).unwrap_or_default(),
        }],
        is_error: None,
    }
}
