//! FHIR — Rust-native handler for NexVigilant Station.
//!
//! Routes `fhir_nexvigilant_com_*` tool calls to `nexcore-fhir`.
//! 4 tools: adverse_event_to_signal, batch_to_signals, parse_bundle, validate_resource.

use nexcore_fhir::resources::{AdverseEvent, Bundle};
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("fhir_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "adverse-event-to-signal" => handle_ae_to_signal(args),
        "parse-bundle" => handle_parse_bundle(args),
        "validate-resource" => handle_validate(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (fhir)");

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

fn handle_ae_to_signal(args: &Value) -> Value {
    let fhir_json = match get_str(args, "fhir_json") {
        Some(v) => v,
        None => return err("missing required parameter: fhir_json"),
    };
    let ae: AdverseEvent = match serde_json::from_str(fhir_json) {
        Ok(v) => v,
        Err(e) => return err(&format!("Invalid FHIR AdverseEvent JSON: {e}")),
    };

    let signal = nexcore_fhir::adapter::adverse_event_to_signal(&ae);

    ok(json!({
        "fhir_id": signal.fhir_id,
        "actuality": signal.actuality,
        "meddra_term": {
            "preferred_term": signal.meddra_term.preferred_term,
            "code": signal.meddra_term.code,
            "is_coded": signal.meddra_term.is_coded,
        },
        "drug": {
            "name": signal.drug.name,
            "causality": signal.drug.causality,
        },
        "severity": {
            "tier": format!("{:?}", signal.severity.tier),
            "is_serious": signal.severity.is_serious,
        },
        "outcome": {
            "code": signal.outcome.code,
            "is_fatal": signal.outcome.is_fatal,
            "is_resolved": signal.outcome.is_resolved,
        },
    }))
}

fn handle_parse_bundle(args: &Value) -> Value {
    let fhir_json = match get_str(args, "fhir_json") {
        Some(v) => v,
        None => return err("missing required parameter: fhir_json"),
    };
    let bundle: Bundle = match serde_json::from_str(fhir_json) {
        Ok(v) => v,
        Err(e) => return err(&format!("Invalid FHIR Bundle JSON: {e}")),
    };

    let entry_count = bundle.entry.len();

    ok(json!({
        "resource_type": bundle.resource_type,
        "bundle_type": bundle.r#type,
        "entry_count": entry_count,
        "total": bundle.total,
    }))
}

fn handle_validate(args: &Value) -> Value {
    let fhir_json = match get_str(args, "fhir_json") {
        Some(v) => v,
        None => return err("missing required parameter: fhir_json"),
    };
    let resource_type = get_str(args, "resource_type").unwrap_or("AdverseEvent");

    let parsed: Result<Value, _> = serde_json::from_str(fhir_json);
    match parsed {
        Ok(v) => {
            let has_resource_type = v.get("resourceType").is_some();
            let rt_matches = v
                .get("resourceType")
                .and_then(|r| r.as_str())
                .map_or(false, |r| r == resource_type);
            ok(json!({
                "valid_json": true,
                "has_resource_type": has_resource_type,
                "resource_type_matches": rt_matches,
                "expected_type": resource_type,
            }))
        }
        Err(e) => ok(json!({
            "valid_json": false,
            "error": format!("{e}"),
        })),
    }
}
