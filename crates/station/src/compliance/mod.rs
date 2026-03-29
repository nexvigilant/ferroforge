//! Compliance — Rust-native handler for NexVigilant Station.
//!
//! Routes `compliance_nexvigilant_com_*` tool calls to `nexcore-compliance`.
//! 3 tools: assess, catalog_ich, check_exclusion.

use nexcore_compliance::dsl::{Assessment, ComplianceResult, Finding, FindingSeverity};
use nexcore_compliance::oscal::{Control, ControlStatus};
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("compliance_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "assess" => handle_assess(args),
        "catalog-ich" => handle_catalog_ich(args),
        "check-exclusion" => handle_check_exclusion(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (compliance)");

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

fn get_str<'a>(args: &'a Value, key: &str) -> Option<&'a str> {
    args.get(key).and_then(|v| v.as_str())
}

fn handle_assess(args: &Value) -> Value {
    let system_name = get_str(args, "system_name").unwrap_or("unnamed");

    let controls_json = args.get("controls").and_then(|v| v.as_array());

    let mut assessment = Assessment::new(system_name);

    if let Some(controls) = controls_json {
        for ctrl in controls {
            let id = ctrl.get("id").and_then(|v| v.as_str()).unwrap_or("unknown");
            let title = ctrl.get("title").and_then(|v| v.as_str()).unwrap_or("");
            let status_str = ctrl
                .get("status")
                .and_then(|v| v.as_str())
                .unwrap_or("not_implemented");
            let catalog = ctrl.get("catalog").and_then(|v| v.as_str()).unwrap_or("ICH");

            let status = match status_str {
                "implemented" => ControlStatus::Implemented,
                "partial" => ControlStatus::Partial,
                "not_applicable" => ControlStatus::NotApplicable,
                _ => ControlStatus::NotImplemented,
            };

            assessment.add_control(Control {
                id: id.to_string(),
                title: title.to_string(),
                description: String::new(),
                catalog: catalog.to_string(),
                status,
            });

            // Add finding for non-implemented controls
            if matches!(status, ControlStatus::NotImplemented | ControlStatus::Partial) {
                assessment.add_finding(Finding {
                    control_id: id.to_string(),
                    severity: if status == ControlStatus::NotImplemented {
                        FindingSeverity::High
                    } else {
                        FindingSeverity::Medium
                    },
                    title: format!("Control {id} requires attention"),
                    description: format!("Control {id} is {status_str}"),
                    remediation: Some(format!("Evaluate and implement {id}")),
                });
            }
        }
    }

    assessment.evaluate();

    let implemented = assessment
        .controls
        .iter()
        .filter(|c| c.status == ControlStatus::Implemented)
        .count();
    let total = assessment.controls.len();

    ok(json!({
        "system_name": system_name,
        "controls_assessed": total,
        "controls_implemented": implemented,
        "compliance_pct": if total > 0 { (implemented as f64 / total as f64 * 100.0).round() } else { 0.0 },
        "findings_count": assessment.findings.len(),
        "findings": assessment.findings.iter().map(|f| json!({
            "control_id": f.control_id,
            "severity": format!("{:?}", f.severity),
            "title": f.title,
            "description": f.description,
        })).collect::<Vec<_>>(),
        "result": format!("{:?}", assessment.result.unwrap_or(ComplianceResult::Inconclusive)),
    }))
}

fn handle_catalog_ich(_args: &Value) -> Value {
    // Build a reference catalog of ICH PV controls
    let controls = vec![
        ("ICH-E2A", "Clinical Safety Data Management", "Definitions and standards for expedited reporting"),
        ("ICH-E2B", "ICSR Electronic Transmission", "Electronic submission of ICSRs"),
        ("ICH-E2C", "Periodic Benefit-Risk Evaluation", "PBRER/PSUR periodic reports"),
        ("ICH-E2D", "Post-Approval Safety Data Management", "Post-marketing safety data handling"),
        ("ICH-E2E", "Pharmacovigilance Planning", "Development Safety Update Reports"),
        ("ICH-E2F", "Development Safety Update Reports", "DSUR format and content"),
        ("ICH-E6", "Good Clinical Practice", "GCP guidelines for clinical trials"),
        ("ICH-E8", "General Considerations for Clinical Studies", "Study design principles"),
        ("ICH-E9", "Statistical Principles", "Statistical methods for clinical trials"),
        ("ICH-M1", "MedDRA", "Medical Dictionary for Regulatory Activities"),
    ];

    let ctrl_json: Vec<Value> = controls
        .iter()
        .map(|(id, title, desc)| {
            json!({
                "id": id,
                "title": title,
                "description": desc,
                "catalog": "ICH",
            })
        })
        .collect();

    ok(json!({
        "catalog": "ICH",
        "control_count": ctrl_json.len(),
        "controls": ctrl_json,
    }))
}

fn handle_check_exclusion(args: &Value) -> Value {
    let entity_name = get_str(args, "entity_name").unwrap_or("");

    ok(json!({
        "entity_name": entity_name,
        "note": "SAM.gov exclusion check requires SAM_GOV_API_KEY. Use nexcore-mcp local tool for live lookups.",
        "sam_gov_url": "https://sam.gov/content/exclusions",
        "manual_check": format!("Search for '{}' at sam.gov/content/exclusions", entity_name),
    }))
}
