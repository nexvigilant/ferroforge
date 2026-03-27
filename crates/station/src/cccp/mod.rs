//! CCCP (Competency Framework) — Rust-native handler for NexVigilant Station.
//!
//! Routes `cccp_nexvigilant_com_*` tool calls to `nexcore-cccp`.
//! 5 tools: gap_analysis, plan, epa_readiness, evaluate, phase_info.

use nexcore_cccp::assess::GapAnalysis;
use nexcore_cccp::follow_up::{Achievement, ObjectiveEvaluation, OutcomeEvaluation};
use nexcore_cccp::plan::EngagementPlan;
use nexcore_vigilance::caba::{DomainCategory, DomainStateVector, ProficiencyLevel};
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("cccp_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "gap-analysis" => handle_gap_analysis(args),
        "plan" => handle_plan(args),
        "epa-readiness" => handle_epa_readiness(args),
        "evaluate" => handle_evaluate(args),
        "phase-info" => handle_phase_info(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (cccp)");

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

fn level_from_u8(v: u8) -> ProficiencyLevel {
    match v {
        1 => ProficiencyLevel::L1Novice,
        2 => ProficiencyLevel::L2AdvancedBeginner,
        3 => ProficiencyLevel::L3Competent,
        4 => ProficiencyLevel::L4Proficient,
        5 => ProficiencyLevel::L5Expert,
        _ => ProficiencyLevel::L1Novice,
    }
}

fn parse_levels(args: &Value, key: &str) -> Option<[ProficiencyLevel; 15]> {
    let arr = args.get(key).and_then(|v| v.as_array())?;
    if arr.len() < 15 {
        return None;
    }
    let mut out = [ProficiencyLevel::L1Novice; 15];
    for (i, v) in arr.iter().take(15).enumerate() {
        out[i] = level_from_u8(v.as_u64().unwrap_or(1) as u8);
    }
    Some(out)
}

fn handle_gap_analysis(args: &Value) -> Value {
    let current = match parse_levels(args, "current") {
        Some(v) => v,
        None => return err("missing required parameter: current (array of 15 levels, 1-5)"),
    };
    let desired = match parse_levels(args, "desired") {
        Some(v) => v,
        None => return err("missing required parameter: desired (array of 15 levels, 1-5)"),
    };

    let current_vec = DomainStateVector::new(current);
    let desired_vec = DomainStateVector::new(desired);
    let analysis = GapAnalysis::compute(current_vec, desired_vec);

    let gaps: Vec<Value> = analysis
        .domain_gaps
        .iter()
        .filter(|g| g.gap > 0)
        .map(|g| {
            json!({
                "domain": g.domain.as_str(),
                "current": g.current.as_str(),
                "desired": g.desired.as_str(),
                "gap": g.gap,
            })
        })
        .collect();

    let blocked_epas: Vec<Value> = analysis
        .blocked_epas()
        .iter()
        .map(|e| {
            json!({
                "epa": format!("{:?}", e.epa),
                "threshold": e.threshold.as_str(),
                "blocking_domains": e.blocking_domains.iter().map(|d| d.as_str()).collect::<Vec<_>>(),
            })
        })
        .collect();

    ok(json!({
        "overall_readiness": format!("{:.0}%", analysis.overall_readiness * 100.0),
        "domains_with_gaps": gaps.len(),
        "priority_gaps": gaps,
        "blocked_epas_count": blocked_epas.len(),
        "blocked_epas": blocked_epas,
    }))
}

fn handle_plan(args: &Value) -> Value {
    let current = match parse_levels(args, "current") {
        Some(v) => v,
        None => return err("missing required parameter: current (array of 15 levels, 1-5)"),
    };
    let desired = match parse_levels(args, "desired") {
        Some(v) => v,
        None => return err("missing required parameter: desired (array of 15 levels, 1-5)"),
    };

    let current_vec = DomainStateVector::new(current);
    let desired_vec = DomainStateVector::new(desired);
    let analysis = GapAnalysis::compute(current_vec, desired_vec);
    let gaps = analysis.priority_gaps();
    let gap_refs: Vec<&nexcore_cccp::assess::DomainGap> = gaps;
    let plan = EngagementPlan::from_gaps(&gap_refs);

    let interventions: Vec<Value> = plan
        .interventions
        .iter()
        .map(|i| {
            json!({
                "id": i.id,
                "description": i.description,
                "target_domains": i.target_domains.iter().map(|d| d.as_str()).collect::<Vec<_>>(),
                "target_level": i.target_level.as_str(),
                "priority": format!("{:?}", i.priority),
                "estimated_sessions": i.estimated_sessions,
            })
        })
        .collect();

    ok(json!({
        "scope": plan.scope.iter().map(|d| d.as_str()).collect::<Vec<_>>(),
        "total_interventions": plan.interventions.len(),
        "total_estimated_sessions": plan.total_estimated_sessions,
        "interventions": interventions,
    }))
}

fn handle_epa_readiness(args: &Value) -> Value {
    let current = match parse_levels(args, "current") {
        Some(v) => v,
        None => return err("missing required parameter: current (array of 15 levels, 1-5)"),
    };

    let current_vec = DomainStateVector::new(current);
    let desired_vec = DomainStateVector::new([ProficiencyLevel::L5Expert; 15]);
    let analysis = GapAnalysis::compute(current_vec, desired_vec);

    let ready: Vec<Value> = analysis
        .epa_readiness
        .iter()
        .filter(|e| e.ready)
        .map(|e| {
            json!({
                "epa": format!("{:?}", e.epa),
                "threshold": e.threshold.as_str(),
            })
        })
        .collect();

    let blocked: Vec<Value> = analysis
        .epa_readiness
        .iter()
        .filter(|e| !e.ready)
        .map(|e| {
            json!({
                "epa": format!("{:?}", e.epa),
                "threshold": e.threshold.as_str(),
                "blocking_domains": e.blocking_domains.iter().map(|d| d.as_str()).collect::<Vec<_>>(),
            })
        })
        .collect();

    ok(json!({
        "ready_count": ready.len(),
        "blocked_count": blocked.len(),
        "ready_epas": ready,
        "blocked_epas": blocked,
    }))
}

fn handle_evaluate(args: &Value) -> Value {
    let current = match parse_levels(args, "current") {
        Some(v) => v,
        None => return err("missing required parameter: current (array of 15 levels, 1-5)"),
    };
    let target_level = args
        .get("target_level")
        .and_then(|v| v.as_u64())
        .unwrap_or(3) as u8;

    let current_vec = DomainStateVector::new(current);
    let target = level_from_u8(target_level);

    // Count domains at or above target
    let at_target = current.iter().filter(|&l| *l as u8 >= target as u8).count();
    let below = 15 - at_target;

    ok(json!({
        "target_level": target.as_str(),
        "domains_at_target": at_target,
        "domains_below_target": below,
        "readiness_pct": format!("{:.0}%", at_target as f64 / 15.0 * 100.0),
        "verdict": if at_target >= 15 { "READY" }
                   else if at_target >= 10 { "NEAR_READY" }
                   else { "DEVELOPMENT_NEEDED" },
    }))
}

fn handle_phase_info(args: &Value) -> Value {
    let phase = args
        .get("phase")
        .and_then(|v| v.as_str())
        .unwrap_or("all");

    let phases = vec![
        json!({
            "phase": "1_assess",
            "name": "Assessment",
            "description": "Evaluate current proficiency across 15 PV domains using behavioral anchors",
            "key_tools": ["gap_analysis", "epa_readiness"],
        }),
        json!({
            "phase": "2_plan",
            "name": "Planning",
            "description": "Generate engagement plan with prioritized interventions",
            "key_tools": ["plan"],
        }),
        json!({
            "phase": "3_develop",
            "name": "Development",
            "description": "Execute training interventions and track progress",
            "key_tools": ["evaluate"],
        }),
        json!({
            "phase": "4_evaluate",
            "name": "Evaluation",
            "description": "Assess outcomes against objectives, determine readiness for EPAs",
            "key_tools": ["epa_readiness", "evaluate"],
        }),
    ];

    let filtered: Vec<Value> = if phase == "all" {
        phases
    } else {
        phases
            .into_iter()
            .filter(|p| {
                p.get("phase")
                    .and_then(|v| v.as_str())
                    .map_or(false, |v| v.contains(phase))
            })
            .collect()
    };

    ok(json!({
        "framework": "CCCP (Consultant's Client Care Process)",
        "domains": 15,
        "epas": 21,
        "cpas": 8,
        "ksbs": 1286,
        "phases": filtered,
    }))
}
