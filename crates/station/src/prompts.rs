//! MCP Prompts — reusable prompt templates for guided PV workflows.
//!
//! Prompts appear in the agent's prompt library and can be invoked by name.
//! Each prompt maps to one of the 6 guided research courses.

use serde::Serialize;
use serde_json::Value;

// ---------------------------------------------------------------------------
// MCP Prompt types (per MCP 2025-03-26 spec)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize)]
pub struct Prompt {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub arguments: Option<Vec<PromptArgument>>,
}

#[derive(Debug, Clone, Serialize)]
pub struct PromptArgument {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub required: Option<bool>,
}

#[derive(Debug, Serialize)]
pub struct PromptsListResult {
    pub prompts: Vec<Prompt>,
}

#[derive(Debug, Serialize)]
pub struct PromptMessage {
    pub role: String,
    pub content: PromptContent,
}

#[derive(Debug, Serialize)]
#[serde(tag = "type")]
pub enum PromptContent {
    #[serde(rename = "text")]
    Text { text: String },
}

#[derive(Debug, Serialize)]
pub struct PromptGetResult {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    pub messages: Vec<PromptMessage>,
}

// ---------------------------------------------------------------------------
// Prompt definitions
// ---------------------------------------------------------------------------

pub fn list_prompts() -> PromptsListResult {
    PromptsListResult {
        prompts: vec![
            Prompt {
                name: "drug-safety-profile".into(),
                description: Some("Build a complete safety profile for any drug — FAERS adverse events, labeled ADRs, signal detection, literature evidence, and regulatory actions.".into()),
                arguments: Some(vec![
                    PromptArgument { name: "drug".into(), description: Some("Drug name (e.g., metformin, semaglutide, ozempic)".into()), required: Some(true) },
                ]),
            },
            Prompt {
                name: "signal-investigation".into(),
                description: Some("Investigate a potential safety signal for a drug-event pair using FAERS data, disproportionality analysis, and multi-source triangulation.".into()),
                arguments: Some(vec![
                    PromptArgument { name: "drug".into(), description: Some("Drug name".into()), required: Some(true) },
                    PromptArgument { name: "event".into(), description: Some("Adverse event to investigate (optional — omit to scan all events)".into()), required: Some(false) },
                ]),
            },
            Prompt {
                name: "causality-assessment".into(),
                description: Some("Assess whether a drug caused a specific adverse event using Naranjo algorithm and WHO-UMC criteria.".into()),
                arguments: Some(vec![
                    PromptArgument { name: "drug".into(), description: Some("Drug name".into()), required: Some(true) },
                    PromptArgument { name: "event".into(), description: Some("Adverse event".into()), required: Some(true) },
                ]),
            },
            Prompt {
                name: "benefit-risk-assessment".into(),
                description: Some("Compute a quantitative benefit-risk assessment for a drug in a specific indication.".into()),
                arguments: Some(vec![
                    PromptArgument { name: "drug".into(), description: Some("Drug name".into()), required: Some(true) },
                    PromptArgument { name: "indication".into(), description: Some("Therapeutic indication (e.g., type 2 diabetes, hypertension)".into()), required: Some(false) },
                ]),
            },
            Prompt {
                name: "regulatory-intelligence".into(),
                description: Some("Get the regulatory landscape for a drug — ICH guidelines, EU EPAR assessment, FDA approval history, and post-marketing requirements.".into()),
                arguments: Some(vec![
                    PromptArgument { name: "drug".into(), description: Some("Drug name".into()), required: Some(true) },
                ]),
            },
            Prompt {
                name: "competitive-landscape".into(),
                description: Some("Compare safety profiles across competing drugs in the same therapeutic class.".into()),
                arguments: Some(vec![
                    PromptArgument { name: "drug".into(), description: Some("Primary drug name".into()), required: Some(true) },
                    PromptArgument { name: "comparator".into(), description: Some("Comparator drug (optional — auto-detects class if omitted)".into()), required: Some(false) },
                ]),
            },
        ],
    }
}

// ---------------------------------------------------------------------------
// Prompt execution — resolve name + args to messages
// ---------------------------------------------------------------------------

