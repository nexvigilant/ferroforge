//! API Key authentication for NexVigilant Station.
//!
//! Education is free — meta-tools (directory, capabilities, chart_course) require
//! no authentication. All domain tool calls require a valid API key.
//!
//! Keys are loaded from `NEXVIGILANT_API_KEYS` env var (comma-separated).
//! If the env var is not set, auth is disabled (development mode).
//!
//! Key format: `nv_` prefix + 32 hex chars (e.g., `nv_a1b2c3d4e5f6...`).

use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;
use tracing::info;

/// Tools that are always free — education/discovery surface.
const FREE_TOOLS: &[&str] = &[
    "nexvigilant_directory",
    "nexvigilant_capabilities",
    "nexvigilant_chart_course",
    "nexvigilant_station_health",
    "nexvigilant_ring_health",
];

/// API key gate for station access control.
#[derive(Debug, Clone)]
pub struct ApiKeyGate {
    /// SHA-256 hashes of valid API keys. Hashing normalizes length for
    /// constant-time comparison and avoids keeping plaintext keys in memory.
    /// `None` = auth disabled (dev mode).
    key_hashes: Option<Vec<[u8; 32]>>,
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

/// Hash a key with SHA-256 to normalize length for constant-time comparison.
fn hash_key(key: &str) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(key.as_bytes());
    hasher.finalize().into()
}

impl ApiKeyGate {
    /// Create an auth gate with explicit keys (for testing).
    /// Pass `None` for dev mode (all allowed), `Some(vec)` for enforced mode.
    pub fn new(valid_keys: Option<Vec<String>>) -> Self {
        Self {
            key_hashes: valid_keys.map(|keys| keys.iter().map(|k| hash_key(k)).collect()),
        }
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
                let hashes = keys.iter().map(|k| hash_key(k)).collect();
                Self {
                    key_hashes: Some(hashes),
                }
            }
            _ => {
                info!("API key gate disabled (NEXVIGILANT_API_KEYS not set — dev mode)");
                Self { key_hashes: None }
            }
        }
    }

    /// Check whether a tool call is authorized.
    ///
    /// - Free tools (meta-tools) and public config tools always pass.
    /// - Private config tools require a valid API key.
    /// - If no keys configured → always pass (dev mode).
    ///
    /// Key comparison is constant-time: both the candidate and stored keys
    /// are SHA-256 hashed, then compared with `subtle::ConstantTimeEq` to
    /// prevent timing side-channel attacks.
    pub fn check(&self, auth_header: Option<&str>, tool_name: &str) -> AuthResult {
        // Meta-tools are always free — education surface
        if FREE_TOOLS.contains(&tool_name) {
            return AuthResult::Allowed;
        }

        // Dev mode — no keys configured, all tools open
        let Some(key_hashes) = &self.key_hashes else {
            return AuthResult::Allowed;
        };

        self.validate_token(auth_header, key_hashes)
    }

    /// Check whether a tool call is authorized using config privacy flag.
    ///
    /// - Public tools (is_private=false) always pass.
    /// - Private tools require a valid API key.
    /// - Dev mode (no keys) → all tools open.
    pub fn check_with_privacy(&self, auth_header: Option<&str>, is_private: bool) -> AuthResult {
        // Public tools are always free
        if !is_private {
            return AuthResult::Allowed;
        }

        // Dev mode — no keys configured, all tools open
        let Some(key_hashes) = &self.key_hashes else {
            return AuthResult::Allowed;
        };

        self.validate_token(auth_header, key_hashes)
    }

    /// Validate a Bearer token against stored key hashes.
    fn validate_token(&self, auth_header: Option<&str>, key_hashes: &[[u8; 32]]) -> AuthResult {
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

        // Constant-time comparison via SHA-256 hash + subtle::ConstantTimeEq.
        // Hashing normalizes key length (prevents length-leak timing).
        // ConstantTimeEq prevents byte-position timing leaks.
        let candidate_hash = hash_key(token);
        let matched = key_hashes
            .iter()
            .any(|stored| candidate_hash.ct_eq(stored).into());

        if matched {
            AuthResult::Allowed
        } else {
            AuthResult::InvalidKey
        }
    }

    /// Check if the given auth header contains a valid key.
    /// Used by tools/list to determine which tools to show.
    pub fn is_authenticated(&self, auth_header: Option<&str>) -> bool {
        let Some(key_hashes) = &self.key_hashes else {
            return true; // dev mode — show everything
        };
        matches!(self.validate_token(auth_header, key_hashes), AuthResult::Allowed)
    }

    /// Check if auth is enabled (keys are configured).
    pub fn is_enabled(&self) -> bool {
        self.key_hashes.is_some()
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
            "message": "This tool requires authentication. Provide an API key via Authorization: Bearer nv_... header. Start with nexvigilant_chart_course (free, no auth) to get guided workflows. Other free tools: nexvigilant_directory, nexvigilant_capabilities, nexvigilant_ring_health.",
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
