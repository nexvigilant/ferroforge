//! MoltBook — MCP tool surface for config discovery, contribution, and health monitoring.
//!
//! Exposes the Molt family as native MCP tools so any agent connecting via
//! the MCP protocol can discover configs, submit new ones, and check health
//! without needing REST endpoint knowledge.
//!
//! Tools:
//!   moltbook_nexvigilant_com_lookup       — discover configs by domain
//!   moltbook_nexvigilant_com_catalog      — list all configs with source types
//!   moltbook_nexvigilant_com_contribute   — submit a new config
//!   moltbook_nexvigilant_com_watch        — check config health status
//!   moltbook_nexvigilant_com_generate     — describe how to generate a proxy script

use serde_json::{Value, json};
use tracing::info;
use crate::config::ConfigRegistry;
use crate::protocol::{ContentBlock, ToolCallResult};

/// Try to handle a MoltBook tool call. Returns None if the tool name doesn't match.
pub fn try_handle(tool_name: &str, args: &Value, registry: &ConfigRegistry) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("moltbook_nexvigilant_com_")?.replace('_', "-");
    let result = match bare.as_str() {
        "lookup" => handle_lookup(args, registry),
        "catalog" => handle_catalog(registry),
        "contribute" => handle_contribute(args, registry),
        "watch" => handle_watch(registry),
        "generate" => handle_generate(args),
        _ => return None,
    };
    info!(tool = tool_name, "Handled natively (moltbook)");
    Some(ToolCallResult {
        content: vec![ContentBlock::Text {
            text: serde_json::to_string_pretty(&result).unwrap_or_default(),
        }],
        is_error: None,
    })
}

fn classify_source(domain: &str) -> &'static str {
    let d = domain.to_lowercase();
    if d.ends_with(".nexvigilant.com") {
        "rust-native"
    } else if [
        "api.fda.gov", "clinicaltrials.gov", "pubmed.ncbi.nlm.nih.gov",
        "dailymed.nlm.nih.gov", "rxnav.nlm.nih.gov", "open-vigil.fr",
        "accessdata.fda.gov", "eudravigilance.ema.europa.eu",
        "eudravigilance-live.ema.europa.eu", "www.ema.europa.eu",
        "vigiaccess.org", "en.wikipedia.org",
    ].iter().any(|&x| d == x) {
        "live-api"
    } else if d.starts_with("www.") {
        "live-api"
    } else {
        "reference"
    }
}

fn config_to_json(config: &crate::config::HubConfig) -> Value {
    let tools: Vec<Value> = config.tools.iter().map(|t| {
        json!({
            "name": t.name,
            "description": t.description,
            "paramCount": t.parameters.len(),
        })
    }).collect();

    json!({
        "domain": config.domain,
        "title": config.title,
        "description": config.description,
        "toolCount": config.tools.len(),
        "tools": tools,
        "sourceType": classify_source(&config.domain),
    })
}

/// Lookup configs matching a domain query.
fn handle_lookup(args: &Value, registry: &ConfigRegistry) -> Value {
    let query = args.get("domain")
        .or_else(|| args.get("query"))
        .and_then(|v| v.as_str())
        .unwrap_or("");

    if query.is_empty() {
        return json!({
            "status": "error",
            "message": "domain is required. Example: moltbook_nexvigilant_com_lookup({\"domain\": \"dailymed\"})",
        });
    }

    let query_lower = query.to_lowercase();
    let matched: Vec<Value> = registry.configs.iter()
        .filter(|c| c.domain.to_lowercase().contains(&query_lower))
        .map(|c| config_to_json(c))
        .collect();

    json!({
        "status": "ok",
        "query": query,
        "count": matched.len(),
        "configs": matched,
        "try_next": if matched.is_empty() {
            "No configs found. Try moltbook_nexvigilant_com_catalog to see all available domains."
        } else {
            "Use the tool names from the matched config to call tools directly."
        },
    })
}

