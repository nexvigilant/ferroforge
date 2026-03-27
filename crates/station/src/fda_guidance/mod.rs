//! FDA Guidance — Rust-native handler for NexVigilant Station.
//!
//! Routes `fda-guidance_nexvigilant_com_*` tool calls to `nexcore-fda-guidance`.
//! 5 tools: search, get, categories, url, status.

use nexcore_fda_guidance::{format, index};
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("fda-guidance_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "search" => handle_search(args),
        "get" => handle_get(args),
        "categories" => handle_categories(args),
        "url" => handle_url(args),
        "status" => handle_status(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (fda-guidance)");

    Some(ToolCallResult {
        content: vec![ContentBlock::Text {
            text: serde_json::to_string_pretty(&result).unwrap_or_default(),
        }],
        is_error: if result.get("status").and_then(|s| s.as_str()) == Some("error") {
            Some(true)
        } else {
            None
        },
    })
}

fn ok(v: Value) -> Value {
    let mut obj = v;
    if let Some(map) = obj.as_object_mut() {
        map.insert("status".into(), json!("ok"));
    }
    obj
}

fn err(msg: &str) -> Value {
    json!({ "status": "error", "error": msg })
}

fn get_str<'a>(args: &'a Value, key: &str) -> Option<&'a str> {
    args.get(key).and_then(|v| v.as_str())
}

fn handle_search(args: &Value) -> Value {
    let query = match get_str(args, "query") {
        Some(v) => v,
        None => return err("missing required parameter: query"),
    };
    let limit = args.get("limit").and_then(|v| v.as_u64()).unwrap_or(10) as usize;
    let center = get_str(args, "center");
    let product = get_str(args, "product");
    let status_filter = get_str(args, "status_filter");

    match index::search(query, center, product, status_filter, limit) {
        Ok(results) => {
            let output = format::format_search_results(&results, query);
            ok(json!({ "results": output, "count": results.len() }))
        }
        Err(e) => err(&format!("Search failed: {e}")),
    }
}

fn handle_get(args: &Value) -> Value {
    let id = match get_str(args, "id") {
        Some(v) => v,
        None => return err("missing required parameter: id"),
    };
    match index::get(id) {
        Ok(Some(doc)) => {
            let output = format::format_detail(&doc);
            ok(json!({ "document": output }))
        }
        Ok(None) => ok(json!({ "found": false, "note": format!("Document '{}' not found", id) })),
        Err(e) => err(&format!("Lookup failed: {e}")),
    }
}

fn handle_categories(_args: &Value) -> Value {
    match index::load_all() {
        Ok(docs) => {
            let by_center = index::categories_by_center(&docs);
            let by_product = index::categories_by_product(&docs);
            let by_topic = index::categories_by_topic(&docs);
            ok(json!({
                "total_documents": docs.len(),
                "by_center": by_center,
                "by_product": by_product,
                "by_topic": by_topic,
            }))
        }
        Err(e) => err(&format!("Failed to load index: {e}")),
    }
}

fn handle_url(args: &Value) -> Value {
    let id = match get_str(args, "id") {
        Some(v) => v,
        None => return err("missing required parameter: id"),
    };
    match index::get(id) {
        Ok(Some(doc)) => ok(json!({
            "id": id,
            "url": doc.pdf_url.as_deref().unwrap_or("No PDF URL available"),
            "title": doc.title,
        })),
        Ok(None) => ok(json!({ "found": false })),
        Err(e) => err(&format!("Lookup failed: {e}")),
    }
}

fn handle_status(_args: &Value) -> Value {
    match index::load_all() {
        Ok(docs) => ok(json!({
            "engine": "nexcore-fda-guidance",
            "total_documents": docs.len(),
            "index_loaded": true,
        })),
        Err(e) => err(&format!("Index load failed: {e}")),
    }
}
