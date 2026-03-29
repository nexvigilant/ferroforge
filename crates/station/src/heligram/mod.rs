//! Heligram — Rust-native handler for NexVigilant Station.
//!
//! Routes `heligram_nexvigilant_com_*` tool calls to the rsk heligram runtime.
//! Loads heligrams from the rsk/heligrams directory.

use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

const HELIGRAM_DIR: &str = "rsk/heligrams";

/// Resolve the rsk binary path. Checks RSK_BINARY env var first,
/// then falls back to ~/Projects/rsk-core/target/release/rsk, then bare "rsk".
fn rsk_binary() -> String {
    if let Ok(path) = std::env::var("RSK_BINARY") {
        return path;
    }
    if let Ok(home) = std::env::var("HOME") {
        let fallback = format!("{home}/Projects/rsk-core/target/release/rsk");
        if std::path::Path::new(&fallback).exists() {
            return fallback;
        }
    }
    "rsk".to_string()
}

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let suffix = tool_name.strip_prefix("heligram_nexvigilant_com_")?;

    info!(tool = %suffix, "Heligram handler");

    let result = match suffix {
        "run" => handle_run(args),
        "test" => handle_test(args),
        "list" => handle_list(),
        "test_all" | "test-all" => handle_test_all(),
        _ => return None,
    };

    Some(ToolCallResult {
        content: vec![ContentBlock::Text {
            text: serde_json::to_string_pretty(&result).unwrap_or_default(),
        }],
        is_error: if result.get("status").and_then(|v| v.as_str()) == Some("error") {
            Some(true)
        } else {
            None
        },
    })
}

fn handle_run(args: &Value) -> Value {
    let name = match args.get("name").and_then(|v| v.as_str()) {
        Some(n) => n,
        None => return err("missing required parameter: name"),
    };

    let input_val = args.get("input").cloned().unwrap_or(json!({}));

    // Shell out to rsk binary for now — keeps the handler simple and
    // avoids linking rsk as a library dependency
    let input_str = serde_json::to_string(&input_val).unwrap_or_default();

    // Find the heligram file
    let heligram_path = find_heligram(name);
    let path = match heligram_path {
        Some(p) => p,
        None => return err(&format!("heligram not found: {name}. Use heligram_nexvigilant_com_list to see available heligrams.")),
    };

    match std::process::Command::new(rsk_binary())
        .args(["heligram", "run", &path, "-i", &input_str])
        .output()
    {
        Ok(output) => {
            let stdout = String::from_utf8_lossy(&output.stdout);
            match serde_json::from_str::<Value>(&stdout) {
                Ok(mut v) => {
                    if let Some(obj) = v.as_object_mut() {
                        obj.insert("status".to_string(), json!("ok"));
                    }
                    v
                }
                Err(_) => err(&format!("failed to parse rsk output: {stdout}")),
            }
        }
        Err(e) => err(&format!("failed to run rsk: {e}. Ensure rsk binary is in PATH.")),
    }
}

fn handle_test(args: &Value) -> Value {
    let name = match args.get("name").and_then(|v| v.as_str()) {
        Some(n) => n,
        None => return err("missing required parameter: name"),
    };

    let path = match find_heligram(name) {
        Some(p) => p,
        None => return err(&format!("heligram not found: {name}")),
    };

    match std::process::Command::new(rsk_binary())
        .args(["heligram", "test", &path])
        .output()
    {
        Ok(output) => {
            let stdout = String::from_utf8_lossy(&output.stdout);
            match serde_json::from_str::<Value>(&stdout) {
                Ok(mut v) => {
                    if let Some(obj) = v.as_object_mut() {
                        obj.insert("status".to_string(), json!("ok"));
                    }
                    v
                }
                Err(_) => err(&format!("parse error: {stdout}")),
            }
        }
        Err(e) => err(&format!("failed to run rsk: {e}")),
    }
}

fn handle_list() -> Value {
    match std::process::Command::new(rsk_binary())
        .args(["heligram", "list", HELIGRAM_DIR])
        .output()
    {
        Ok(output) => {
            let stdout = String::from_utf8_lossy(&output.stdout);
            match serde_json::from_str::<Value>(&stdout) {
                Ok(mut v) => {
                    if let Some(obj) = v.as_object_mut() {
                        obj.insert("status".to_string(), json!("ok"));
                    }
                    v
                }
                Err(_) => err(&format!("parse error: {stdout}")),
            }
        }
        Err(e) => err(&format!("failed to run rsk: {e}")),
    }
}

fn handle_test_all() -> Value {
    match std::process::Command::new(rsk_binary())
        .args(["heligram", "test-all", HELIGRAM_DIR])
        .output()
    {
        Ok(output) => {
            let stdout = String::from_utf8_lossy(&output.stdout);
            match serde_json::from_str::<Value>(&stdout) {
                Ok(mut v) => {
                    if let Some(obj) = v.as_object_mut() {
                        obj.insert("status".to_string(), json!("ok"));
                    }
                    v
                }
                Err(_) => err(&format!("parse error: {stdout}")),
            }
        }
        Err(e) => err(&format!("failed to run rsk: {e}")),
    }
}

fn find_heligram(name: &str) -> Option<String> {
    // Try direct path first
    let direct = format!("{HELIGRAM_DIR}/{name}.yaml");
    if std::path::Path::new(&direct).exists() {
        return Some(direct);
    }
    // Try home-relative
    let home = std::env::var("HOME").unwrap_or_default();
    let home_path = format!("{home}/Projects/rsk-core/rsk/heligrams/{name}.yaml");
    if std::path::Path::new(&home_path).exists() {
        return Some(home_path);
    }
    None
}

fn err(msg: &str) -> Value {
    json!({ "status": "error", "message": msg })
}
