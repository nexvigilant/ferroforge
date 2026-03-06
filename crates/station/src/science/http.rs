//! Shared HTTP client utilities for science domain handlers.

use serde_json::Value;
use tracing::warn;

const USER_AGENT: &str = "NexVigilantStation/1.0 (science; https://nexvigilant.com)";
const TIMEOUT_SECS: u64 = 15;

/// GET request returning parsed JSON, or an error object on failure.
pub fn get_json(url: &str) -> Value {
    match ureq::get(url)
        .set("Accept", "application/json")
        .set("User-Agent", USER_AGENT)
        .timeout(std::time::Duration::from_secs(TIMEOUT_SECS))
        .call()
    {
        Ok(resp) => match resp.into_json::<Value>() {
            Ok(v) => v,
            Err(e) => {
                warn!(url, error = %e, "JSON parse failed");
                serde_json::json!({"error": e.to_string()})
            }
        },
        Err(e) => {
            warn!(url, error = %e, "HTTP request failed");
            serde_json::json!({"error": e.to_string()})
        }
    }
}

/// POST request with JSON body, returning parsed JSON.
pub fn post_json(url: &str, body: &Value) -> Value {
    match ureq::post(url)
        .set("Content-Type", "application/json")
        .set("Accept", "application/json")
        .set("User-Agent", USER_AGENT)
        .timeout(std::time::Duration::from_secs(TIMEOUT_SECS))
        .send_json(body.clone())
    {
        Ok(resp) => match resp.into_json::<Value>() {
            Ok(v) => v,
            Err(e) => {
                warn!(url, error = %e, "JSON parse failed");
                serde_json::json!({"error": e.to_string()})
            }
        },
        Err(e) => {
            warn!(url, error = %e, "HTTP POST failed");
            serde_json::json!({"error": e.to_string()})
        }
    }
}