/// List all configs in the catalog with summary stats.
fn handle_catalog(registry: &ConfigRegistry) -> Value {
    let mut by_type: std::collections::HashMap<&str, Vec<Value>> = std::collections::HashMap::new();

    for config in &registry.configs {
        let source = classify_source(&config.domain);
        by_type.entry(source).or_default().push(json!({
            "domain": config.domain,
            "title": config.title,
            "toolCount": config.tools.len(),
        }));
    }

    let total_tools: usize = registry.configs.iter().map(|c| c.tools.len()).sum();

    json!({
        "status": "ok",
        "totalConfigs": registry.configs.len(),
        "totalTools": total_tools,
        "bySourceType": {
            "rust-native": by_type.get("rust-native").map(|v| v.len()).unwrap_or(0),
            "live-api": by_type.get("live-api").map(|v| v.len()).unwrap_or(0),
            "reference": by_type.get("reference").map(|v| v.len()).unwrap_or(0),
        },
        "configs": registry.configs.iter().map(|c| json!({
            "domain": c.domain,
            "toolCount": c.tools.len(),
            "sourceType": classify_source(&c.domain),
        })).collect::<Vec<_>>(),
        "try_next": "Use moltbook_nexvigilant_com_lookup with a domain to see full tool details.",
    })
}

/// Accept a contributed config from an agent.
fn handle_contribute(args: &Value, registry: &ConfigRegistry) -> Value {
    let domain = match args.get("domain").and_then(|v| v.as_str()) {
        Some(d) if !d.is_empty() => d,
        _ => return json!({
            "status": "error",
            "message": "domain is required",
        }),
    };

    let title = match args.get("title").and_then(|v| v.as_str()) {
        Some(t) if !t.is_empty() => t,
        _ => return json!({
            "status": "error",
            "message": "title is required",
        }),
    };

    let tools = match args.get("tools").and_then(|v| v.as_array()) {
        Some(t) if !t.is_empty() => t,
        _ => return json!({
            "status": "error",
            "message": "tools array required with at least one tool (each needs name + description)",
        }),
    };

    // Validate tool structure
    for (i, tool) in tools.iter().enumerate() {
        if tool.get("name").and_then(|v| v.as_str()).unwrap_or("").is_empty() {
            return json!({ "status": "error", "message": format!("tools[{}] missing 'name'", i) });
        }
        if tool.get("description").and_then(|v| v.as_str()).unwrap_or("").is_empty() {
            return json!({ "status": "error", "message": format!("tools[{}] missing 'description'", i) });
        }
    }

    let domain_exists = registry.configs.iter().any(|c| c.domain == domain);

    // Write config to disk
    let filename = domain.replace('.', "-").replace('/', "_");
    let config_path = format!("{}/configs/{}.json", registry.station_root, filename);

    let config_json = json!({
        "domain": domain,
        "url_pattern": args.get("urlPattern").and_then(|v| v.as_str()).unwrap_or("/*"),
        "title": title,
        "description": args.get("description").and_then(|v| v.as_str()),
        "tools": tools,
    });
    let config_pretty = serde_json::to_string_pretty(&config_json).unwrap_or_default();

    // Write config to disk (ephemeral on Cloud Run, persistent on local dev)
    let write_result = std::fs::write(&config_path, &config_pretty);

    // Persist to GCS if configured (Primary persistence for Cloud Run)
    if let Ok(bucket) = std::env::var("MOLTCONTRIB_BUCKET") {
        let gcp = crate::gcp::GcpClient::new();
        let filename = domain.replace('.', "-").replace('/', "_");
        let object_name = format!("configs/{}.json", filename);
        if let Err(e) = gcp.upload_to_gcs(&bucket, &object_name, config_pretty.as_bytes()) {
            info!(bucket = %bucket, object = %object_name, error = %e, "MoltContrib: GCS persistence failed via MCP");
        } else {
            info!(bucket = %bucket, object = %object_name, "MoltContrib: GCS persistence successful via MCP");
        }
    }

    match write_result {
        Ok(_) => {
            info!(domain = %domain, tools = tools.len(), "MoltBook: config contributed via MCP");
            json!({
                "status": "ok",
                "message": if domain_exists { "Config updated (takes effect on restart)" }
                           else { "Config created (takes effect on restart)" },
                "domain": domain,
                "configPath": config_path,
                "try_next": "Config is persisted. Run moltbook_nexvigilant_com_watch to verify health.",
            })
        }
        Err(e) => json!({
            "status": "error",
            "message": format!("Failed to write config: {}", e),
        }),
    }
}

