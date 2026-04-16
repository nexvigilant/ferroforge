//! Execution: forward `(config, tool, params)` to an HTTP JSON-RPC endpoint.
//!
//! This module defines the **transport contract** as a trait. Concrete
//! clients (production: `reqwest`, tests: mock) implement it. The meta-tool
//! layer is transport-agnostic so we can prototype without pulling an HTTP
//! dependency into the workspace just for this wrapper.

use anyhow::Result;
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Request to execute one tool at the Station endpoint.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionRequest {
    /// Config stem (e.g. `"openfda"`, `"rxnav"`).
    pub config: String,
    /// Tool name within that config.
    pub tool: String,
    /// Parameters as a JSON object; keys match `ToolParameter::name`.
    pub params: Value,
}

/// Result from a Station execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionResult {
    /// `"ok"` on success, `"error"` otherwise.
    pub status: String,
    /// Tool output on success.
    #[serde(default)]
    pub result: Option<Value>,
    /// Error message on failure.
    #[serde(default)]
    pub error: Option<String>,
}

impl ExecutionResult {
    /// Construct a success result.
    #[must_use]
    pub fn ok(result: Value) -> Self {
        Self {
            status: "ok".to_string(),
            result: Some(result),
            error: None,
        }
    }

    /// Construct an error result.
    #[must_use]
    pub fn error(msg: impl Into<String>) -> Self {
        Self {
            status: "error".to_string(),
            result: None,
            error: Some(msg.into()),
        }
    }

    /// True iff `status == "ok"`.
    #[must_use]
    pub fn is_ok(&self) -> bool {
        self.status == "ok"
    }
}

/// Abstract transport — implemented by the real HTTP client and by test mocks.
///
/// Kept synchronous for prototype simplicity; upgrade to async in the
/// production wiring step once the transport crate is chosen.
pub trait StationClient {
    /// Execute one request against the Station endpoint.
    fn call(&self, req: &ExecutionRequest) -> Result<ExecutionResult>;
}

/// Execute one tool via the supplied client.
///
/// This is a thin pass-through that gives callers a single named entry point,
/// symmetric with `discover::discover`.
pub fn execute(client: &dyn StationClient, req: ExecutionRequest) -> Result<ExecutionResult> {
    client.call(&req)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    /// Test mock that records the last request and returns a canned result.
    struct MockClient {
        response: ExecutionResult,
        last: RefCell<Option<ExecutionRequest>>,
    }

    impl MockClient {
        fn new(response: ExecutionResult) -> Self {
            Self {
                response,
                last: RefCell::new(None),
            }
        }
    }

    impl StationClient for MockClient {
        fn call(&self, req: &ExecutionRequest) -> Result<ExecutionResult> {
            *self.last.borrow_mut() = Some(req.clone());
            Ok(self.response.clone())
        }
    }

    #[test]
    fn execute_forwards_request_and_returns_ok() {
        let mock = MockClient::new(ExecutionResult::ok(serde_json::json!({"count": 3})));
        let req = ExecutionRequest {
            config: "openfda".into(),
            tool: "search_adverse_events".into(),
            params: serde_json::json!({"drug_name": "metformin", "limit": 3}),
        };
        let out = execute(&mock, req.clone()).expect("execute");
        assert!(out.is_ok());
        assert_eq!(out.result.and_then(|v| v.get("count").cloned()), Some(serde_json::json!(3)));

        let last = mock.last.borrow().clone().expect("recorded");
        assert_eq!(last.config, "openfda");
        assert_eq!(last.tool, "search_adverse_events");
    }

    #[test]
    fn execute_propagates_error_status() {
        let mock = MockClient::new(ExecutionResult::error("rate limited"));
        let req = ExecutionRequest {
            config: "openfda".into(),
            tool: "search_adverse_events".into(),
            params: serde_json::json!({}),
        };
        let out = execute(&mock, req).expect("transport ok");
        assert!(!out.is_ok());
        assert_eq!(out.error.as_deref(), Some("rate limited"));
    }

    #[test]
    fn result_is_ok_discriminates_status() {
        assert!(ExecutionResult::ok(serde_json::json!({})).is_ok());
        assert!(!ExecutionResult::error("boom").is_ok());
    }
}
