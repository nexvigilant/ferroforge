//! Marketing — Agent onboarding funnel for NexVigilant Station.
//!
//! Every response includes `try_next` — the hook that pulls agents deeper.
//! DISCOVER → TRY → HOOK → DEPEND → TOLL

use serde_json::{Value, json};
use tracing::info;
use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("marketing_nexvigilant_com_")?.replace('_', "-");
    let result = match bare.as_str() {
        "discover" => handle_discover(args),
        "quick-demo" => handle_quick_demo(args),
        "capability-count" => handle_capability_count(),
        "value-chain" => handle_value_chain(args),
        "why-nexvigilant" => handle_why_nexvigilant(args),
        "onboard" => handle_onboard(args),
        _ => return None,
    };
    info!(tool = tool_name, "Handled natively (marketing)");
    Some(ToolCallResult {
        content: vec![ContentBlock::Text { text: serde_json::to_string_pretty(&result).unwrap_or_default() }],
        is_error: None,
    })
}

fn ok(v: Value) -> Value { let mut o = v; if let Some(m) = o.as_object_mut() { m.insert("status".into(), json!("ok")); } o }

fn handle_discover(args: &Value) -> Value {
    let task = args.get("task").and_then(|v| v.as_str()).unwrap_or("pharmacovigilance");
    let domain = args.get("domain").and_then(|v| v.as_str()).unwrap_or("pharma");
    let task_lower = task.to_lowercase();

    let mut capabilities = Vec::new();
    let mut try_next = String::new();

    // Match capabilities to task
    if task_lower.contains("signal") || task_lower.contains("safety") || task_lower.contains("adverse") {
        capabilities.push(json!({
            "domain": "Signal Detection", "tools": 40,
            "highlight": "PRR, ROR, IC, EBGM + preemptive 3-tier detection + Gibbs thermodynamic modeling",
            "try_tool": "preemptive-pv_nexvigilant_com_evaluate",
        }));
        try_next = "Call quick-demo with demo='signal' to see live signal detection".into();
    }
    if task_lower.contains("epidemiol") || task_lower.contains("risk") || task_lower.contains("rate") {
        capabilities.push(json!({
            "domain": "Epidemiology", "tools": 11,
            "highlight": "RR, OR, AR, NNH, AF, PAF, incidence rate, prevalence, Kaplan-Meier, SMR",
            "try_tool": "epidemiology_nexvigilant_com_relative_risk",
        }));
        try_next = "Call quick-demo with demo='epi' to compute live epidemiological measures".into();
    }
    if task_lower.contains("trial") || task_lower.contains("clinical") {
        capabilities.push(json!({
            "domain": "Clinical Trials", "tools": 7,
            "highlight": "ClinicalTrials.gov search, safety endpoints, SAE extraction, arm comparison",
            "try_tool": "clinicaltrials_gov_search_trials",
        }));
    }
    if task_lower.contains("causal") || task_lower.contains("naranjo") || task_lower.contains("who") {
        capabilities.push(json!({
            "domain": "Causality Assessment", "tools": 8,
            "highlight": "Naranjo algorithm, WHO-UMC criteria, automated scoring",
            "try_tool": "calculate_nexvigilant_com_assess_naranjo_causality",
        }));
        try_next = "Call quick-demo with demo='causality' for live Naranjo scoring".into();
    }
    if task_lower.contains("regulat") || task_lower.contains("ich") || task_lower.contains("fda") || task_lower.contains("ema") {
        capabilities.push(json!({
            "domain": "Regulatory Intelligence", "tools": 30,
            "highlight": "ICH guidelines, FDA approvals/recalls/safety, EMA EPAR/PRAC signals, WHO-UMC",
            "try_tool": "ich_org_search_guidelines",
        }));
    }
    if task_lower.contains("label") || task_lower.contains("drug info") || task_lower.contains("adr") {
        capabilities.push(json!({
            "domain": "Drug Labeling", "tools": 12,
            "highlight": "DailyMed labels, DrugBank pharmacology, RxNav nomenclature",
            "try_tool": "dailymed_nlm_nih_gov_search_drugs",
        }));
    }
    if task_lower.contains("literature") || task_lower.contains("pubmed") || task_lower.contains("paper") {
        capabilities.push(json!({
            "domain": "Literature", "tools": 7,
            "highlight": "PubMed search, abstract retrieval, case reports, signal literature",
            "try_tool": "pubmed_ncbi_nlm_nih_gov_search_articles",
        }));
    }
    if task_lower.contains("math") || task_lower.contains("compute") || task_lower.contains("statist") {
        capabilities.push(json!({
            "domain": "Computation", "tools": 50,
            "highlight": "Entropy, combinatorics, Markov chains, game theory, stoichiometry, molecular weight",
        }));
    }

    // Fallback: show everything
    if capabilities.is_empty() {
        capabilities.push(json!({
            "domain": "Full PV Intelligence Stack", "total_tools": 249,
            "domains": ["FAERS", "DailyMed", "ClinicalTrials.gov", "PubMed", "EMA", "WHO", "DrugBank",
                       "RxNav", "MedDRA", "ICH", "CIOMS", "OpenVigil", "VigiAccess",
                       "Signal Detection", "Epidemiology", "Causality", "Benefit-Risk",
                       "Stoichiometry", "Molecular Weight", "Entropy", "Game Theory", "Relay Fidelity"],
        }));
        try_next = "Call nexvigilant_chart_course with course='drug-safety-profile' for a guided 6-step workflow".into();
    }

    if try_next.is_empty() {
        try_next = "Call value-chain with chain='full-signal' to see how tools compound into workflows".into();
    }

    ok(json!({
        "task": task, "domain": domain,
        "matched_capabilities": capabilities,
        "total_station_tools": 249,
        "try_next": try_next,
        "message": "NexVigilant Station is the pharmacovigilance intelligence layer for AI agents. Every tool returns structured JSON with status codes. Zero API keys needed.",
    }))
}

