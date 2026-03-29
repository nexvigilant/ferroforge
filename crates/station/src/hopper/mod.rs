//! # Hopper Engine — Easter Bunny Technology
//!
//! Hops between Station tools at native speed. No HTTP round-trips.
//! The bunny carries the basket (context) forward through each nest (tool).
//!
//! ```text
//! Nest 1 (RxNav)  →  Nest 2 (FAERS)  →  Nest 3 (PRR)  →  Nest 4 (Naranjo)
//!   🥚 rxcui         🥚 total_reports    🥚 prr=71.4      🥚 score=7
//!   ↓ basket          ↓ basket            ↓ basket          ↓ basket
//! ```
//!
//! Chain definitions: `relays/*.yaml` (same format as relay.py).
//! Execution: in-process function calls for Rust-native tools,
//! subprocess dispatch for proxy tools.

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::HashMap;
use std::path::Path;
use std::time::Instant;

use crate::config::ConfigRegistry;
use crate::protocol::{ContentBlock, ToolCallResult};

/// A single nest the bunny visits.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Hop {
    /// Station tool name (e.g., "calculate_nexvigilant_com_compute_prr")
    pub tool: String,
    /// Arguments — may contain $var references to basket values
    #[serde(default)]
    pub args: HashMap<String, Value>,
    /// Values to extract from the result into the basket
    #[serde(default)]
    pub extract: HashMap<String, String>,
    /// Continue hopping even if this nest errors
    #[serde(default)]
    pub continue_on_error: bool,
}

/// A chain of hops — the bunny's route.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Chain {
    pub name: String,
    #[serde(default)]
    pub description: String,
    pub hops: Vec<Hop>,
}

/// The basket — accumulated context carried between hops.
pub type Basket = HashMap<String, Value>;

/// Result of a single hop.
#[derive(Debug, Serialize)]
pub struct HopResult {
    pub hop: usize,
    pub tool: String,
    pub status: String,
    pub latency_ms: u64,
    pub extracted: HashMap<String, Value>,
    pub error: Option<String>,
}

/// Result of a full chain execution.
#[derive(Debug, Serialize)]
pub struct ChainResult {
    pub chain: String,
    pub hops_total: usize,
    pub hops_executed: usize,
    pub hops_passed: usize,
    pub fidelity: f64,
    pub total_ms: u64,
    pub basket: Basket,
    pub results: Vec<HopResult>,
}

/// Load a chain from YAML (or JSON fallback).
pub fn load_chain(path: &Path) -> Result<Chain, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| format!("Failed to read {}: {e}", path.display()))?;

    // Try JSON first (faster), fall back to basic YAML parsing
    if let Ok(chain) = serde_json::from_str::<Chain>(&text) {
        return Ok(chain);
    }

    // Basic YAML: use serde_yaml if available, otherwise manual parse
    parse_yaml_chain(&text)
}

/// Execute a chain through the Station's tool router.
pub fn execute(
    chain: &Chain,
    initial_vars: Basket,
    registry: &ConfigRegistry,
    station_root: &str,
) -> ChainResult {
    let mut basket = initial_vars;
    let mut results = Vec::new();
    let chain_start = Instant::now();

    for (i, hop) in chain.hops.iter().enumerate() {
        let hop_start = Instant::now();

        // Substitute $var references in args
        let resolved_args = substitute_vars(&hop.args, &basket);

        // Route the tool call through the Station router
        let tool_result = crate::router::route_tool_call_for_hopper(
            registry,
            &hop.tool,
            &resolved_args,
            station_root,
        );

        let latency_ms = hop_start.elapsed().as_millis() as u64;

        // Parse the result
        let (status, extracted, error) = parse_tool_result(&tool_result, &hop.extract);

        // Drop extracted eggs into the basket
        for (key, val) in &extracted {
            basket.insert(key.clone(), val.clone());
        }

        results.push(HopResult {
            hop: i + 1,
            tool: hop.tool.clone(),
            status: status.clone(),
            latency_ms,
            extracted,
            error: error.clone(),
        });

        // Stop on error unless continue_on_error
        if status == "error" && !hop.continue_on_error {
            break;
        }
    }

    let total_ms = chain_start.elapsed().as_millis() as u64;
    let passed = results.iter().filter(|r| r.status != "error").count();
    let fidelity = if results.is_empty() {
        0.0
    } else {
        passed as f64 / results.len() as f64
    };

    ChainResult {
        chain: chain.name.clone(),
        hops_total: chain.hops.len(),
        hops_executed: results.len(),
        hops_passed: passed,
        fidelity,
        total_ms,
        basket,
        results,
    }
}

/// Substitute $var references in hop arguments with basket values.
fn substitute_vars(args: &HashMap<String, Value>, basket: &Basket) -> Value {
    let mut resolved = serde_json::Map::new();

    for (key, val) in args {
        match val {
            Value::String(s) if s.starts_with('$') => {
                let var_name = &s[1..];
                if let Some(basket_val) = basket.get(var_name) {
                    resolved.insert(key.clone(), basket_val.clone());
                } else {
                    resolved.insert(key.clone(), val.clone());
                }
            }
            _ => {
                resolved.insert(key.clone(), val.clone());
            }
        }
    }

    Value::Object(resolved)
}