pub fn get_prompt(name: &str, arguments: &Value) -> Result<PromptGetResult, String> {
    let drug = arguments.get("drug").and_then(|v| v.as_str()).unwrap_or("").to_string();
    if drug.is_empty() && name != "regulatory-intelligence" {
        return Err("Missing required argument: drug".into());
    }

    match name {
        "drug-safety-profile" => Ok(prompt_drug_safety_profile(&drug)),
        "signal-investigation" => {
            let event = arguments.get("event").and_then(|v| v.as_str()).unwrap_or("");
            Ok(prompt_signal_investigation(&drug, event))
        }
        "causality-assessment" => {
            let event = arguments.get("event").and_then(|v| v.as_str()).unwrap_or("");
            if event.is_empty() {
                return Err("Missing required argument: event".into());
            }
            Ok(prompt_causality_assessment(&drug, event))
        }
        "benefit-risk-assessment" => {
            let indication = arguments.get("indication").and_then(|v| v.as_str()).unwrap_or("");
            Ok(prompt_benefit_risk(&drug, indication))
        }
        "regulatory-intelligence" => Ok(prompt_regulatory_intel(&drug)),
        "competitive-landscape" => {
            let comparator = arguments.get("comparator").and_then(|v| v.as_str()).unwrap_or("");
            Ok(prompt_competitive_landscape(&drug, comparator))
        }
        other => Err(format!("Unknown prompt: {other}")),
    }
}

// ---------------------------------------------------------------------------
// Individual prompt builders
// ---------------------------------------------------------------------------

fn prompt_drug_safety_profile(drug: &str) -> PromptGetResult {
    PromptGetResult {
        description: Some(format!("Complete safety profile for {drug}")),
        messages: vec![user_message(format!(
            "Build a complete safety profile for {drug}. Follow these steps:\n\n\
             1. **Resolve drug identity**: Call `rxnav_nlm_nih_gov_get_rxcui` with name='{drug}' to get the RxCUI.\n\n\
             2. **Get FAERS adverse events**: Call `api_fda_gov_search_adverse_events` with drug='{drug}' to see reported adverse events, outcomes, and reporter types.\n\n\
             3. **Get labeled ADRs**: Call `dailymed_nlm_nih_gov_get_adverse_reactions` with drug_name='{drug}' to see what's in the FDA-approved label.\n\n\
             4. **Check boxed warnings**: Call `dailymed_nlm_nih_gov_get_boxed_warning` with drug_name='{drug}'.\n\n\
             5. **Run signal detection**: For the top FAERS events, call `calculate_nexvigilant_com_compute_prr` and `calculate_nexvigilant_com_compute_ror` to compute disproportionality.\n\n\
             6. **Search literature**: Call `pubmed_ncbi_nlm_nih_gov_search_signal_literature` with query='{drug} adverse event' for published evidence.\n\n\
             Synthesize all findings into a structured safety profile with: known risks, emerging signals, labeled vs unlabeled events, and an overall safety assessment."
        ))],
    }
}

fn prompt_signal_investigation(drug: &str, event: &str) -> PromptGetResult {
    let event_clause = if event.is_empty() {
        "Scan across all reported events to identify the strongest signals.".to_string()
    } else {
        format!("Focus on the drug-event pair: {drug} + {event}.")
    };

    PromptGetResult {
        description: Some(format!("Signal investigation for {drug}")),
        messages: vec![user_message(format!(
            "Investigate safety signals for {drug}. {event_clause}\n\n\
             1. **Query FAERS**: Call `api_fda_gov_search_adverse_events` with drug='{drug}' to get case counts and outcome distribution.\n\n\
             2. **Compute disproportionality**: Call `calculate_nexvigilant_com_compute_disproportionality_table` with drug='{drug}' to get PRR/ROR/IC/EBGM for top events.\n\n\
             3. **Check EU data**: Call `eudravigilance_ema_europa_eu_search_reports` with substance='{drug}' for European case counts.\n\n\
             4. **Search case reports**: Call `pubmed_ncbi_nlm_nih_gov_search_case_reports` with query='{drug}' for published case reports.\n\n\
             5. **Check clinical trial SAEs**: Call `clinicaltrials_gov_get_serious_adverse_events` for trial-reported serious events.\n\n\
             6. **Check EMA signals**: Call `www_ema_europa_eu_get_safety_signals` with substance='{drug}' for PRAC signal assessments.\n\n\
             For each signal detected, report: drug-event pair, PRR, ROR, case count, labeled/unlabeled status, and clinical significance."
        ))],
    }
}

