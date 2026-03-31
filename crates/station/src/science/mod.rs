//! NexVigilant Science Station — Rust-native science domain handlers.
//!
//! Three rail domains:
//!   - `hexim1`  — curated HEXIM1/PTEFb research (compiled into binary)
//!   - `targets` — drug target intelligence (ChEMBL, UniProt, PDB live APIs)
//!   - `genomics` — expression mining (NCBI GEO, PubMed live APIs)
//!
//! Plus `chart_course` — compose multi-tool workflows into a single invocation.

pub mod genomics;
pub mod hexim1;
mod http;
pub mod targets;

use serde_json::{json, Value};
use tracing::info;

use crate::config::ConfigRegistry;
use crate::protocol::{ContentBlock, ToolCallResult};

/// A single step in a research course, with tool name and example parameters.
struct CourseStep {
    tool: &'static str,
    example_params: &'static str,
}

/// Predefined research courses (multi-step workflows) with example parameters.
struct Course {
    name: &'static str,
    description: &'static str,
    steps: &'static [CourseStep],
}

const COURSES: &[Course] = &[
    Course {
        name: "drug-safety-profile",
        description: "Full drug safety profile: resolve name → FAERS events → labeling ADRs → literature → EU signals → WHO global",
        steps: &[
            CourseStep { tool: "rxnav_nlm_nih_gov_get_rxcui", example_params: r#"{"name": "metformin"}"# },
            CourseStep { tool: "api_fda_gov_search_adverse_events", example_params: r#"{"drug_name": "metformin", "limit": 10}"# },
            CourseStep { tool: "dailymed_nlm_nih_gov_get_adverse_reactions", example_params: r#"{"drug_name": "metformin"}"# },
            CourseStep { tool: "pubmed_ncbi_nlm_nih_gov_search_signal_literature", example_params: r#"{"drug": "metformin", "max_results": 5}"# },
            CourseStep { tool: "eudravigilance_ema_europa_eu_get_signal_summary", example_params: r#"{"substance": "metformin"}"# },
            CourseStep { tool: "vigiaccess_org_get_adverse_reactions", example_params: r#"{"drug": "metformin"}"# },
        ],
    },
    Course {
        name: "signal-investigation",
        description: "Investigate a safety signal: FAERS data → disproportionality → EU confirmation → case reports → trial SAEs → PRAC status",
        steps: &[
            CourseStep { tool: "api_fda_gov_search_adverse_events", example_params: r#"{"drug_name": "semaglutide", "reaction": "pancreatitis", "limit": 10}"# },
            CourseStep { tool: "open-vigil_fr_compute_disproportionality", example_params: r#"{"drug": "semaglutide", "event": "pancreatitis"}"# },
            CourseStep { tool: "eudravigilance_ema_europa_eu_get_signal_summary", example_params: r#"{"substance": "semaglutide"}"# },
            CourseStep { tool: "pubmed_ncbi_nlm_nih_gov_search_case_reports", example_params: r#"{"drug": "semaglutide", "event": "pancreatitis"}"# },
            CourseStep { tool: "clinicaltrials_gov_get_serious_adverse_events", example_params: r#"{"nct_id": "NCT03548935"}"# },
            CourseStep { tool: "www_ema_europa_eu_get_safety_signals", example_params: r#"{"substance": "semaglutide"}"# },
        ],
    },
    Course {
        name: "causality-assessment",
        description: "Assess drug-event causality: FAERS case counts → disproportionality → WHO-UMC framework → published case reports",
        steps: &[
            CourseStep { tool: "api_fda_gov_search_adverse_events", example_params: r#"{"drug_name": "metformin", "reaction": "lactic acidosis"}"# },
            CourseStep { tool: "open-vigil_fr_compute_disproportionality", example_params: r#"{"drug": "metformin", "event": "lactic acidosis"}"# },
            CourseStep { tool: "who-umc_org_get_causality_assessment", example_params: r#"{}"# },
            CourseStep { tool: "pubmed_ncbi_nlm_nih_gov_search_case_reports", example_params: r#"{"drug": "metformin", "event": "lactic acidosis"}"# },
        ],
    },
    Course {
        name: "benefit-risk-assessment",
        description: "Quantify benefit-risk: trial safety endpoints → FAERS outcome distribution → label ADRs → EU risk management plan",
        steps: &[
            CourseStep { tool: "clinicaltrials_gov_get_safety_endpoints", example_params: r#"{"nct_id": "NCT03548935"}"# },
            CourseStep { tool: "api_fda_gov_get_event_outcomes", example_params: r#"{"drug_name": "semaglutide"}"# },
            CourseStep { tool: "dailymed_nlm_nih_gov_get_adverse_reactions", example_params: r#"{"drug_name": "semaglutide"}"# },
            CourseStep { tool: "www_ema_europa_eu_get_rmp_summary", example_params: r#"{"product": "semaglutide"}"# },
        ],
    },
    Course {
        name: "regulatory-intelligence",
        description: "Trace regulatory lifecycle: ICH PV guidelines → EU assessment report → FDA approval history",
        steps: &[
            CourseStep { tool: "ich_org_get_pv_guidelines", example_params: r#"{}"# },
            CourseStep { tool: "www_ema_europa_eu_get_epar", example_params: r#"{"product": "ozempic"}"# },
            CourseStep { tool: "accessdata_fda_gov_get_approval_history", example_params: r#"{"drug": "semaglutide"}"# },
        ],
    },
    Course {
        name: "competitive-landscape",
        description: "Map competitive terrain: drug targets → head-to-head disproportionality → active clinical pipeline",
        steps: &[
            CourseStep { tool: "go_drugbank_com_get_targets", example_params: r#"{"drug": "semaglutide"}"# },
            CourseStep { tool: "open-vigil_fr_compare_drugs", example_params: r#"{"drug_a": "semaglutide", "drug_b": "tirzepatide"}"# },
            CourseStep { tool: "clinicaltrials_gov_search_trials", example_params: r#"{"condition": "obesity", "intervention": "GLP-1"}"# },
        ],
    },
];

/// Number of predefined research courses.
pub fn course_count() -> usize {
    COURSES.len()
}

/// Course summaries for the directory meta-tool.
pub fn course_summaries() -> Vec<(&'static str, &'static str, usize)> {
    COURSES.iter().map(|c| (c.name, c.description, c.steps.len())).collect()
}

/// Validate that all course tool references resolve to real tools in the registry.
/// Called at startup to catch stale course definitions early.
/// Returns a list of (course_name, tool_name) pairs that failed to resolve.
pub fn validate_courses(registry: &ConfigRegistry) -> Vec<(String, String)> {
    let registry_tools: Vec<String> = registry
        .configs
        .iter()
        .flat_map(|c| {
            let domain_prefix = c.domain.replace('.', "_");
            c.tools.iter().map(move |t| {
                format!("{}_{}", domain_prefix, t.name.replace('-', "_"))
            })
        })
        .collect();

    let mut missing = Vec::new();
    for course in COURSES {
        for step in course.steps {
            if !registry_tools.contains(&step.tool.to_string()) {
                missing.push((course.name.to_string(), step.tool.to_string()));
            }
        }
    }
    missing
}

/// Try to handle a tool call natively in Rust.
/// Returns `Some(ToolCallResult)` if handled, `None` to fall through to proxy.
pub fn try_handle(tool_name: &str, args: &Value, registry: &ConfigRegistry) -> Option<ToolCallResult> {
    // Meta-tool: chart a course
    if tool_name == "nexvigilant_chart_course" {
        return Some(handle_chart_course(args, registry));
    }

    // Strip the science domain prefix to get the bare tool name
    let bare = tool_name
        .strip_prefix("science_nexvigilant_com_")
        .map(|s| s.replace('_', "-"));

    let bare_name = bare.as_deref()?;

    // Try each science handler
    let result = hexim1::handle(bare_name, args)
        .or_else(|| targets::handle(bare_name, args))
        .or_else(|| genomics::handle(bare_name, args))?;

    info!(tool = tool_name, "Handled natively in Rust");

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

/// Chart a course through the station — list available courses or describe a specific one.
fn handle_chart_course(args: &Value, _registry: &ConfigRegistry) -> ToolCallResult {
    let course_name = args.get("course").and_then(|v| v.as_str()).unwrap_or("");

    if course_name.is_empty() {
        // List all courses
        let courses: Vec<Value> = COURSES
            .iter()
            .map(|c| {
                json!({
                    "course": c.name,
                    "description": c.description,
                    "steps": c.steps.len(),
                    "tools": c.steps.iter().map(|s| s.tool).collect::<Vec<_>>(),
                })
            })
            .collect();

        let result = json!({
            "status": "ok",
            "station": "NexVigilant Station",
            "message": "Pick a course below and call this tool again with the 'course' parameter. Most users start with 'drug-safety-profile'. Each course returns the exact tool names and parameters to execute in order.",
            "tip": "Example: nexvigilant_chart_course({\"course\": \"drug-safety-profile\"})",
            "courses": courses,
        });

        return ToolCallResult {
            content: vec![ContentBlock::Text {
                text: serde_json::to_string_pretty(&result).unwrap_or_default(),
            }],
            is_error: None,
        };
    }

    // Find the specific course
    let found = COURSES.iter().find(|c| c.name == course_name);

    match found {
        Some(course) => {
            let result = json!({
                "status": "ok",
                "course": course.name,
                "description": course.description,
                "step_count": course.steps.len(),
                "steps": course.steps.iter().enumerate().map(|(i, s)| {
                    json!({
                        "step": i + 1,
                        "tool": s.tool,
                        "example_params": serde_json::from_str::<Value>(s.example_params).unwrap_or(json!({})),
                    })
                }).collect::<Vec<Value>>(),
                "usage": format!(
                    "Execute each step in order. Pass the output of each step as context to the next. Start with: {}",
                    course.steps.first().map(|s| s.tool).unwrap_or("")
                ),
                "tip": "Replace 'metformin' or 'semaglutide' in example_params with your drug of interest. Each step's output feeds the next.",
            });

            ToolCallResult {
                content: vec![ContentBlock::Text {
                    text: serde_json::to_string_pretty(&result).unwrap_or_default(),
                }],
                is_error: None,
            }
        }
        None => {
            let available: Vec<&str> = COURSES.iter().map(|c| c.name).collect();
            let result = json!({
                "status": "error",
                "message": format!("Unknown course: '{course_name}'"),
                "available_courses": available,
            });

            ToolCallResult {
                content: vec![ContentBlock::Text {
                    text: serde_json::to_string_pretty(&result).unwrap_or_default(),
                }],
                is_error: Some(true),
            }
        }
    }
}
