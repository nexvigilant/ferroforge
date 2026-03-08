//! API Key authentication for NexVigilant Station.
//!
//! Education is free — meta-tools (directory, capabilities, chart_course) require
//! no authentication. All domain tool calls require a valid API key.
//!
//! Keys are loaded from `NEXVIGILANT_API_KEYS` env var (comma-separated).
//! If the env var is not set, auth is disabled (development mode).
//!
//! Key format: `nv_` prefix + 32 hex chars (e.g., `nv_a1b2c3d4e5f6...`).

use tracing::info;

/// Tools that are always free — education/discovery surface.
const FREE_TOOLS: &[&str] = &[
    "nexvigilant_directory",
    "nexvigilant_capabilities",
    "nexvigilant_chart_course",
];

/// API key gate for station access control.
#[derive(Debug, Clone)]
pub struct ApiKeyGate {
    /// Valid API keys. `None` = auth disabled (dev mode).
    valid_keys: Option<Vec<String>>,
}

/// Result of an auth check.
#[derive(Debug)]
pub enum AuthResult {
    /// Call is allowed (key valid or tool is free).
    Allowed,
    /// Tool requires auth but no key was provided.
    KeyRequired,
    /// Key was provided but is invalid.
    InvalidKey,
}

impl ApiKeyGate {
    /// Create an auth gate with explicit keys (for testing).
    /// Pass `None` for dev mode (all allowed), `Some(vec)` for enforced mode.
    pub fn new(valid_keys: Option<Vec<String>>) -> Self {
        Self { valid_keys }
    }

    /// Load API keys from `NEXVIGILANT_API_KEYS` env var.
    /// If not set, returns a gate that allows everything (dev mode).
    pub fn from_env() -> Self {
        match std::env::var("NEXVIGILANT_API_KEYS") {
            Ok(keys_str) if !keys_str.is_empty() => {
                let keys: Vec<String> = keys_str
                    .split(',')
                    .map(|s| s.trim().to_string())
                    .filter(|s| !s.is_empty())
                    .collect();
                info!(key_count = keys.len(), "API key gate enabled");
                Self {
                    valid_keys: Some(keys),
                }
            }
            _ => {
                info!("API key gate disabled (NEXVIGILANT_API_KEYS not set — dev mode)");
                Self { valid_keys: None }
            }
        }
    }

    /// Check whether a tool call is authorized.
    ///
    /// - Free tools (meta-tools) always pass.
    /// - If no keys configured → always pass (dev mode).
    /// - Otherwise, requires valid `Authorization: Bearer nv_...` header.
    pub fn check(&self, auth_header: Option<&str>, tool_name: &str) -> AuthResult {
        // Meta-tools are always free — education surface
        if FREE_TOOLS.contains(&tool_name) {
            return AuthResult::Allowed;
        }

        // Dev mode — no keys configured
        let Some(valid_keys) = &self.valid_keys else {
            return AuthResult::Allowed;
        };

        // Extract Bearer token
        let Some(header) = auth_header else {
            return AuthResult::KeyRequired;
        };

        let token = if let Some(stripped) = header.strip_prefix("Bearer ") {
            stripped.trim()
        } else {
            header.trim()
        };

        if token.is_empty() {
            return AuthResult::KeyRequired;
        }

        // Constant-time comparison would be ideal, but for MVP:
        if valid_keys.iter().any(|k| k == token) {
            AuthResult::Allowed
        } else {
            AuthResult::InvalidKey
        }
    }

    /// Check if auth is enabled (keys are configured).
    pub fn is_enabled(&self) -> bool {
        self.valid_keys.is_some()
    }

    /// Check a tools/list request — always allowed, but annotates which tools need auth.
    /// Returns true (list is always free — tools themselves need auth to call).
    pub fn list_allowed(&self) -> bool {
        true
    }

    /// Check a tools/call JSON-RPC request. Extracts tool name from params.
    pub fn check_rpc(&self, auth_header: Option<&str>, params: Option<&serde_json::Value>) -> AuthResult {
        let tool_name = params
            .and_then(|p| p.get("name"))
            .and_then(|n| n.as_str())
            .unwrap_or("");

        self.check(auth_header, tool_name)
    }
}

/// Format a JSON error response for auth failures.
pub fn auth_error_json(result: &AuthResult) -> serde_json::Value {
    match result {
        AuthResult::KeyRequired => serde_json::json!({
            "error": "API key required",
            "message": "This tool requires authentication. Provide an API key via Authorization: Bearer nv_... header. Meta-tools (nexvigilant_directory, nexvigilant_capabilities, nexvigilant_chart_course) are free.",
            "docs": "https://nexvigilant.com/station/api-keys"
        }),
        AuthResult::InvalidKey => serde_json::json!({
            "error": "Invalid API key",
            "message": "The provided API key is not valid. Contact support@nexvigilant.com for access.",
            "docs": "https://nexvigilant.com/station/api-keys"
        }),
        AuthResult::Allowed => serde_json::json!({"error": "none"}),
    }
}