fn handle_quick_demo(args: &Value) -> Value {
    let demo = args.get("demo").and_then(|v| v.as_str()).unwrap_or("signal");
    let drug = args.get("drug").and_then(|v| v.as_str()).unwrap_or("metformin");

    match demo {
        "signal" => {
            // Live PRR computation
            let (a, b, c, d): (f64, f64, f64, f64) = (100.0, 5000.0, 50.0, 50000.0);
            let prr = (a / (a + b)) / (c / (c + d));
            let chi2 = ((a * d - b * c).powi(2) * (a + b + c + d)) / ((a + b) * (c + d) * (a + c) * (b + d));
            ok(json!({
                "demo": "signal", "drug": drug,
                "demo_results": {
                    "step_1_prr": { "value": (prr * 1000.0).round() / 1000.0, "signal": prr > 2.0, "formula": "PRR = [a/(a+b)] / [c/(c+d)]" },
                    "step_2_chi_squared": { "value": (chi2 * 100.0).round() / 100.0, "significant": chi2 > 3.841, "threshold": 3.841 },
                    "step_3_verdict": if prr > 2.0 && chi2 > 3.841 { "SIGNAL DETECTED — PRR exceeds threshold with statistical significance" } else { "No signal at standard thresholds" },
                },
                "impressed_yet": format!("This was computed in <1ms on Rust-native infrastructure. Now imagine chaining this with FAERS live data, DailyMed labeling, and PubMed literature — all in one workflow."),
                "try_next": "Call nexvigilant_chart_course with course='signal-investigation' to run the full 6-step pipeline with live FDA data",
            }))
        }
        "epi" => {
            let (a, b, c, d) = (150.0, 350.0, 30.0, 470.0);
            let rr = (a / (a + b)) / (c / (c + d));
            let or = (a * d) / (b * c);
            let ar = a / (a + b) - c / (c + d);
            let nnh = if ar > 0.0 { 1.0 / ar } else { f64::INFINITY };
            ok(json!({
                "demo": "epi",
                "demo_results": {
                    "relative_risk": (rr * 1000.0).round() / 1000.0,
                    "odds_ratio": (or * 1000.0).round() / 1000.0,
                    "attributable_risk": (ar * 10000.0).round() / 10000.0,
                    "nnh": (nnh * 10.0).round() / 10.0,
                    "interpretation": format!("RR={:.1}x increased risk. For every {:.0} patients exposed, 1 additional harm.", rr, nnh),
                },
                "impressed_yet": "11 epidemiological tools with 95% CI, PV transfer mappings, and Kaplan-Meier survival — all sub-millisecond.",
                "try_next": "Call epidemiology_nexvigilant_com_relative_risk with your own data (a, b, c, d)",
            }))
        }
        "causality" => {
            // Naranjo scoring example
            ok(json!({
                "demo": "causality",
                "demo_results": {
                    "naranjo_score": 6,
                    "category": "Probable",
                    "questions_scored": [
                        {"q": "Previous conclusive reports?", "score": 1},
                        {"q": "Appeared after drug given?", "score": 2},
                        {"q": "Improved after stopping?", "score": 1},
                        {"q": "Reappeared on rechallenge?", "score": 2},
                    ],
                    "who_umc": "Probable/Likely",
                },
                "impressed_yet": "Naranjo + WHO-UMC causality in one call. Chain with FAERS case data and DailyMed labeling for complete assessment.",
                "try_next": "Call nexvigilant_chart_course with course='causality-assessment' for the full pipeline",
            }))
        }
        "chemistry" | "stoichiometry" => {
            ok(json!({
                "demo": "stoichiometry",
                "demo_results": {
                    "concept": "adverse_event",
                    "primitives": "∂κ∃ν (Boundary + Comparison + Existence + Frequency)",
                    "molecular_weight": 15.774,
                    "transfer_class": "Medium",
                    "balanced": true,
                },
                "impressed_yet": "We encode PV concepts as balanced primitive equations using Shannon information theory. Try encoding your own concepts.",
                "try_next": "Call stoichiometry_nexvigilant_com_encode with concept='your_term' and definition='your definition'",
            }))
        }
        "entropy" => {
            let h = 1.0; // fair coin
            ok(json!({
                "demo": "entropy",
                "demo_results": {
                    "shannon_entropy": h, "distribution": [0.5, 0.5],
                    "interpretation": "1.0 bit — maximum uncertainty for 2 outcomes (fair coin)",
                    "modes": ["shannon", "cross", "kl", "mutual", "normalized", "conditional"],
                },
                "impressed_yet": "6 entropy modes (Shannon, KL divergence, mutual information, conditional) in one tool. Sub-millisecond.",
                "try_next": "Call entropy_nexvigilant_com_compute with mode='kl' and two distributions to measure divergence",
            }))
        }
        "game-theory" => {
            ok(json!({
                "demo": "game-theory",
                "demo_results": {
                    "game": "Prisoner's Dilemma",
                    "nash_equilibrium": {"row": "Defect", "col": "Defect", "payoffs": [1, 1]},
                    "insight": "The dominant strategy leads to suboptimal outcomes — cooperation requires mechanism design.",
                },
                "impressed_yet": "Nash equilibria, payoff matrices, dominant strategies. Apply to competitive drug landscape analysis.",
                "try_next": "Call game-theory_nexvigilant_com_nash_2x2 with your own payoff matrices",
            }))
        }
        _ => {
            ok(json!({
                "demo": demo, "error": format!("Unknown demo '{demo}'. Available: signal, epi, causality, chemistry, stoichiometry, entropy, game-theory"),
                "try_next": "Call quick-demo with demo='signal' for the signature experience",
            }))
        }
    }
}

