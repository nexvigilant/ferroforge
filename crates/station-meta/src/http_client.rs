//! HTTP transport for `StationClient` — forward execute requests to a Station
//! server over JSON-RPC HTTP. Feature-gated behind `http` so consumers that
//! only need discovery or use a local transport don't pull ureq.
//!
//! Wire protocol (confirmed against https://mcp.nexvigilant.com/rpc on 2026-04-16):
//!
//! ```text
//! POST {base_url}/rpc   Content-Type: application/json
//!
//! Request:  {"jsonrpc":"2.0","id":N,"method":"tools/call",
//!            "params":{"name":"{flat_mcp_name}","arguments":{...}}}
//!
//! Success:  {"jsonrpc":"2.0","id":N,
//!            "result":{"content":[{"type":"text","text":"<tool json>"}],
//!                      "isError": false|null}}
//!
//! Error:    {"jsonrpc":"2.0","id":N,
//!            "error":{"code":-32xxx,"message":"..."}}
//! ```

use anyhow::Result;
use serde_json::Value;
use std::time::Duration;

use crate::execute::{ExecutionRequest, ExecutionResult, StationClient};
use crate::mcp_naming::build_mcp_tool_name;

/// Default endpoint for the NexVigilant Station Cloud Run deployment.
pub const DEFAULT_BASE_URL: &str = "https://mcp.nexvigilant.com";

/// Default timeout for a single tool call. Live FAERS queries can be slow
/// (we've measured 3s P99). Defaulting higher than needed beats aborting
/// legitimate queries under transient latency.
pub const DEFAULT_TIMEOUT: Duration = Duration::from_secs(30);

/// HTTP-backed `StationClient` — forwards execute requests to a remote Station.
pub struct HttpStationClient {
    agent: ureq::Agent,
    base_url: String,
}

impl HttpStationClient {
    /// Create a new client targeting the given base URL (no trailing slash).
    /// Timeout applies per-request, not cumulative.
    #[must_use]
    pub fn new(base_url: impl Into<String>, timeout: Duration) -> Self {
        let agent = ureq::AgentBuilder::new()
            .timeout(timeout)
            .user_agent(concat!("station-meta/", env!("CARGO_PKG_VERSION")))
            .build();
        Self {
            agent,
            base_url: base_url.into().trim_end_matches('/').to_string(),
        }
    }

    /// Client targeting the default Cloud Run endpoint with default timeout.
    #[must_use]
    pub fn default_prod() -> Self {
        Self::new(DEFAULT_BASE_URL, DEFAULT_TIMEOUT)
    }

    // Tool-name construction delegated to `crate::mcp_naming::build_mcp_tool_name`.
    // Both transports (HTTP + local Router) use the same shared helper.
}

impl StationClient for HttpStationClient {
    fn call(&self, req: &ExecutionRequest) -> Result<ExecutionResult> {
        let mcp_name = build_mcp_tool_name(&req.config, &req.tool);
        let url = format!("{}/rpc", self.base_url);

        let payload = serde_json::json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": { "name": mcp_name, "arguments": req.params },
        });

        let resp = match self.agent.post(&url).send_json(payload) {
            Ok(r) => r,
            Err(ureq::Error::Status(code, r)) => {
                let body = r.into_string().unwrap_or_default();
                return Ok(ExecutionResult::error(format!(
                    "HTTP {code}: {body}"
                )));
            }
            Err(e) => {
                return Ok(ExecutionResult::error(format!("transport error: {e}")));
            }
        };

        let body: Value = resp.into_json()?;

        // JSON-RPC error envelope
        if let Some(err) = body.get("error") {
            let msg = err
                .get("message")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown JSON-RPC error");
            return Ok(ExecutionResult::error(format!("jsonrpc error: {msg}")));
        }

        // Success envelope: result.content[0].text is a JSON string
        let result = body.get("result").cloned().unwrap_or(Value::Null);
        let is_tool_error = result
            .get("isError")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);

        let payload: Value = result
            .get("content")
            .and_then(|c| c.as_array())
            .and_then(|arr| arr.first())
            .and_then(|first| first.get("text"))
            .and_then(|t| t.as_str())
            .map_or(Value::Null, |s| {
                serde_json::from_str::<Value>(s).unwrap_or(Value::String(s.to_string()))
            });

        if is_tool_error {
            let msg = payload
                .get("error")
                .and_then(|v| v.as_str())
                .map(str::to_string)
                .unwrap_or_else(|| payload.to_string());
            return Ok(ExecutionResult::error(msg));
        }

        Ok(ExecutionResult::ok(payload))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Tool-name construction tests live in `crate::mcp_naming::tests`.
    // This module only tests HTTP-client-specific behavior.

    #[test]
    fn trims_trailing_slash_from_base_url() {
        let c = HttpStationClient::new("https://example.com/", Duration::from_secs(5));
        assert_eq!(c.base_url, "https://example.com");
    }

    #[test]
    fn default_prod_hits_cloud_run_url() {
        let c = HttpStationClient::default_prod();
        assert_eq!(c.base_url, "https://mcp.nexvigilant.com");
    }
}
