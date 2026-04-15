//! MCP Resources — structured knowledge the agent can read without tool calls.
//!
//! Resources are the "GET" to tools' "POST". They provide reference data
//! that agents can load into context once and reuse throughout a conversation.
//!
//! Resource templates use URI patterns like `drug://{name}/safety-profile`
//! that agents fill in with parameters.

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::config::ConfigRegistry;

// ---------------------------------------------------------------------------
// MCP Resource types (per MCP 2025-03-26 spec)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize)]
pub struct Resource {
    pub uri: String,
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(rename = "mimeType", skip_serializing_if = "Option::is_none")]
    pub mime_type: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ResourceTemplate {
    #[serde(rename = "uriTemplate")]
    pub uri_template: String,
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(rename = "mimeType", skip_serializing_if = "Option::is_none")]
    pub mime_type: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct ResourceContent {
    pub uri: String,
    #[serde(rename = "mimeType", skip_serializing_if = "Option::is_none")]
    pub mime_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub text: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct ResourcesListResult {
    pub resources: Vec<Resource>,
}

#[derive(Debug, Serialize)]
pub struct ResourceTemplatesListResult {
    #[serde(rename = "resourceTemplates")]
    pub resource_templates: Vec<ResourceTemplate>,
}

#[derive(Debug, Serialize)]
pub struct ResourceReadResult {
    pub contents: Vec<ResourceContent>,
}

// ---------------------------------------------------------------------------
// Static resources — always available
// ---------------------------------------------------------------------------

pub fn list_resources(registry: &ConfigRegistry) -> ResourcesListResult {
    let mut resources = vec![
        // Platform overview
        Resource {
            uri: "nexvigilant://capabilities".into(),
            name: "NexVigilant Capabilities".into(),
            description: Some("Complete platform overview — domains, tool counts, transport surfaces, and guided research courses.".into()),
            mime_type: Some("application/json".into()),
        },
        Resource {
            uri: "nexvigilant://domains".into(),
            name: "Domain Directory".into(),
            description: Some("All pharmacovigilance domains with tool counts and descriptions.".into()),
            mime_type: Some("application/json".into()),
        },
        Resource {
            uri: "nexvigilant://methods".into(),
            name: "PV Methods Reference".into(),
            description: Some("Signal detection algorithms (PRR, ROR, IC, EBGM), causality methods (Naranjo, WHO-UMC), and seriousness classification (ICH E2A).".into()),
            mime_type: Some("application/json".into()),
        },
        Resource {
            uri: "nexvigilant://regulatory-agencies".into(),
            name: "Global Regulatory Agencies".into(),
            description: Some("FDA, EMA, PMDA, TGA, MHRA, Swissmedic, ANVISA, COFEPRIS, HSA, Health Canada — reporting requirements and databases.".into()),
            mime_type: Some("application/json".into()),
        },
        Resource {
            uri: "nexvigilant://ich-guidelines".into(),
            name: "ICH Guidelines Index".into(),
            description: Some("Index of ICH pharmacovigilance guidelines: E2A (clinical safety), E2B (electronic reporting), E2C (periodic reports), E2D (post-approval), E2E (PV planning).".into()),
            mime_type: Some("application/json".into()),
        },
        // MedDRA coding reference
        Resource {
            uri: "nexvigilant://meddra".into(),
            name: "MedDRA Coding Guide".into(),
            description: Some("Medical Dictionary for Regulatory Activities — hierarchy levels (SOC/HLGT/HLT/PT/LLT), coding rules, and Standardised MedDRA Queries (SMQs).".into()),
            mime_type: Some("application/json".into()),
        },
        // Reporting timelines
        Resource {
            uri: "nexvigilant://reporting-timelines".into(),
            name: "Global Reporting Timelines".into(),
            description: Some("Expedited and periodic reporting deadlines by agency and seriousness — FDA 15-day, EMA 15/90-day, PMDA 15/30-day, and all other regions.".into()),
            mime_type: Some("application/json".into()),
        },
        // FAERS database reference
        Resource {
            uri: "nexvigilant://faers-guide".into(),
            name: "FAERS Database Guide".into(),
            description: Some("FDA Adverse Event Reporting System — database structure, query syntax, field definitions, limitations, and best practices for safety signal mining.".into()),
            mime_type: Some("application/json".into()),
        },
        // Seriousness criteria
        Resource {
            uri: "nexvigilant://seriousness-criteria".into(),
            name: "ICH E2A Seriousness Criteria".into(),
            description: Some("Complete seriousness classification criteria per ICH E2A — death, life-threatening, hospitalization, disability, congenital anomaly, medically important.".into()),
            mime_type: Some("application/json".into()),
        },
        // Signal detection workflow
        Resource {
            uri: "nexvigilant://signal-detection-workflow".into(),
            name: "Signal Detection Workflow".into(),
            description: Some("End-to-end signal detection methodology — from data mining through validation to regulatory action. Covers all 4 disproportionality measures.".into()),
            mime_type: Some("application/json".into()),
        },
        // Causality frameworks
        Resource {
            uri: "nexvigilant://causality-frameworks".into(),
            name: "Causality Assessment Frameworks".into(),
            description: Some("Naranjo algorithm (10 questions, scoring), WHO-UMC system (6 categories), Bradford Hill criteria (9 viewpoints), and RUCAM for hepatotoxicity.".into()),
            mime_type: Some("application/json".into()),
        },
        // Pharma company directory
        Resource {
            uri: "nexvigilant://pharma-directory".into(),
            name: "Pharmaceutical Company Directory".into(),
            description: Some("41 major pharmaceutical companies with tool access — pipelines, safety profiles, head-to-head comparisons, and product portfolios.".into()),
            mime_type: Some("application/json".into()),
        },
        // Benefit-risk methodology
        Resource {
            uri: "nexvigilant://benefit-risk-methods".into(),
            name: "Benefit-Risk Assessment Methods".into(),
            description: Some("Quantitative benefit-risk frameworks — QBRI index, therapeutic window computation, ICH E2C periodic assessment, and EU RMP integration.".into()),
            mime_type: Some("application/json".into()),
        },
        // Microgram decision trees
        Resource {
            uri: "nexvigilant://micrograms".into(),
            name: "PV Decision Trees (Micrograms)".into(),
            description: Some("969 atomic decision programs for PV workflows — case triage, signal routing, regulatory classification, and causality pipelines. Sub-microsecond execution.".into()),
            mime_type: Some("application/json".into()),
        },
    ];

    // Dynamic: station health
    let config_count = registry.config_count();
    let tool_count = registry.tool_count();
    resources.push(Resource {
        uri: "nexvigilant://station/health".into(),
        name: "Station Health".into(),
        description: Some(format!(
            "Live station status — {config_count} configs, {tool_count} tools, uptime, error rates."
        )),
        mime_type: Some("application/json".into()),
    });

    ResourcesListResult { resources }
}

// ---------------------------------------------------------------------------
// Resource templates — parameterized URIs
// ---------------------------------------------------------------------------

pub fn list_resource_templates() -> ResourceTemplatesListResult {
    ResourceTemplatesListResult {
        resource_templates: vec![
            ResourceTemplate {
                uri_template: "nexvigilant://drug/{name}/safety-profile".into(),
                name: "Drug Safety Profile".into(),
                description: Some("Comprehensive safety profile for a drug — known ADRs, signal status, boxed warnings, and regulatory actions. Combine FAERS data, DailyMed labeling, and computed disproportionality.".into()),
                mime_type: Some("application/json".into()),
            },
            ResourceTemplate {
                uri_template: "nexvigilant://drug/{name}/signals".into(),
                name: "Drug Signal Detection".into(),
                description: Some("Active safety signals for a drug — PRR, ROR, IC, EBGM scores across all reported adverse events.".into()),
                mime_type: Some("application/json".into()),
            },
            ResourceTemplate {
                uri_template: "nexvigilant://drug/{name}/label".into(),
                name: "Drug Label (FDA)".into(),
                description: Some("Current FDA-approved drug label sections — boxed warning, adverse reactions, contraindications, drug interactions.".into()),
                mime_type: Some("application/json".into()),
            },
            ResourceTemplate {
                uri_template: "nexvigilant://guideline/ich/{code}".into(),
                name: "ICH Guideline".into(),
                description: Some("Full ICH guideline content by code (e.g., E2A, E2B, E2C, E2D, E2E, M1, Q1A).".into()),
                mime_type: Some("application/json".into()),
            },
            ResourceTemplate {
                uri_template: "nexvigilant://agency/{name}".into(),
                name: "Regulatory Agency Profile".into(),
                description: Some("Agency reporting requirements, databases, timelines, and contact information. Agencies: FDA, EMA, PMDA, TGA, MHRA, Swissmedic, ANVISA.".into()),
                mime_type: Some("application/json".into()),
            },
            ResourceTemplate {
                uri_template: "nexvigilant://domain/{domain}/tools".into(),
                name: "Domain Tool Catalog".into(),
                description: Some("All tools available in a specific Station domain with descriptions and parameter schemas.".into()),
                mime_type: Some("application/json".into()),
            },
            ResourceTemplate {
                uri_template: "nexvigilant://drug/{name}/interactions".into(),
                name: "Drug Interactions".into(),
                description: Some("Drug-drug interaction guide — tools to check CYP enzyme interactions, contraindications, and concomitant medication risks.".into()),
                mime_type: Some("application/json".into()),
            },
            ResourceTemplate {
                uri_template: "nexvigilant://drug/{name}/regulatory-status".into(),
                name: "Drug Regulatory Status".into(),
                description: Some("Regulatory status across agencies — approval history, labeling changes, REMS, post-marketing requirements.".into()),
                mime_type: Some("application/json".into()),
            },
            ResourceTemplate {
                uri_template: "nexvigilant://pharma/{company}".into(),
                name: "Pharmaceutical Company Profile".into(),
                description: Some("Company safety intelligence — product portfolio, pipeline, recall history, and head-to-head safety comparisons.".into()),
                mime_type: Some("application/json".into()),
            },
            ResourceTemplate {
                uri_template: "nexvigilant://meddra/{term}".into(),
                name: "MedDRA Term Lookup".into(),
                description: Some("MedDRA term hierarchy — SOC, HLGT, HLT, PT, LLT levels for a given term. Used for adverse event coding.".into()),
                mime_type: Some("application/json".into()),
            },
            ResourceTemplate {
                uri_template: "nexvigilant://course/{name}".into(),
                name: "Research Course Guide".into(),
                description: Some("Step-by-step research workflow with exact tool names and parameters. Courses: drug-safety-profile, signal-investigation, causality-assessment, benefit-risk-assessment, regulatory-intelligence, competitive-landscape.".into()),
                mime_type: Some("application/json".into()),
            },
        ],
    }
}

// ---------------------------------------------------------------------------
// Resource reading — resolve URI to content
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
pub struct ResourceReadParams {
    pub uri: String,
}

pub fn read_resource(registry: &ConfigRegistry, uri: &str) -> Result<ResourceReadResult, String> {
    // Static resources
    match uri {
        // Static resources
        "nexvigilant://capabilities" => Ok(read_capabilities(registry)),
        "nexvigilant://domains" => Ok(read_domains(registry)),
        "nexvigilant://methods" => Ok(read_methods()),
        "nexvigilant://regulatory-agencies" => Ok(read_regulatory_agencies()),
        "nexvigilant://ich-guidelines" => Ok(read_ich_guidelines()),
        "nexvigilant://station/health" => Ok(read_station_health(registry)),
        "nexvigilant://meddra" => Ok(read_meddra_guide()),
        "nexvigilant://reporting-timelines" => Ok(read_reporting_timelines()),
        "nexvigilant://faers-guide" => Ok(read_faers_guide()),
        "nexvigilant://seriousness-criteria" => Ok(read_seriousness_criteria()),
        "nexvigilant://signal-detection-workflow" => Ok(read_signal_detection_workflow()),
        "nexvigilant://causality-frameworks" => Ok(read_causality_frameworks()),
        "nexvigilant://pharma-directory" => Ok(read_pharma_directory()),
        "nexvigilant://benefit-risk-methods" => Ok(read_benefit_risk_methods()),
        "nexvigilant://micrograms" => Ok(read_micrograms_guide()),
        _ => {
            // Template-based resources — drug
            if let Some(drug) = uri.strip_prefix("nexvigilant://drug/") {
                return read_drug_resource(drug);
            }
            // ICH guideline
            if let Some(code) = uri.strip_prefix("nexvigilant://guideline/ich/") {
                return Ok(read_ich_guideline(code));
            }
            // Regulatory agency
            if let Some(agency) = uri.strip_prefix("nexvigilant://agency/") {
                return Ok(read_agency(agency));
            }
            // Domain tool catalog
            if let Some(rest) = uri.strip_prefix("nexvigilant://domain/") {
                if let Some(domain) = rest.strip_suffix("/tools") {
                    return Ok(read_domain_tools(registry, domain));
                }
            }
            // Pharma company
            if let Some(company) = uri.strip_prefix("nexvigilant://pharma/") {
                return Ok(read_pharma_company(company));
            }
            // MedDRA term
            if let Some(term) = uri.strip_prefix("nexvigilant://meddra/") {
                return Ok(read_meddra_term(term));
            }
            // Research course
            if let Some(course) = uri.strip_prefix("nexvigilant://course/") {
                return Ok(read_course_guide(course));
            }
            Err(format!("Resource not found: {uri}"))
        }
    }
}

// ---------------------------------------------------------------------------
// Static resource content
// ---------------------------------------------------------------------------

fn read_capabilities(registry: &ConfigRegistry) -> ResourceReadResult {
    let content = serde_json::json!({
        "platform": "NexVigilant Station",
        "version": env!("CARGO_PKG_VERSION"),
        "description": "Pharmacovigilance intelligence platform for AI agents and human professionals",
        "tools": registry.tool_count(),
        "configs": registry.config_count(),
        "transports": ["Streamable HTTP", "SSE", "HTTP REST"],
        "guided_courses": [
            {"name": "drug-safety-profile", "steps": 6, "description": "Complete safety profile from FAERS + labeling + literature"},
            {"name": "signal-investigation", "steps": 6, "description": "End-to-end signal detection and validation"},
            {"name": "causality-assessment", "steps": 4, "description": "Naranjo + WHO-UMC causality evaluation"},
            {"name": "benefit-risk-assessment", "steps": 4, "description": "Quantitative benefit-risk scoring"},
            {"name": "regulatory-intelligence", "steps": 3, "description": "ICH guidelines + EU/FDA regulatory landscape"},
            {"name": "competitive-landscape", "steps": 3, "description": "Head-to-head drug safety comparison"},
        ],
        "key_capabilities": [
            "Signal detection: PRR, ROR, IC (Information Component), EBGM (Empirical Bayesian Geometric Mean)",
            "Causality assessment: Naranjo algorithm, WHO-UMC system",
            "Seriousness classification: ICH E2A criteria",
            "Benefit-risk: Quantitative benefit-risk index (QBRI)",
            "FAERS access: 20M+ adverse event reports from FDA",
            "Drug labeling: DailyMed SPL labels for all FDA-approved drugs",
            "Literature: PubMed case reports and signal literature",
            "Regulatory: ICH, EMA, FDA, PMDA, TGA, WHO guidelines and databases",
            "Pharma intel: 41 pharmaceutical company profiles and pipelines",
        ],
    });
    resource_json(uri_str("nexvigilant://capabilities"), &content)
}

fn read_domains(registry: &ConfigRegistry) -> ResourceReadResult {
    let domains: Vec<Value> = registry
        .configs()
        .iter()
        .map(|c| {
            serde_json::json!({
                "domain": c.domain,
                "title": c.title,
                "description": c.description,
                "tools": c.tools.len(),
            })
        })
        .collect();

    let content = serde_json::json!({
        "total_domains": domains.len(),
        "domains": domains,
    });
    resource_json(uri_str("nexvigilant://domains"), &content)
}

fn read_methods() -> ResourceReadResult {
    let content = serde_json::json!({
        "signal_detection": {
            "PRR": {
                "name": "Proportional Reporting Ratio",
                "formula": "PRR = (a/a+b) / (c/c+d)",
                "threshold": "PRR ≥ 2, chi² ≥ 4, N ≥ 3",
                "tool": "calculate_nexvigilant_com_compute_prr",
                "interpretation": "Values >2 suggest disproportionate reporting"
            },
            "ROR": {
                "name": "Reporting Odds Ratio",
                "formula": "ROR = (a*d) / (b*c)",
                "threshold": "Lower CI > 1",
                "tool": "calculate_nexvigilant_com_compute_ror",
                "interpretation": "Odds of the event given the drug vs all other drugs"
            },
            "IC": {
                "name": "Information Component (Bayesian)",
                "formula": "IC = log2(observed/expected)",
                "threshold": "IC025 > 0",
                "tool": "calculate_nexvigilant_com_compute_ic",
                "interpretation": "Positive IC indicates more reports than expected"
            },
            "EBGM": {
                "name": "Empirical Bayesian Geometric Mean",
                "formula": "Shrinkage-adjusted RR using gamma-Poisson model",
                "threshold": "EB05 ≥ 2",
                "tool": "calculate_nexvigilant_com_compute_ebgm",
                "interpretation": "Most conservative measure — accounts for sparse data"
            },
        },
        "causality_assessment": {
            "Naranjo": {
                "name": "Naranjo Adverse Drug Reaction Probability Scale",
                "scores": {"definite": "≥9", "probable": "5-8", "possible": "1-4", "doubtful": "≤0"},
                "tool": "calculate_nexvigilant_com_assess_naranjo_causality",
                "questions": 10,
            },
            "WHO_UMC": {
                "name": "WHO-UMC Causality Assessment System",
                "categories": ["Certain", "Probable/Likely", "Possible", "Unlikely", "Conditional/Unclassified", "Unassessable/Unclassifiable"],
                "tool": "calculate_nexvigilant_com_assess_who_umc_causality",
            },
        },
        "seriousness": {
            "ICH_E2A": {
                "criteria": [
                    "Death",
                    "Life-threatening",
                    "Hospitalization (initial or prolonged)",
                    "Disability or incapacity",
                    "Congenital anomaly/birth defect",
                    "Medically important event",
                ],
                "tool": "calculate_nexvigilant_com_classify_seriousness",
            },
        },
    });
    resource_json(uri_str("nexvigilant://methods"), &content)
}

fn read_regulatory_agencies() -> ResourceReadResult {
    let content = serde_json::json!({
        "agencies": [
            {"code": "FDA", "name": "US Food and Drug Administration", "country": "United States", "database": "FAERS", "tools_prefix": "api_fda_gov", "reporting_timeline": "15 days (serious), 90 days (periodic)"},
            {"code": "EMA", "name": "European Medicines Agency", "country": "EU", "database": "EudraVigilance", "tools_prefix": "eudravigilance_ema_europa_eu", "reporting_timeline": "15 days (fatal/life-threatening), 90 days (serious)"},
            {"code": "PMDA", "name": "Pharmaceuticals and Medical Devices Agency", "country": "Japan", "database": "JADER", "tools_prefix": "www_pmda_go_jp", "reporting_timeline": "15 days (known serious), 30 days (unknown serious)"},
            {"code": "TGA", "name": "Therapeutic Goods Administration", "country": "Australia", "database": "DAEN", "tools_prefix": "www_tga_gov_au", "reporting_timeline": "15 days (serious)"},
            {"code": "MHRA", "name": "Medicines and Healthcare products Regulatory Agency", "country": "United Kingdom", "database": "Yellow Card", "tools_prefix": "www_gov_uk", "reporting_timeline": "15 days (serious)"},
            {"code": "Swissmedic", "name": "Swiss Agency for Therapeutic Products", "country": "Switzerland", "database": "ElViS", "tools_prefix": "www_swissmedic_ch", "reporting_timeline": "15 days (serious)"},
            {"code": "ANVISA", "name": "Brazilian Health Regulatory Agency", "country": "Brazil", "database": "Notivisa", "tools_prefix": "anvisa_gov_br", "reporting_timeline": "15 days (serious)"},
            {"code": "Health Canada", "name": "Health Canada", "country": "Canada", "database": "CADRMP", "tools_prefix": "recalls_rappels_canada_ca", "reporting_timeline": "15 days (serious)"},
            {"code": "COFEPRIS", "name": "Federal Commission for Protection against Sanitary Risk", "country": "Mexico", "database": "National PV System", "tools_prefix": "cofepris_gob_mx", "reporting_timeline": "15 days (serious)"},
            {"code": "HSA", "name": "Health Sciences Authority", "country": "Singapore", "database": "PRISM", "tools_prefix": "www_hsa_gov_sg", "reporting_timeline": "15 days (serious)"},
            {"code": "WHO", "name": "World Health Organization", "country": "Global", "database": "VigiBase (via VigiAccess)", "tools_prefix": "vigiaccess_org", "reporting_timeline": "N/A (aggregator)"},
        ],
    });
    resource_json(uri_str("nexvigilant://regulatory-agencies"), &content)
}

fn read_ich_guidelines() -> ResourceReadResult {
    let content = serde_json::json!({
        "guidelines": [
            {"code": "E2A", "title": "Clinical Safety Data Management", "scope": "Definitions, seriousness criteria, expedited reporting", "tool": "ich_org_get_pv_guidelines"},
            {"code": "E2B", "title": "Electronic Transmission of ICSRs", "scope": "E2B(R3) data elements, XML schema", "tool": "ich_org_get_e2b_data_elements"},
            {"code": "E2C", "title": "Periodic Benefit-Risk Evaluation Report", "scope": "PBRER structure, signal evaluation, benefit-risk assessment", "tool": "ich_org_get_pv_guidelines"},
            {"code": "E2D", "title": "Post-Approval Safety Data Management", "scope": "Post-marketing reporting obligations, literature monitoring", "tool": "ich_org_get_pv_guidelines"},
            {"code": "E2E", "title": "Pharmacovigilance Planning", "scope": "Safety specification, PV plan, risk minimization", "tool": "ich_org_get_pv_guidelines"},
            {"code": "E2F", "title": "Development Safety Update Report", "scope": "DSUR format, ongoing safety evaluation during development", "tool": "ich_org_get_pv_guidelines"},
            {"code": "M1", "title": "Medical Terminology (MedDRA)", "scope": "MedDRA hierarchy, SOC/HLGT/HLT/PT/LLT coding", "tool": "meddra_org_search_terms"},
        ],
    });
    resource_json(uri_str("nexvigilant://ich-guidelines"), &content)
}

fn read_station_health(registry: &ConfigRegistry) -> ResourceReadResult {
    let content = serde_json::json!({
        "status": "operational",
        "configs": registry.config_count(),
        "tools": registry.tool_count(),
        "version": env!("CARGO_PKG_VERSION"),
        "transport": ["Streamable HTTP (/mcp)", "SSE (/sse)", "REST (/rpc)", "Health (/health)"],
        "endpoint": "https://mcp.nexvigilant.com",
    });
    resource_json(uri_str("nexvigilant://station/health"), &content)
}

// ---------------------------------------------------------------------------
// Template-based resources
// ---------------------------------------------------------------------------

fn read_drug_resource(path: &str) -> Result<ResourceReadResult, String> {
    // path = "{name}/safety-profile" or "{name}/signals" or "{name}/label"
    let parts: Vec<&str> = path.splitn(2, '/').collect();
    if parts.len() < 2 {
        return Err(format!("Invalid drug resource URI. Expected: nexvigilant://drug/{{name}}/{{type}} where type is safety-profile, signals, or label"));
    }
    let drug_name = parts[0];
    let resource_type = parts[1];

    match resource_type {
        "safety-profile" => Ok(read_drug_safety_profile(drug_name)),
        "signals" => Ok(read_drug_signals(drug_name)),
        "label" => Ok(read_drug_label(drug_name)),
        "interactions" => Ok(read_drug_interactions(drug_name)),
        "regulatory-status" => Ok(read_drug_regulatory_status(drug_name)),
        other => Err(format!("Unknown drug resource type: {other}. Use: safety-profile, signals, label, interactions, or regulatory-status")),
    }
}

fn read_drug_safety_profile(drug: &str) -> ResourceReadResult {
    // Returns a structured guide telling the agent which tools to call
    // for a complete safety profile — NOT the data itself (that requires live API calls)
    let content = serde_json::json!({
        "drug": drug,
        "type": "safety-profile",
        "description": format!("Safety profile investigation guide for {drug}"),
        "data_sources": [
            {
                "source": "FDA FAERS",
                "description": "Adverse event reports from spontaneous reporting",
                "tool": "api_fda_gov_search_adverse_events",
                "params": {"drug": drug},
                "data": "Call this tool to get live FAERS data",
            },
            {
                "source": "DailyMed Label",
                "description": "FDA-approved drug labeling (adverse reactions section)",
                "tool": "dailymed_nlm_nih_gov_get_adverse_reactions",
                "params": {"drug_name": drug},
                "data": "Call this tool to get label ADRs",
            },
            {
                "source": "Signal Detection",
                "description": "Disproportionality analysis (PRR/ROR/IC/EBGM)",
                "tool": "calculate_nexvigilant_com_compute_disproportionality_table",
                "params": {"drug": drug},
                "data": "Call this tool after getting FAERS counts",
            },
            {
                "source": "Causality Assessment",
                "description": "Naranjo + WHO-UMC causality evaluation",
                "tools": ["calculate_nexvigilant_com_assess_naranjo_causality", "calculate_nexvigilant_com_assess_who_umc_causality"],
                "data": "Call after identifying specific drug-event pairs",
            },
            {
                "source": "PubMed Literature",
                "description": "Published case reports and signal literature",
                "tool": "pubmed_ncbi_nlm_nih_gov_search_signal_literature",
                "params": {"query": format!("{drug} adverse")},
                "data": "Call this tool for literature evidence",
            },
        ],
        "workflow": format!("Use nexvigilant_chart_course with course='drug-safety-profile' and drug='{drug}' for step-by-step guidance"),
    });
    resource_json(format!("nexvigilant://drug/{drug}/safety-profile"), &content)
}

fn read_drug_signals(drug: &str) -> ResourceReadResult {
    let content = serde_json::json!({
        "drug": drug,
        "type": "signals",
        "description": format!("Signal detection guide for {drug}"),
        "methods": {
            "PRR": {"tool": "calculate_nexvigilant_com_compute_prr", "threshold": "≥2 with chi²≥4 and N≥3"},
            "ROR": {"tool": "calculate_nexvigilant_com_compute_ror", "threshold": "lower 95% CI > 1"},
            "IC": {"tool": "calculate_nexvigilant_com_compute_ic", "threshold": "IC025 > 0"},
            "EBGM": {"tool": "calculate_nexvigilant_com_compute_ebgm", "threshold": "EB05 ≥ 2"},
        },
        "data_source": {
            "tool": "api_fda_gov_search_adverse_events",
            "params": {"drug": drug},
        },
        "workflow": format!("Use nexvigilant_chart_course with course='signal-investigation' and drug='{drug}' for full pipeline"),
    });
    resource_json(format!("nexvigilant://drug/{drug}/signals"), &content)
}

fn read_drug_label(drug: &str) -> ResourceReadResult {
    let content = serde_json::json!({
        "drug": drug,
        "type": "label",
        "description": format!("FDA drug label guide for {drug}"),
        "sections": {
            "adverse_reactions": {"tool": "dailymed_nlm_nih_gov_get_adverse_reactions", "params": {"drug_name": drug}},
            "boxed_warning": {"tool": "dailymed_nlm_nih_gov_get_boxed_warning", "params": {"drug_name": drug}},
            "contraindications": {"tool": "dailymed_nlm_nih_gov_get_contraindications", "params": {"drug_name": drug}},
            "drug_interactions": {"tool": "dailymed_nlm_nih_gov_get_drug_interactions", "params": {"drug_name": drug}},
            "full_label": {"tool": "dailymed_nlm_nih_gov_get_drug_label", "params": {"drug_name": drug}},
        },
    });
    resource_json(format!("nexvigilant://drug/{drug}/label"), &content)
}

fn read_ich_guideline(code: &str) -> ResourceReadResult {
    let content = serde_json::json!({
        "code": code.to_uppercase(),
        "type": "ich-guideline",
        "description": format!("ICH {} guideline reference", code.to_uppercase()),
        "tool": "ich_org_get_guideline",
        "params": {"guideline_id": code.to_uppercase()},
        "note": "Call the tool above to retrieve the full guideline content",
    });
    resource_json(format!("nexvigilant://guideline/ich/{code}"), &content)
}

fn read_agency(name: &str) -> ResourceReadResult {
    let content = serde_json::json!({
        "agency": name,
        "type": "regulatory-agency",
        "description": format!("Regulatory agency profile for {name}"),
        "note": "See nexvigilant://regulatory-agencies for full agency directory with tool prefixes and reporting timelines",
    });
    resource_json(format!("nexvigilant://agency/{name}"), &content)
}

fn read_domain_tools(registry: &ConfigRegistry, domain: &str) -> ResourceReadResult {
    let tools: Vec<Value> = registry
        .configs()
        .iter()
        .filter(|c| c.domain.contains(domain))
        .flat_map(|c| {
            c.tools.iter().map(|t| {
                serde_json::json!({
                    "name": t.name,
                    "description": t.description,
                })
            })
        })
        .collect();

    let content = serde_json::json!({
        "domain": domain,
        "tool_count": tools.len(),
        "tools": tools,
    });
    resource_json(format!("nexvigilant://domain/{domain}/tools"), &content)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn resource_json(uri: impl Into<String>, content: &Value) -> ResourceReadResult {
    ResourceReadResult {
        contents: vec![ResourceContent {
            uri: uri.into(),
            mime_type: Some("application/json".into()),
            text: Some(serde_json::to_string_pretty(content).unwrap_or_default()),
        }],
    }
}

fn uri_str(s: &str) -> String {
    s.to_string()
}

// ---------------------------------------------------------------------------
// New static resources (batch 2)
// ---------------------------------------------------------------------------

fn read_meddra_guide() -> ResourceReadResult {
    let content = serde_json::json!({
        "name": "MedDRA — Medical Dictionary for Regulatory Activities",
        "hierarchy": [
            {"level": "SOC", "name": "System Organ Class", "count": 27, "description": "Highest level — body system or etiology (e.g., 'Cardiac disorders')"},
            {"level": "HLGT", "name": "High Level Group Term", "description": "Superordinate grouping of HLTs"},
            {"level": "HLT", "name": "High Level Term", "description": "Superordinate grouping of PTs"},
            {"level": "PT", "name": "Preferred Term", "count": "~27,000", "description": "Primary coding level — single medical concept (e.g., 'Myocardial infarction')"},
            {"level": "LLT", "name": "Lowest Level Term", "count": "~83,000", "description": "Synonym or sub-concept of a PT"},
        ],
        "smqs": "Standardised MedDRA Queries — pre-defined groupings for safety topics (e.g., 'Hepatic disorders' SMQ captures all liver-related PTs)",
        "tools": {
            "search_terms": "meddra_org_search_terms",
            "get_hierarchy": "meddra_org_get_term_hierarchy",
            "get_smq": "meddra_org_get_smq",
            "get_soc_terms": "meddra_org_get_soc_terms",
        },
        "coding_rules": [
            "Code to the most specific PT that matches the reported term",
            "Use LLT for verbatim capture, PT for analysis",
            "Multi-axiality: one PT may belong to multiple SOCs (primary SOC used for analysis)",
            "Version consistency: use same MedDRA version throughout a study/report",
        ],
    });
    resource_json(uri_str("nexvigilant://meddra"), &content)
}

fn read_reporting_timelines() -> ResourceReadResult {
    let content = serde_json::json!({
        "title": "Global Expedited Reporting Timelines",
        "timelines": [
            {"agency": "FDA", "serious_unexpected": "15 calendar days", "serious_expected": "Periodic (PBRER)", "non_serious": "Annual", "format": "E2B(R3) via FAERS"},
            {"agency": "EMA", "serious_unexpected": "15 calendar days", "serious_expected": "90 calendar days", "non_serious": "Periodic", "format": "E2B(R3) via EudraVigilance"},
            {"agency": "PMDA", "serious_unexpected": "15 calendar days (known), 30 days (unknown)", "serious_expected": "Periodic", "non_serious": "Annual", "format": "E2B(R3) via PMDA gateway"},
            {"agency": "TGA", "serious_unexpected": "15 calendar days", "serious_expected": "PSUR cycle", "non_serious": "Annual", "format": "E2B(R3)"},
            {"agency": "MHRA", "serious_unexpected": "15 calendar days", "serious_expected": "PSUR cycle", "non_serious": "Annual", "format": "E2B(R3)"},
            {"agency": "Swissmedic", "serious_unexpected": "15 calendar days", "serious_expected": "PSUR cycle", "non_serious": "Annual", "format": "E2B(R3)"},
            {"agency": "Health Canada", "serious_unexpected": "15 calendar days", "serious_expected": "PSUR cycle", "non_serious": "Annual", "format": "E2B(R3)"},
        ],
        "key_definitions": {
            "Day 0": "Date the MAH first becomes aware of the case",
            "Clock start": "Day the minimum information criteria are met (identifiable patient, identifiable reporter, suspect drug, adverse event)",
            "Serious": "Per ICH E2A: death, life-threatening, hospitalization, disability, congenital anomaly, medically important",
            "Unexpected": "Not consistent with the applicable product information (e.g., not in the label/SmPC)",
        },
        "tool": "calculate_nexvigilant_com_compute_reporting_rate",
    });
    resource_json(uri_str("nexvigilant://reporting-timelines"), &content)
}

fn read_faers_guide() -> ResourceReadResult {
    let content = serde_json::json!({
        "name": "FDA Adverse Event Reporting System (FAERS)",
        "description": "FAERS is the FDA's spontaneous reporting database containing over 20 million adverse event reports from healthcare professionals, consumers, and manufacturers.",
        "database_size": "20M+ reports (2004-present, quarterly updates)",
        "report_types": ["Expedited (15-day)", "Periodic", "Direct (MedWatch)"],
        "key_fields": {
            "patient": "Age, sex, weight",
            "drug": "Name, indication, route, dose, role (suspect/concomitant/interacting)",
            "reaction": "MedDRA PT-coded adverse events",
            "outcome": "Death, life-threatening, hospitalization, disability, congenital anomaly, other serious, required intervention",
            "reporter": "Physician, pharmacist, consumer, other health professional",
        },
        "tools": {
            "search": "api_fda_gov_search_adverse_events",
            "drug_events": "faers_nexvigilant_com_faers_drug_events",
            "compare": "faers_nexvigilant_com_faers_compare_drugs",
            "disproportionality": "faers_nexvigilant_com_faers_disproportionality",
            "geographic": "faers_nexvigilant_com_faers_geographic_divergence",
            "polypharmacy": "faers_nexvigilant_com_faers_polypharmacy",
            "signal_velocity": "faers_nexvigilant_com_faers_signal_velocity",
        },
        "limitations": [
            "Voluntary reporting — underreporting is significant (estimated 1-10% of events reported)",
            "No denominator — cannot compute incidence rates (use disproportionality instead)",
            "Duplicates — same event may be reported multiple times",
            "Reporting bias — serious and novel events are over-represented",
            "Stimulated reporting — media attention or regulatory action increases reports temporarily",
        ],
        "best_practices": [
            "Always use disproportionality (PRR/ROR/IC/EBGM) not raw counts",
            "Apply N≥3 minimum case count threshold",
            "Compare multiple disproportionality measures for consensus",
            "Check DailyMed label to distinguish known vs new signals",
            "Account for Weber effect (increased reporting in first 2 years after approval)",
        ],
    });
    resource_json(uri_str("nexvigilant://faers-guide"), &content)
}

fn read_seriousness_criteria() -> ResourceReadResult {
    let content = serde_json::json!({
        "source": "ICH E2A — Clinical Safety Data Management: Definitions and Standards for Expedited Reporting",
        "criteria": [
            {"criterion": "Death", "description": "The adverse event resulted in death", "code": "DE", "always_serious": true},
            {"criterion": "Life-threatening", "description": "The patient was at immediate risk of death at the time of the event (NOT hypothetical risk)", "code": "LT", "always_serious": true},
            {"criterion": "Hospitalization", "description": "Required inpatient hospitalization or prolongation of existing hospitalization", "code": "HO", "always_serious": true, "note": "Emergency room visits alone do not qualify unless admission follows"},
            {"criterion": "Disability/Incapacity", "description": "Resulted in persistent or significant disability or substantial disruption of ability to conduct normal life functions", "code": "DS", "always_serious": true},
            {"criterion": "Congenital anomaly/Birth defect", "description": "Congenital anomaly or birth defect in offspring of patient exposed to drug", "code": "CA", "always_serious": true},
            {"criterion": "Medically important", "description": "May not be immediately life-threatening or result in death/hospitalization, but may jeopardize the patient or require medical/surgical intervention", "code": "OT", "always_serious": true, "note": "Requires medical judgment — examples: bronchospasm, blood dyscrasias, seizures, drug-induced liver injury"},
        ],
        "tool": "calculate_nexvigilant_com_classify_seriousness",
        "key_principle": "If ANY criterion is met, the event is SERIOUS. Seriousness is not the same as severity (severity = mild/moderate/severe).",
    });
    resource_json(uri_str("nexvigilant://seriousness-criteria"), &content)
}

fn read_signal_detection_workflow() -> ResourceReadResult {
    let content = serde_json::json!({
        "title": "Signal Detection Methodology",
        "phases": [
            {
                "phase": 1, "name": "Data Mining",
                "description": "Systematically search safety databases for drug-event combinations that occur more frequently than expected",
                "tools": ["api_fda_gov_search_adverse_events", "faers_nexvigilant_com_faers_drug_events"],
            },
            {
                "phase": 2, "name": "Disproportionality Analysis",
                "description": "Apply statistical measures to quantify how disproportionate the reporting is",
                "methods": {
                    "PRR": {"tool": "calculate_nexvigilant_com_compute_prr", "type": "frequentist"},
                    "ROR": {"tool": "calculate_nexvigilant_com_compute_ror", "type": "frequentist"},
                    "IC": {"tool": "calculate_nexvigilant_com_compute_ic", "type": "Bayesian"},
                    "EBGM": {"tool": "calculate_nexvigilant_com_compute_ebgm", "type": "Bayesian (shrinkage)"},
                },
                "consensus_rule": "Signal if ≥2 of 4 methods exceed their thresholds",
            },
            {
                "phase": 3, "name": "Signal Validation",
                "description": "Verify the statistical signal with clinical and scientific evidence",
                "tools": ["dailymed_nlm_nih_gov_get_adverse_reactions", "pubmed_ncbi_nlm_nih_gov_search_case_reports"],
                "checks": ["Temporal plausibility", "Biological plausibility", "Dose-response", "Dechallenge/rechallenge", "Literature consistency"],
            },
            {
                "phase": 4, "name": "Signal Assessment",
                "description": "Evaluate the strength, clinical impact, and regulatory implications",
                "tools": ["calculate_nexvigilant_com_assess_naranjo_causality", "calculate_nexvigilant_com_assess_who_umc_causality"],
            },
            {
                "phase": 5, "name": "Regulatory Action",
                "description": "Determine appropriate regulatory response based on signal strength and public health impact",
                "actions": ["Label update", "Dear Healthcare Professional letter", "REMS modification", "Risk communication", "Product withdrawal"],
            },
        ],
        "guided_course": "Use nexvigilant_chart_course with course='signal-investigation' for step-by-step execution",
    });
    resource_json(uri_str("nexvigilant://signal-detection-workflow"), &content)
}

fn read_causality_frameworks() -> ResourceReadResult {
    let content = serde_json::json!({
        "frameworks": {
            "naranjo": {
                "name": "Naranjo Adverse Drug Reaction Probability Scale",
                "questions": [
                    "1. Are there previous conclusive reports on this reaction?",
                    "2. Did the adverse event appear after the suspected drug was given?",
                    "3. Did the adverse reaction improve when the drug was discontinued?",
                    "4. Did the adverse reaction reappear when the drug was readministered?",
                    "5. Are there alternative causes that could have caused the reaction?",
                    "6. Did the reaction reappear when a placebo was given?",
                    "7. Was the drug detected in the blood in toxic concentrations?",
                    "8. Was the reaction more severe when the dose was increased?",
                    "9. Did the patient have a similar reaction to the same or similar drug?",
                    "10. Was the adverse event confirmed by any objective evidence?",
                ],
                "scoring": {"yes": "+1 or +2", "no": "0 or -1", "unknown": "0"},
                "categories": {"definite": "≥9", "probable": "5-8", "possible": "1-4", "doubtful": "≤0"},
                "tool": "calculate_nexvigilant_com_assess_naranjo_causality",
            },
            "who_umc": {
                "name": "WHO-UMC Causality Assessment System",
                "categories": [
                    {"category": "Certain", "criteria": "Plausible time relationship, cannot be explained by disease, response to withdrawal clinically plausible, rechallenge if necessary"},
                    {"category": "Probable/Likely", "criteria": "Reasonable time relationship, unlikely attributable to disease, clinically reasonable response to withdrawal"},
                    {"category": "Possible", "criteria": "Reasonable time relationship, could also be explained by disease or other drugs"},
                    {"category": "Unlikely", "criteria": "Improbable time relationship, disease or other drugs provide plausible explanations"},
                    {"category": "Conditional/Unclassified", "criteria": "Event reported, more data needed for assessment"},
                    {"category": "Unassessable/Unclassifiable", "criteria": "Report insufficient or contradictory"},
                ],
                "tool": "calculate_nexvigilant_com_assess_who_umc_causality",
            },
            "bradford_hill": {
                "name": "Bradford Hill Criteria for Causation",
                "viewpoints": [
                    "Strength of association", "Consistency", "Specificity",
                    "Temporality", "Biological gradient (dose-response)",
                    "Plausibility", "Coherence", "Experiment", "Analogy",
                ],
                "note": "Used for epidemiological evidence, not individual case assessment",
            },
            "rucam": {
                "name": "Roussel Uclaf Causality Assessment Method",
                "scope": "Specific to drug-induced liver injury (DILI)",
                "tool": "agent_intel_nexvigilant_com_causality_rucam",
            },
        },
    });
    resource_json(uri_str("nexvigilant://causality-frameworks"), &content)
}

fn read_pharma_directory() -> ResourceReadResult {
    let companies = [
        "abbvie", "alexion", "amgen", "astellas", "astrazeneca", "bayer",
        "biogen", "bms", "boehringer-ingelheim", "celltrion", "cipla", "cspc",
        "daiichisankyo", "drreddys", "eisai", "gilead", "gsk", "hengrui",
        "incyte", "ipsen", "jazzpharma", "jnj", "lilly", "lupin", "menarini",
        "merck", "moderna", "novartis", "novonordisk", "pfizer", "regeneron",
        "roche", "samsungbioepis", "sanofi", "seagen", "servier", "sunpharma",
        "takeda", "tevapharm", "ucb", "vrtx",
    ];
    let content = serde_json::json!({
        "total_companies": companies.len(),
        "companies": companies.iter().map(|c| {
            serde_json::json!({
                "id": c,
                "tools_prefix": format!("www_{}_com", c.replace('-', "_")),
                "available_tools": ["search_products", "get_portfolio", "get_pipeline", "get_safety_profile", "get_head_to_head", "get_recalls", "get_labeling_changes"],
                "resource_uri": format!("nexvigilant://pharma/{c}"),
            })
        }).collect::<Vec<_>>(),
    });
    resource_json(uri_str("nexvigilant://pharma-directory"), &content)
}

fn read_benefit_risk_methods() -> ResourceReadResult {
    let content = serde_json::json!({
        "methods": {
            "QBRI": {
                "name": "Quantitative Benefit-Risk Index",
                "description": "Weighted composite score balancing therapeutic benefit against safety risk",
                "tools": [
                    "benefit_risk_nexvigilant_com_compute_qbri",
                    "benefit_risk_nexvigilant_com_compute_qbr",
                    "benefit_risk_nexvigilant_com_compute_therapeutic_window",
                ],
            },
            "ICH_E2C": {
                "name": "Periodic Benefit-Risk Evaluation (PBRER)",
                "description": "Structured periodic assessment per ICH E2C(R2) — integrates cumulative safety data with benefit evidence",
                "sections": ["Executive summary", "Safety specification", "Signal evaluation", "Benefit evaluation", "Integrated benefit-risk analysis"],
            },
            "EU_RMP": {
                "name": "EU Risk Management Plan",
                "description": "Structured risk management per GVP Module V — safety specification, pharmacovigilance plan, risk minimisation measures",
                "tool": "www_ema_europa_eu_get_rmp_summary",
            },
        },
    });
    resource_json(uri_str("nexvigilant://benefit-risk-methods"), &content)
}

fn read_micrograms_guide() -> ResourceReadResult {
    let content = serde_json::json!({
        "name": "PV Decision Trees (Micrograms)",
        "description": "Atomic, self-testing decision programs that execute in sub-microsecond time. Each microgram encodes one PV decision as a YAML decision tree.",
        "count": 969,
        "chain_count": 184,
        "examples": [
            {"name": "case-triage", "description": "Route incoming case to correct processing pathway"},
            {"name": "prr-signal", "description": "Evaluate PRR threshold for signal detection"},
            {"name": "naranjo-quick", "description": "Quick Naranjo causality assessment"},
            {"name": "seriousness-to-deadline", "description": "Map seriousness criteria to reporting deadline"},
            {"name": "causality-to-action", "description": "Convert causality assessment to regulatory action"},
        ],
        "tool": "microgram_nexvigilant_com_run_microgram",
        "chain_tool": "microgram_nexvigilant_com_run_chain",
        "list_tool": "microgram_nexvigilant_com_list_micrograms",
    });
    resource_json(uri_str("nexvigilant://micrograms"), &content)
}

// ---------------------------------------------------------------------------
// New template-based resources (batch 2)
// ---------------------------------------------------------------------------

fn read_drug_interactions(drug: &str) -> ResourceReadResult {
    let content = serde_json::json!({
        "drug": drug,
        "type": "interactions",
        "description": format!("Drug interaction investigation guide for {drug}"),
        "data_sources": {
            "rxnav_interactions": {"tool": "rxnav_nlm_nih_gov_get_interactions", "params": {"drug": drug}},
            "drugbank_interactions": {"tool": "go_drugbank_com_get_interactions", "params": {"drug_name": drug}},
            "label_interactions": {"tool": "dailymed_nlm_nih_gov_get_drug_interactions", "params": {"drug_name": drug}},
            "contraindications": {"tool": "dailymed_nlm_nih_gov_get_contraindications", "params": {"drug_name": drug}},
            "pharmgkb_genes": {"tool": "api_pharmgkb_org_get_drug_genes", "params": {"drug_name": drug}},
        },
    });
    resource_json(format!("nexvigilant://drug/{drug}/interactions"), &content)
}

fn read_drug_regulatory_status(drug: &str) -> ResourceReadResult {
    let content = serde_json::json!({
        "drug": drug,
        "type": "regulatory-status",
        "description": format!("Regulatory status guide for {drug}"),
        "data_sources": {
            "fda_approval": {"tool": "accessdata_fda_gov_get_approval_history", "params": {"drug": drug}},
            "fda_labeling_changes": {"tool": "accessdata_fda_gov_get_labeling_changes", "params": {"drug": drug}},
            "fda_rems": {"tool": "accessdata_fda_gov_get_rems", "params": {"drug": drug}},
            "fda_recalls": {"tool": "accessdata_fda_gov_search_recalls", "params": {"drug": drug}},
            "ema_epar": {"tool": "www_ema_europa_eu_get_epar", "params": {"product": drug}},
            "ema_safety_signals": {"tool": "www_ema_europa_eu_get_safety_signals", "params": {"substance": drug}},
            "safety_communications": {"tool": "www_fda_gov_search_safety_communications", "params": {"drug": drug}},
        },
    });
    resource_json(format!("nexvigilant://drug/{drug}/regulatory-status"), &content)
}

fn read_pharma_company(company: &str) -> ResourceReadResult {
    let prefix = format!("www_{}_com", company.replace('-', "_"));
    let content = serde_json::json!({
        "company": company,
        "type": "pharma-company",
        "tools": {
            "search_products": format!("{prefix}_search_products"),
            "get_portfolio": format!("{prefix}_get_portfolio"),
            "get_pipeline": format!("{prefix}_get_pipeline"),
            "get_safety_profile": format!("{prefix}_get_safety_profile"),
            "get_head_to_head": format!("{prefix}_get_head_to_head"),
            "get_recalls": format!("{prefix}_get_recalls"),
            "get_labeling_changes": format!("{prefix}_get_labeling_changes"),
        },
    });
    resource_json(format!("nexvigilant://pharma/{company}"), &content)
}

fn read_meddra_term(term: &str) -> ResourceReadResult {
    let content = serde_json::json!({
        "term": term,
        "type": "meddra-term",
        "description": format!("MedDRA hierarchy lookup for '{term}'"),
        "tools": {
            "search": {"tool": "meddra_org_search_terms", "params": {"query": term}},
            "hierarchy": {"tool": "meddra_org_get_term_hierarchy", "params": {"term": term}},
        },
    });
    resource_json(format!("nexvigilant://meddra/{term}"), &content)
}

fn read_course_guide(course: &str) -> ResourceReadResult {
    // Delegate to the prompts module for the detailed workflow
    let arguments = serde_json::json!({"drug": "{drug_name}"});
    match crate::prompts::get_prompt(course, &arguments) {
        Ok(result) => {
            let text = result.messages.first()
                .map(|m| match &m.content { crate::prompts::PromptContent::Text { text } => text.clone() })
                .unwrap_or_default();
            let content = serde_json::json!({
                "course": course,
                "type": "research-course",
                "description": result.description,
                "workflow": text,
                "note": "Replace {drug_name} with the actual drug name. Or use the prompt directly: prompts/get with name='{course}' and arguments.drug='{drug_name}'",
            });
            resource_json(format!("nexvigilant://course/{course}"), &content)
        }
        Err(_) => {
            let content = serde_json::json!({
                "course": course,
                "error": format!("Unknown course: {course}"),
                "available": ["drug-safety-profile", "signal-investigation", "causality-assessment", "benefit-risk-assessment", "regulatory-intelligence", "competitive-landscape"],
            });
            resource_json(format!("nexvigilant://course/{course}"), &content)
        }
    }
}