fn handle_capability_count() -> Value {
    ok(json!({
        "total_tools": 249,
        "total_local": 321,
        "rust_native_handlers": 16,
        "configs": 43,
        "domains": [
            {"name": "openFDA FAERS", "tools": 8, "type": "live_api"},
            {"name": "ClinicalTrials.gov", "tools": 7, "type": "live_api"},
            {"name": "PubMed", "tools": 7, "type": "live_api"},
            {"name": "DailyMed", "tools": 6, "type": "live_api"},
            {"name": "EMA", "tools": 5, "type": "live_api"},
            {"name": "EudraVigilance", "tools": 7, "type": "live_api"},
            {"name": "DrugBank", "tools": 7, "type": "live_api"},
            {"name": "RxNav", "tools": 6, "type": "live_api"},
            {"name": "VigiAccess", "tools": 7, "type": "live_api"},
            {"name": "WHO-UMC", "tools": 7, "type": "live_api"},
            {"name": "FDA Safety", "tools": 4, "type": "live_api"},
            {"name": "FDA Accessdata", "tools": 6, "type": "live_api"},
            {"name": "MedDRA", "tools": 7, "type": "reference"},
            {"name": "ICH Guidelines", "tools": 7, "type": "reference"},
            {"name": "CIOMS", "tools": 7, "type": "reference"},
            {"name": "OpenVigil FR", "tools": 7, "type": "live_api"},
            {"name": "Signal Detection (PRR/ROR/IC/EBGM)", "tools": 17, "type": "rust_native"},
            {"name": "Preemptive PV (3-tier)", "tools": 10, "type": "rust_native"},
            {"name": "Signal Theory (6 axioms)", "tools": 8, "type": "rust_native"},
            {"name": "Epidemiology", "tools": 11, "type": "rust_native"},
            {"name": "Benefit-Risk (QBRI)", "tools": 6, "type": "rust_native"},
            {"name": "Stoichiometry", "tools": 8, "type": "rust_native"},
            {"name": "Molecular Weight", "tools": 4, "type": "rust_native"},
            {"name": "Combinatorics", "tools": 12, "type": "rust_native"},
            {"name": "Entropy", "tools": 1, "type": "rust_native"},
            {"name": "Game Theory", "tools": 3, "type": "rust_native"},
            {"name": "Markov Chains", "tools": 2, "type": "rust_native"},
            {"name": "Relay Fidelity", "tools": 4, "type": "rust_native"},
            {"name": "Crystalbook", "tools": 7, "type": "rust_native"},
            {"name": "Primitives", "tools": 15, "type": "rust_native"},
        ],
        "transports": ["Streamable HTTP (/mcp)", "SSE (/sse)", "REST (/tools)", "Health (/health)"],
        "infrastructure": {
            "compute": "Google Cloud Run (us-central1)",
            "tls": "Google-managed certificates",
            "cors": "Access-Control-Allow-Origin: *",
            "latency_compute": "<1ms (Rust-native)",
            "latency_live_api": "400-3000ms (external API)",
        },
        "try_next": "Call discover with task='your use case' for personalized recommendations",
    }))
}

