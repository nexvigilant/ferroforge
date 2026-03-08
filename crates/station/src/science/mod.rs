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

/// Predefined research courses (multi-step workflows).
const COURSES: &[(&str, &str, &[&str])] = &[
    (
        "drug-safety-profile",
        "Full drug safety profile: resolve name → FAERS events → labeling ADRs → literature → EU signals → WHO global",
        &[
            "rxnav_nlm_nih_gov_get_rxcui",
            "api_fda_gov_search_adverse_events",
            "dailymed_nlm_nih_gov_get_adverse_reactions",
            "pubmed_ncbi_nlm_nih_gov_search_signal_literature",
            "eudravigilance_ema_europa_eu_get_signal_summary",
            "vigiaccess_org_get_adverse_reactions",
        ],
    ),
    (
        "signal-investigation",
        "Investigate a safety signal: FAERS data → disproportionality → EU confirmation → case reports → trial SAEs → PRAC status",
        &[
            "api_fda_gov_search_adverse_events",
            "open_vigil_fr_compute_disproportionality",
            "eudravigilance_ema_europa_eu_get_signal_summary",
            "pubmed_ncbi_nlm_nih_gov_search_case_reports",
            "clinicaltrials_gov_get_serious_adverse_events",
            "www_ema_europa_eu_get_safety_signals",
        ],
    ),
    (
        "target-investigation",
        "Drug target deep-dive: ChEMBL target → UniProt profile → PDB structures → clinical candidates → safety liabilities",
        &[
            "science_nexvigilant_com_search_targets",
            "science_nexvigilant_com_get_target_profile",
            "science_nexvigilant_com_get_crystal_structures",
            "science_nexvigilant_com_search_clinical_candidates",
            "science_nexvigilant_com_get_target_safety",
        ],
    ),
    (
        "gene-profile",
        "Gene characterization: GEO expression → variants → pathway enrichment → protein interactions → literature",
        &[
            "science_nexvigilant_com_get_expression_profile",
            "science_nexvigilant_com_search_variants",
            "science_nexvigilant_com_get_pathway_enrichment",
            "science_nexvigilant_com_search_protein_interactions",
            "science_nexvigilant_com_search_literature",
        ],
    ),
];

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
            .map(|(name, desc, steps)| {
                json!({
                    "course": name,
                    "description": desc,
                    "steps": steps.len(),
                    "tools": steps,
                })
            })
            .collect();

        let result = json!({
            "status": "ok",
            "station": "NexVigilant Station",
            "message": "Available research courses. Provide 'course' parameter to chart a specific course.",
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
    let found = COURSES.iter().find(|(name, _, _)| *name == course_name);

    match found {
        Some((name, desc, steps)) => {
            let result = json!({
                "status": "ok",
                "course": name,
                "description": desc,
                "step_count": steps.len(),
                "steps": steps.iter().enumerate().map(|(i, s)| {
                    json!({"step": i + 1, "tool": s})
                }).collect::<Vec<Value>>(),
                "usage": format!(
                    "Execute each step in order. Pass the output of each step as context to the next. Start with: {}",
                    steps.first().unwrap_or(&"")
                ),
            });

            ToolCallResult {
                content: vec![ContentBlock::Text {
                    text: serde_json::to_string_pretty(&result).unwrap_or_default(),
                }],
                is_error: None,
            }
        }
        None => {
            let available: Vec<&str> = COURSES.iter().map(|(n, _, _)| *n).collect();
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