fn prompt_causality_assessment(drug: &str, event: &str) -> PromptGetResult {
    PromptGetResult {
        description: Some(format!("Causality assessment: {drug} + {event}")),
        messages: vec![user_message(format!(
            "Assess whether {drug} caused {event} using established causality frameworks.\n\n\
             1. **Get FAERS data**: Call `api_fda_gov_search_adverse_events` with drug='{drug}' to get case counts for {event}.\n\n\
             2. **Compute disproportionality**: Call `calculate_nexvigilant_com_compute_prr` and `calculate_nexvigilant_com_compute_ror` with the 2x2 table counts.\n\n\
             3. **Run Naranjo**: Call `calculate_nexvigilant_com_assess_naranjo_causality` — answer each of the 10 Naranjo questions based on available evidence.\n\n\
             4. **Run WHO-UMC**: Call `calculate_nexvigilant_com_assess_who_umc_causality` — classify using the WHO-UMC system (Certain/Probable/Possible/Unlikely).\n\n\
             5. **Search case reports**: Call `pubmed_ncbi_nlm_nih_gov_search_case_reports` with query='{drug} {event}' for dechallenge/rechallenge evidence.\n\n\
             Present the causality verdict with both Naranjo score and WHO-UMC category, citing the evidence for each criterion."
        ))],
    }
}

fn prompt_benefit_risk(drug: &str, indication: &str) -> PromptGetResult {
    let indication_text = if indication.is_empty() {
        "its primary indication".to_string()
    } else {
        indication.to_string()
    };

    PromptGetResult {
        description: Some(format!("Benefit-risk assessment for {drug}")),
        messages: vec![user_message(format!(
            "Compute a quantitative benefit-risk assessment for {drug} in {indication_text}.\n\n\
             1. **Get trial safety data**: Call `clinicaltrials_gov_get_serious_adverse_events` for {drug} trials to quantify risks.\n\n\
             2. **Get FAERS outcomes**: Call `api_fda_gov_get_event_outcomes` with drug='{drug}' to see real-world outcome distribution.\n\n\
             3. **Get labeled ADRs**: Call `dailymed_nlm_nih_gov_get_adverse_reactions` with drug_name='{drug}' for labeled risk profile.\n\n\
             4. **Check EU RMP**: Call `www_ema_europa_eu_get_rmp_summary` with product='{drug}' for the risk management plan.\n\n\
             5. **Compute QBRI**: Call `benefit_risk_nexvigilant_com_compute_qbri` with the gathered benefit and risk data.\n\n\
             Present: benefit evidence, risk evidence, QBRI score, and overall benefit-risk balance with confidence level."
        ))],
    }
}

fn prompt_regulatory_intel(drug: &str) -> PromptGetResult {
    PromptGetResult {
        description: Some(format!("Regulatory intelligence for {drug}")),
        messages: vec![user_message(format!(
            "Get the regulatory landscape for {drug}.\n\n\
             1. **ICH guidelines**: Call `ich_org_get_pv_guidelines` for applicable pharmacovigilance guidelines.\n\n\
             2. **EU assessment**: Call `www_ema_europa_eu_get_epar` with product='{drug}' for the European public assessment report.\n\n\
             3. **FDA approval**: Call `accessdata_fda_gov_get_approval_history` with drug='{drug}' for US approval timeline and conditions.\n\n\
             4. **Safety communications**: Call `www_fda_gov_search_safety_communications` with drug='{drug}' for FDA safety alerts.\n\n\
             5. **Labeling changes**: Call `accessdata_fda_gov_get_labeling_changes` with drug='{drug}' for label revision history.\n\n\
             Summarize: approval status by region, key regulatory actions, post-marketing commitments, and any ongoing safety reviews."
        ))],
    }
}

fn prompt_competitive_landscape(drug: &str, comparator: &str) -> PromptGetResult {
    let comp_text = if comparator.is_empty() {
        format!("Identify the main competitors in {drug}'s therapeutic class, then compare.")
    } else {
        format!("Compare {drug} head-to-head with {comparator}.")
    };

    PromptGetResult {
        description: Some(format!("Competitive landscape for {drug}")),
        messages: vec![user_message(format!(
            "{comp_text}\n\n\
             1. **Identify targets**: Call `platform_api_opentargets_org_search_targets` with query='{drug}' to find the drug's molecular targets and therapeutic area.\n\n\
             2. **Head-to-head FAERS**: Call `faers_nexvigilant_com_faers_compare_drugs` to compare adverse event profiles between {drug} and competitors.\n\n\
             3. **Clinical pipeline**: Call `clinicaltrials_gov_search_trials` with condition matching {drug}'s indication to see what's in development.\n\n\
             Present: comparative safety profiles, differentiation opportunities, and competitive positioning based on safety data."
        ))],
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn user_message(text: String) -> PromptMessage {
    PromptMessage {
        role: "user".into(),
        content: PromptContent::Text { text },
    }
}