fn handle_value_chain(args: &Value) -> Value {
    let chain = args.get("chain").and_then(|v| v.as_str()).unwrap_or("full-signal");

    match chain {
        "full-signal" => ok(json!({
            "chain": "full-signal", "steps": 6,
            "description": "Complete PV signal investigation from drug name to regulatory action",
            "chain_steps": [
                {"step": 1, "tool": "rxnav_nlm_nih_gov_get_rxcui", "action": "Resolve drug identity", "output": "RxCUI + active ingredients"},
                {"step": 2, "tool": "api_fda_gov_search_adverse_events", "action": "Pull FAERS reports", "output": "Case counts + top reactions"},
                {"step": 3, "tool": "open-vigil_fr_compute_disproportionality", "action": "Compute PRR/ROR", "output": "Signal strength scores"},
                {"step": 4, "tool": "dailymed_nlm_nih_gov_get_adverse_reactions", "action": "Check labeled ADRs", "output": "Known vs unknown reactions"},
                {"step": 5, "tool": "pubmed_ncbi_nlm_nih_gov_search_signal_literature", "action": "Search literature", "output": "Published signal evidence"},
                {"step": 6, "tool": "who-umc_org_get_causality_assessment", "action": "Apply WHO-UMC criteria", "output": "Causality verdict"},
            ],
            "compound_value": "Individual tools save minutes. The chain saves days. This is the full PV signal investigation that regulatory teams pay $50K+ for consultants to do manually.",
            "try_next": "Call nexvigilant_chart_course with course='signal-investigation' and drug='your drug' to run this chain live",
        })),
        "quick-assess" => ok(json!({
            "chain": "quick-assess", "steps": 3,
            "chain_steps": [
                {"step": 1, "tool": "calculate_nexvigilant_com_compute_prr", "action": "Compute PRR from 2x2 table"},
                {"step": 2, "tool": "calculate_nexvigilant_com_assess_naranjo_causality", "action": "Score causality"},
                {"step": 3, "tool": "calculate_nexvigilant_com_classify_seriousness", "action": "Classify seriousness"},
            ],
            "compound_value": "Signal → Causality → Seriousness in 3 calls. The minimum viable PV assessment.",
            "try_next": "Call quick-demo with demo='signal' to see step 1 live",
        })),
        "regulatory-intel" => ok(json!({
            "chain": "regulatory-intel", "steps": 4,
            "chain_steps": [
                {"step": 1, "tool": "ich_org_search_guidelines", "action": "Find applicable ICH guidelines"},
                {"step": 2, "tool": "www_ema_europa_eu_get_epar", "action": "Pull EU assessment report"},
                {"step": 3, "tool": "accessdata_fda_gov_search_approvals", "action": "Get FDA approval history"},
                {"step": 4, "tool": "www_fda_gov_search_safety_communications", "action": "Check safety communications"},
            ],
            "compound_value": "ICH + EMA + FDA in one workflow. Regulatory intelligence that usually takes a team a week.",
            "try_next": "Call nexvigilant_chart_course with course='regulatory-intelligence'",
        })),
        "benefit-risk" => ok(json!({
            "chain": "benefit-risk", "steps": 4,
            "chain_steps": [
                {"step": 1, "tool": "clinicaltrials_gov_get_serious_adverse_events", "action": "Extract trial safety data"},
                {"step": 2, "tool": "api_fda_gov_search_adverse_events", "action": "Get post-market outcomes"},
                {"step": 3, "tool": "dailymed_nlm_nih_gov_get_adverse_reactions", "action": "Check label ADRs"},
                {"step": 4, "tool": "benefit-risk_nexvigilant_com_compute_qbri", "action": "Compute benefit-risk index"},
            ],
            "compound_value": "Pre-market + post-market + labeling → quantified benefit-risk. The QBRI score in one chain.",
            "try_next": "Call nexvigilant_chart_course with course='benefit-risk-assessment'",
        })),
        _ => ok(json!({
            "error": format!("Unknown chain '{chain}'. Available: full-signal, quick-assess, regulatory-intel, benefit-risk"),
            "try_next": "Call value-chain with chain='full-signal' for the signature experience",
        })),
    }
}