/// Extract values from a tool result using dot-notation paths.
fn parse_tool_result(
    result: &ToolCallResult,
    extract: &HashMap<String, String>,
) -> (String, HashMap<String, Value>, Option<String>) {
    // Get the text content from the tool result
    let text = result
        .content
        .first()
        .map(|c| match c {
            ContentBlock::Text { text } => text.clone(),
        })
        .unwrap_or_default();

    // Parse as JSON
    let parsed: Value = match serde_json::from_str(&text) {
        Ok(v) => v,
        Err(_) => {
            return (
                "error".to_string(),
                HashMap::new(),
                Some(format!("Failed to parse tool result as JSON: {}", &text[..text.len().min(100)])),
            );
        }
    };

    let status = parsed
        .get("status")
        .and_then(|s| s.as_str())
        .unwrap_or("ok")
        .to_string();

    let error = if status == "error" {
        parsed.get("message").and_then(|m| m.as_str()).map(|s| s.to_string())
    } else {
        None
    };

    // Extract values using dot-notation paths
    let mut extracted = HashMap::new();
    for (var_name, path) in extract {
        if let Some(val) = resolve_path(&parsed, path) {
            extracted.insert(var_name.clone(), val);
        }
    }

    (status, extracted, error)
}

/// Resolve a dot-notation path with array indexing.
/// e.g., "scores.PRR" or "results[0].rxcui"
fn resolve_path(data: &Value, path: &str) -> Option<Value> {
    let mut current = data.clone();

    for part in path.split('.') {
        // Check for array index: "results[0]"
        if let Some(bracket_pos) = part.find('[') {
            let key = &part[..bracket_pos];
            let idx_str = &part[bracket_pos + 1..part.len() - 1];
            let idx: usize = idx_str.parse().ok()?;

            current = current.get(key)?.clone();
            current = current.get(idx)?.clone();
        } else {
            current = current.get(part)?.clone();
        }
    }

    Some(current)
}

/// Parse a basic YAML chain definition.
fn parse_yaml_chain(text: &str) -> Result<Chain, String> {
    let mut chain = Chain {
        name: String::new(),
        description: String::new(),
        hops: Vec::new(),
    };

    let mut current_hop: Option<Hop> = None;
    let mut in_args = false;
    let mut in_extract = false;

    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }

        if trimmed.starts_with("name:") {
            chain.name = trimmed[5..].trim().trim_matches('"').trim_matches('\'').to_string();
        } else if trimmed.starts_with("description:") {
            chain.description = trimmed[12..].trim().trim_matches('"').trim_matches('\'').to_string();
        } else if trimmed == "hops:" {
            continue;
        } else if trimmed.starts_with("- tool:") {
            if let Some(hop) = current_hop.take() {
                chain.hops.push(hop);
            }
            current_hop = Some(Hop {
                tool: trimmed[7..].trim().trim_matches('"').trim_matches('\'').to_string(),
                args: HashMap::new(),
                extract: HashMap::new(),
                continue_on_error: false,
            });
            in_args = false;
            in_extract = false;
        } else if let Some(ref mut hop) = current_hop {
            if trimmed.starts_with("continue_on_error:") {
                hop.continue_on_error = trimmed.contains("true");
                in_args = false;
                in_extract = false;
            } else if trimmed.starts_with("args:") {
                in_args = true;
                in_extract = false;
                // Try inline JSON
                let inline = trimmed[5..].trim();
                if inline.starts_with('{') {
                    if let Ok(map) = serde_json::from_str::<HashMap<String, Value>>(
                        &inline.replace('\'', "\""),
                    ) {
                        hop.args = map;
                        in_args = false;
                    }
                }
            } else if trimmed.starts_with("extract:") {
                in_extract = true;
                in_args = false;
                let inline = trimmed[8..].trim();
                if inline.starts_with('{') {
                    // Parse { key: "path" } format
                    for cap in inline.split(',') {
                        let parts: Vec<&str> = cap.split(':').collect();
                        if parts.len() == 2 {
                            let k = parts[0].trim().trim_matches(|c: char| !c.is_alphanumeric() && c != '_');
                            let v = parts[1].trim().trim_matches(|c: char| !c.is_alphanumeric() && c != '.' && c != '[' && c != ']' && c != '_');
                            hop.extract.insert(k.to_string(), v.to_string());
                        }
                    }
                    in_extract = false;
                }
            } else if in_args && trimmed.contains(':') {
                let parts: Vec<&str> = trimmed.splitn(2, ':').collect();
                if parts.len() == 2 {
                    let k = parts[0].trim().to_string();
                    let v_str = parts[1].trim().trim_matches('"').trim_matches('\'');
                    let v: Value = if v_str == "true" {
                        Value::Bool(true)
                    } else if v_str == "false" {
                        Value::Bool(false)
                    } else if let Ok(n) = v_str.parse::<i64>() {
                        Value::Number(n.into())
                    } else if let Ok(n) = v_str.parse::<f64>() {
                        json!(n)
                    } else if v_str.starts_with('$') {
                        Value::String(v_str.to_string())
                    } else {
                        Value::String(v_str.to_string())
                    };
                    hop.args.insert(k, v);
                }
            } else if in_extract && trimmed.contains(':') {
                let parts: Vec<&str> = trimmed.splitn(2, ':').collect();
                if parts.len() == 2 {
                    let k = parts[0].trim().to_string();
                    let v = parts[1].trim().trim_matches('"').trim_matches('\'').to_string();
                    hop.extract.insert(k, v);
                }
            }
        }
    }

    if let Some(hop) = current_hop {
        chain.hops.push(hop);
    }

    if chain.hops.is_empty() {
        return Err("No hops found in chain definition".to_string());
    }

    Ok(chain)
}
