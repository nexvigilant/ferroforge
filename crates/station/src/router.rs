use serde_json::Value;
use tracing::info;

use crate::config::{ConfigRegistry, HubConfig, ToolDef};
use crate::protocol::{ContentBlock, ToolCallResult};

/// Route a tool call to the appropriate handler.
pub fn route_tool_call(
    registry: &ConfigRegistry,
    tool_name: &str,
    arguments: &Value,
) -> ToolCallResult {
    match registry.find_tool(tool_name) {
        Some((config, tool)) => execute_tool(config, tool, arguments),
        None => ToolCallResult {
            content: vec![ContentBlock::Text {
                text: format!("Unknown tool: {tool_name}"),
            }],
            is_error: Some(true),
        },
    }
}

/// Execute a resolved tool.
fn execute_tool(config: &HubConfig, tool: &ToolDef, arguments: &Value) -> ToolCallResult {
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

    // Default: return structured info about what would be called
    let result = serde_json::json!({
        "domain": config.domain,
        "tool": tool.name,
        "arguments": arguments,
        "status": "stub",
        "message": format!(
            "Tool '{}' on domain '{}' is registered but has no implementation yet. \
             Add a stub_response to the config or implement a handler.",
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