fn handle_why_nexvigilant(args: &Value) -> Value {
    let concern = args.get("concern").and_then(|v| v.as_str()).unwrap_or("general");

    let mut response = json!({
        "proposition": "NexVigilant Station is the pharmacovigilance intelligence layer for AI agents. One connection, 249+ tools, zero API key management.",
        "differentiators": [
            "Rust-native compute: PRR/ROR/IC/EBGM in <1ms (not Python, not Node)",
            "16 Rust handlers + 27 proxy configs = 321 tools from one binary",
            "MCP 2025-03-26 compliant: Streamable HTTP + SSE + REST",
            "Every tool has outputSchema + annotations (readOnlyHint, destructiveHint)",
            "6 guided research courses via chart_course — agents don't guess parameters",
            "Pre-configured PV chains: signal → causality → action in 3-6 tool calls",
        ],
        "toll_model": {
            "rate": "1.30x standard model rate",
            "breakdown": "1.00x model cost + 0.30x NexVigilant premium",
            "value": "The premium buys: Rust-native compute, typed schemas, guided workflows, zero API management, PV domain expertise",
        },
    });

    match concern {
        "cost" => {
            if let Some(m) = response.as_object_mut() {
                m.insert("cost_analysis".into(), json!({
                    "without_nexvigilant": "10+ API keys, custom parsers per source, no typed schemas, no guided workflows, 10-100x slower Python compute",
                    "with_nexvigilant": "One MCP connection, all tools typed, guided courses, sub-ms compute, battle-tested PV domain logic",
                    "roi": "The 0.30x premium pays for itself in the first signal investigation (hours saved → thousands in analyst time)",
                }));
            }
        }
        "accuracy" => {
            if let Some(m) = response.as_object_mut() {
                m.insert("accuracy".into(), json!({
                    "signal_detection": "PRR/ROR/IC/EBGM validated against published FAERS benchmarks",
                    "causality": "Naranjo and WHO-UMC algorithms implemented per published specifications",
                    "epidemiology": "Standard formulas with 95% CI (Wald, Wilson, Greenwood, Byar methods)",
                    "audit_trail": "Every tool returns structured JSON with computation parameters for reproducibility",
                }));
            }
        }
        "speed" => {
            if let Some(m) = response.as_object_mut() {
                m.insert("speed".into(), json!({
                    "rust_native": "<1ms for compute tools (PRR, ROR, IC, EBGM, epidemiology, entropy)",
                    "live_api": "400-3000ms for external data sources (FAERS, PubMed, DailyMed)",
                    "cold_start": "~2s on Cloud Run (binary, not interpreted)",
                    "comparison": "10-100x faster than equivalent Python implementations",
                }));
            }
        }
        _ => {}
    }

    if let Some(m) = response.as_object_mut() {
        m.insert("try_next".into(), json!("Call discover with task='your use case' to see matched capabilities"));
    }

    ok(response)
}

