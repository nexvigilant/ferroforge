//! NexCore Bridge — Rust-native bridge to the nexcore-mcp binary.
//!
//! Handles all rust-native tools that don't have a dedicated handler in the Station.
//! Eliminates Python overhead for 100+ tools.

use serde_json::{Value, json};
use std::process::{Command, Stdio};
use std::io::{Write, Read};
use tracing::{info, warn};

use crate::protocol::{ContentBlock, ToolCallResult};

/// Try to handle a tool call via the NexCore bridge.
pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    // We only handle tools that look like NexCore domain-prefixed tools.
    // Example: adventure_nexvigilant_com_list_adventures
    if !tool_name.contains("_nexvigilant_com_") {
        return None;
    }

    // Find the binary
    let binary = find_nexcore_mcp()?;

    info!(tool = tool_name, "Routing to nexcore-mcp via Rust bridge");

    match call_mcp(&binary, tool_name, args) {
        Ok(res) => Some(ToolCallResult {
            content: vec![ContentBlock::Text {
                text: serde_json::to_string_pretty(&res).unwrap_or_default(),
            }],
            is_error: if res.get("status").and_then(|s| s.as_str()) == Some("error") {
                Some(true)
            } else {
                None
            },
        }),
        Err(e) => {
            warn!(error = %e, "NexCore bridge failure");
            Some(ToolCallResult {
                content: vec![ContentBlock::Text {
                    text: format!("NexCore bridge error: {}", e),
                }],
                is_error: Some(true),
            })
        }
    }
}

fn find_nexcore_mcp() -> Option<String> {
    if let Ok(env) = std::env::var("NEXCORE_MCP_BINARY") {
        return Some(env);
    }
    
    let home = std::env::var("HOME").unwrap_or_default();
    let paths = [
        "/usr/local/bin/nexcore-mcp",
        &format!("{}/Projects/Active/nexcore/target/release/nexcore-mcp", home),
        &format!("{}/.cargo/bin/nexcore-mcp", home),
    ];

    for path in paths {
        if std::path::Path::new(path).exists() {
            return Some(path.to_string());
        }
    }
    None
}

fn call_mcp(binary: &str, tool_name: &str, args: &Value) -> anyhow::Result<Value> {
    // Strip prefix: adventure_nexvigilant_com_list -> list
    let marker = "_nexvigilant_com_";
    let mcp_tool = if let Some(idx) = tool_name.find(marker) {
        &tool_name[idx + marker.len()..]
    } else {
        tool_name
    };

    let mut child = Command::new(binary)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;

    let mut stdin = child.stdin.take().ok_or_else(|| anyhow::anyhow!("Failed to open stdin"))?;
    let mut stdout = child.stdout.take().ok_or_else(|| anyhow::anyhow!("Failed to open stdout"))?;

    // MCP Handshake
    // 1. Initialize
    let init_req = json!({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "nexvigilant-station-rust-bridge", "version": "1.0.0"},
        }
    });
    writeln!(stdin, "{}", serde_json::to_string(&init_req)?)?;

    // Read init response (wait for id: 1)
    let _init_res = read_json_rpc(&mut stdout, 1)?;

    // 2. Initialized notification
    let initialized_notif = json!({
        "jsonrpc": "2.0", "method": "notifications/initialized"
    });
    writeln!(stdin, "{}", serde_json::to_string(&initialized_notif)?)?;

    // 3. tools/call
    let call_req = json!({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {
            "name": mcp_tool,
            "arguments": args
        }
    });
    writeln!(stdin, "{}", serde_json::to_string(&call_req)?)?;

    // Read call response (wait for id: 2)
    let call_res = read_json_rpc(&mut stdout, 2)?;

    // Extract result
    if let Some(error) = call_res.get("error") {
        return Ok(json!({
            "status": "error",
            "message": error.get("message").and_then(|v| v.as_str()).unwrap_or("Unknown MCP error"),
            "code": error.get("code")
        }));
    }

    let result = call_res.get("result").ok_or_else(|| anyhow::anyhow!("Missing result field"))?;
    let content = result.get("content").and_then(|v| v.as_array()).ok_or_else(|| anyhow::anyhow!("Missing content array"))?;
    
    if content.is_empty() {
        return Ok(json!({ "status": "ok", "message": "No content returned" }));
    }

    let text = content[0].get("text").and_then(|v| v.as_str()).ok_or_else(|| anyhow::anyhow!("Missing text in content"))?;
    
    // Many nexcore tools return JSON as a string in the text field
    if let Ok(json_inner) = serde_json::from_str::<Value>(text) {
        Ok(json_inner)
    } else {
        Ok(json!({ "status": "ok", "raw": text }))
    }
}

fn read_json_rpc(reader: &mut dyn Read, expected_id: i64) -> anyhow::Result<Value> {
    use std::io::BufRead;
    let mut buf_reader = std::io::BufReader::new(reader);
    let mut line = String::new();
    
    // Polling with timeout (simplification)
    for _ in 0..5000 { // loop a few times
        line.clear();
        if buf_reader.read_line(&mut line)? == 0 {
            break;
        }
        if let Ok(val) = serde_json::from_str::<Value>(&line)
            && val.get("id").and_then(|v| v.as_i64()) == Some(expected_id)
        {
            return Ok(val);
        }
    }
    Err(anyhow::anyhow!("Timeout or protocol error waiting for RPC id {}", expected_id))
}
