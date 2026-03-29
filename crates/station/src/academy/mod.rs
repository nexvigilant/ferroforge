//! Academy Forge & NexCore Academy — Educational content generation and validation.
//!
//! Exposes academy-forge and nexcore-academy native logic to the Station.

use serde_json::{Value, json};
use tracing::info;
use std::path::Path;

use crate::protocol::{ContentBlock, ToolCallResult};

/// Try to handle an academy tool call.
pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    // 1. Check for academy-forge prefix
    if let Some(bare) = tool_name.strip_prefix("academy-forge_nexvigilant_com_") {
        let bare = bare.replace('_', "-");
        let result = handle_forge(&bare, args);
        return Some(render_result(tool_name, result));
    }

    // 2. Check for nexcore-academy prefix
    if let Some(bare) = tool_name.strip_prefix("nexcore-academy_nexvigilant_com_") {
        let bare = bare.replace('_', "-");
        let result = handle_academy(&bare, args);
        return Some(render_result(tool_name, result));
    }

    None
}

fn render_result(tool: &str, result: Value) -> ToolCallResult {
    info!(tool = tool, "Handled natively (academy)");
    ToolCallResult {
        content: vec![ContentBlock::Text {
            text: serde_json::to_string_pretty(&result).unwrap_or_default(),
        }],
        is_error: if result.get("status").and_then(|s| s.as_str()) == Some("error") {
            Some(true)
        } else {
            None
        },
    }
}

fn handle_forge(tool: &str, args: &Value) -> Value {
    match tool {
        "extract" => {
            let crate_path_str = args.get("crate").and_then(|v| v.as_str()).unwrap_or("");
            let crate_path = Path::new(crate_path_str);
            let domain = args.get("domain").and_then(|v| v.as_str());
            match academy_forge::extract_crate(crate_path, domain) {
                Ok(analysis) => json!({ "status": "ok", "analysis": analysis }),
                Err(e) => json!({ "status": "error", "message": e.to_string() }),
            }
        }
        "validate" => {
            let report = academy_forge::validate(args, None);
            json!({ "status": "ok", "report": report })
        }
        "scaffold" => {
            let domain_analysis_val = args.get("domain_analysis");
            let pathway_id = args.get("pathway_id").and_then(|v| v.as_str()).unwrap_or("scaffold-01");
            let title = args.get("title").and_then(|v| v.as_str()).unwrap_or("Untitled Pathway");
            let domain_name = args.get("domain").and_then(|v| v.as_str()).unwrap_or("vigilance");

            if let Some(da_val) = domain_analysis_val {
                match serde_json::from_value::<academy_forge::DomainAnalysis>(da_val.clone()) {
                    Ok(da) => {
                        let params = academy_forge::ScaffoldParams::new(pathway_id, title, domain_name);
                        let content = academy_forge::scaffold(&da, &params);
                        json!({ "status": "ok", "content": content })
                    }
                    Err(e) => json!({ "status": "error", "message": format!("Invalid domain analysis: {}", e) }),
                }
            } else {
                json!({ "status": "error", "message": "domain_analysis is required for scaffold" })
            }
        }
        _ => json!({ "status": "error", "message": format!("Unknown forge tool: {}", tool) }),
    }
}

fn handle_academy(tool: &str, args: &Value) -> Value {
    match tool {
        "validate-course" => {
            match serde_json::from_value::<nexcore_academy::AcademyCourse>(args.clone()) {
                Ok(course) => {
                    let report = nexcore_academy::validate_course(&course);
                    json!({ "status": "ok", "report": report })
                }
                Err(e) => json!({ "status": "error", "message": format!("Invalid course JSON: {}", e) }),
            }
        }
        "estimate-duration" => {
            let word_count = args.get("word_count").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
            let mins = nexcore_academy::estimate_duration_minutes(word_count);
            json!({ "status": "ok", "duration_minutes": mins })
        }
        "quality-score" => {
            let content = args.get("content").and_then(|v| v.as_str()).unwrap_or("");
            let citations_val = args.get("citations").and_then(|v| v.as_array());
            let citations_vec: Vec<&str> = if let Some(a) = citations_val {
                a.iter().filter_map(|v| v.as_str()).collect()
            } else {
                Vec::new()
            };
            
            let result = nexcore_academy::validate_quality(content, &citations_vec);
            json!({ "status": "ok", "quality": result })
        }
        _ => json!({ "status": "error", "message": format!("Unknown academy tool: {}", tool) }),
    }
}