/// Check health of all configs.
fn handle_watch(registry: &ConfigRegistry) -> Value {
    let is_cloud_run = std::env::var("K_SERVICE").is_ok();
    let mut results = Vec::new();

    for config in &registry.configs {
        let is_rust_native = config.domain.to_lowercase().ends_with(".nexvigilant.com");

        let proxy_status = if is_rust_native {
            "rust-native"
        } else if config.proxy.is_some() {
            if is_cloud_run { "cloud-run-proxy" } else {
                let proxy_path = format!("{}/{}", registry.station_root,
                    config.proxy.as_deref().unwrap_or(""));
                if std::path::Path::new(&proxy_path).exists() { "healthy" } else { "missing_proxy" }
            }
        } else {
            "healthy"
        };

        let stub_count = config.tools.iter().filter(|t| t.stub_response.is_some()).count();
        let status = if proxy_status == "missing_proxy" { "degraded" }
            else if stub_count == config.tools.len() && config.tools.len() > 0 { "stub_only" }
            else if stub_count > 0 { "partial" }
            else { "healthy" };

        results.push(json!({
            "domain": config.domain,
            "status": status,
            "toolCount": config.tools.len(),
            "stubCount": stub_count,
        }));
    }

    let healthy = results.iter().filter(|r| r["status"] == "healthy").count();
    let degraded = results.len() - healthy;

    json!({
        "status": "ok",
        "summary": {
            "total": results.len(),
            "healthy": healthy,
            "degraded": degraded,
            "healthPct": if results.is_empty() { 100.0 } else {
                (healthy as f64 / results.len() as f64 * 100.0 * 10.0).round() / 10.0
            },
        },
        "degraded": results.iter().filter(|r| r["status"] != "healthy").cloned().collect::<Vec<_>>(),
        "try_next": "Use moltbook_nexvigilant_com_lookup to inspect specific degraded configs.",
    })
}

/// Describe how to generate a proxy script from a config.
fn handle_generate(args: &Value) -> Value {
    let domain = args.get("domain").and_then(|v| v.as_str()).unwrap_or("example.com");
    let mode = args.get("mode").and_then(|v| v.as_str()).unwrap_or("api");

    json!({
        "status": "ok",
        "instructions": {
            "step1": format!("Create config: configs/{}.json with domain, title, tools[]", domain.replace('.', "-")),
            "step2": format!("Generate proxy: python3 scripts/moltproxy_generate.py configs/{}.json {}",
                domain.replace('.', "-"),
                if mode == "browser" { "--browser" } else { "" }),
            "step3": "Wire in dispatch.py (auto-discovered from config domain prefix)",
            "step4": "Test: echo '{\"tool\": \"tool-name\", \"args\": {}}' | python3 scripts/generated_proxy.py",
            "step5": "Deploy: gcloud run deploy nexvigilant-station --source .",
        },
        "modes": {
            "api": "Generates urllib-based proxy for REST APIs (faster, no browser needed)",
            "browser": "Generates Playwright-based proxy for JS-heavy sites (needs chromium)",
        },
        "try_next": "Use moltbook_nexvigilant_com_contribute to submit the config after testing.",
    })
}