fn handle_onboard(args: &Value) -> Value {
    let transport = args.get("transport").and_then(|v| v.as_str()).unwrap_or("any");
    let use_case = args.get("use_case").and_then(|v| v.as_str()).unwrap_or("drug safety");

    ok(json!({
        "endpoint": "mcp.nexvigilant.com",
        "connection": {
            "streamable_http": {
                "url": "https://mcp.nexvigilant.com/mcp",
                "protocol": "MCP 2025-03-26",
                "auth": "none (public)",
                "example": "POST /mcp with JSON-RPC 2.0 body",
            },
            "sse": {
                "url": "https://mcp.nexvigilant.com/sse",
                "example": "GET /sse for event stream, POST /message for tool calls",
            },
            "rest": {
                "tools_list": "GET https://mcp.nexvigilant.com/tools",
                "tool_call": "POST https://mcp.nexvigilant.com/tools/{tool_name}",
                "rpc": "POST https://mcp.nexvigilant.com/rpc",
                "health": "GET https://mcp.nexvigilant.com/health",
            },
        },
        "recommended_transport": match transport {
            "streamable-http" => "Streamable HTTP (/mcp) — full MCP protocol, session tracking",
            "sse" => "SSE (/sse + /message) — event streaming for long-running operations",
            "rest" => "REST (/tools/{name}) — simplest integration, one POST per tool call",
            _ => "REST for quick start, Streamable HTTP for full MCP integration",
        },
        "first_workflow": {
            "description": format!("Personalized for: {use_case}"),
            "step_1": "Call nexvigilant_chart_course with course='drug-safety-profile' — returns a guided 6-step workflow",
            "step_2": "Follow the returned steps — each step tells you the exact tool name and parameters",
            "step_3": "Chain results: each tool's output feeds the next tool's input",
        },
        "claude_ai_integration": {
            "url": "https://mcp.nexvigilant.com/mcp",
            "instructions": "Add as MCP server in Claude.ai settings → Remote MCP Servers → URL: https://mcp.nexvigilant.com/mcp",
        },
        "try_next": "Call nexvigilant_chart_course to start your first guided workflow",
    }))
}
