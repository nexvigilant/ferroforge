use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::Path;
use tracing::info;

use crate::protocol::ToolInfo;

/// A hub config file — defines tools for a specific domain/URL pattern.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct HubConfig {
    /// Domain this config applies to (e.g., "dailymed.nlm.nih.gov")
    pub domain: String,

    /// URL pattern for matching (e.g., "/dailymed/drugInfo*")
    #[serde(default)]
    pub url_pattern: Option<String>,

    /// Human-readable title
    pub title: String,

    /// Description of what this config provides
    #[serde(default)]
    pub description: Option<String>,

    /// Python proxy script for all tools in this config (relative to station root)
    #[serde(default)]
    pub proxy: Option<String>,

    /// Tools exposed by this config
    pub tools: Vec<ToolDef>,
}

/// A single tool definition within a hub config.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ToolDef {
    /// Tool name (e.g., "get-adverse-reactions")
    pub name: String,

    /// What this tool does
    pub description: String,

    /// Tool parameters
    #[serde(default)]
    pub parameters: Vec<ParamDef>,

    /// Static response for stub tools (development/testing)
    #[serde(default)]
    pub stub_response: Option<String>,

    /// Per-tool proxy script override (relative to station root)
    #[serde(default)]
    pub proxy: Option<String>,

    /// JSON Schema describing the tool's output structure (MCP spec 2025-06-18)
    #[serde(default, rename = "outputSchema")]
    pub output_schema: Option<Value>,
}

/// A parameter for a tool.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ParamDef {
    pub name: String,
    #[serde(rename = "type", default = "default_string_type")]
    pub param_type: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub required: bool,
}

fn default_string_type() -> String {
    "string".into()
}

/// Loaded config registry — all configs from the configs/ directory.
#[derive(Debug)]
pub struct ConfigRegistry {
    pub configs: Vec<HubConfig>,
    /// Root directory of the station (for resolving relative proxy paths)
    pub station_root: String,
}

impl ConfigRegistry {
    /// Load all config files from a directory.
    pub fn load_from_dir(dir: &Path) -> Result<Self> {
        let mut configs = Vec::new();

        if !dir.exists() {
            info!(path = %dir.display(), "Config directory does not exist, starting empty");
            return Ok(Self {
                configs,
                station_root: dir.parent().unwrap_or(dir).to_string_lossy().into(),
            });
        }

        for entry in std::fs::read_dir(dir).context("reading config directory")? {
            let entry = entry?;
            let path = entry.path();

            let ext = path.extension().and_then(|e| e.to_str());
            let config = match ext {
                Some("json") => {
                    let data = std::fs::read_to_string(&path)?;
                    serde_json::from_str::<HubConfig>(&data)
                        .with_context(|| format!("parsing {}", path.display()))?
                }
                Some("yaml" | "yml") => {
                    // For now, treat YAML as JSON (add serde_yaml later if needed)
                    let data = std::fs::read_to_string(&path)?;
                    serde_json::from_str::<HubConfig>(&data)
                        .with_context(|| format!("parsing {}", path.display()))?
                }
                Some("toml") => {
                    let data = std::fs::read_to_string(&path)?;
                    toml::from_str::<HubConfig>(&data)
                        .with_context(|| format!("parsing {}", path.display()))?
                }
                _ => continue,
            };

            info!(
                domain = %config.domain,
                tools = config.tools.len(),
                path = %path.display(),
                "Loaded config"
            );
            configs.push(config);
        }

        info!(
            configs = configs.len(),
            tools = configs.iter().map(|c| c.tools.len()).sum::<usize>(),
            "Config registry loaded"
        );

        Ok(Self {
            configs,
            station_root: dir.canonicalize()
                .unwrap_or_else(|_| dir.to_path_buf())
                .parent()
                .unwrap_or(dir)
                .to_string_lossy()
                .into(),
        })
    }

    /// Convert all tools to MCP ToolInfo for tools/list, including meta-tools.
    pub fn tool_infos(&self) -> Vec<ToolInfo> {
        let mut tools: Vec<ToolInfo> = vec![
            ToolInfo {
                name: "nexvigilant_directory".into(),
                description: "[NexVigilant Station] Complete directory of all pharmacovigilance tools, domains, and capabilities. Lists every available tool with parameters and handler status.".into(),
                input_schema: serde_json::json!({
                    "type": "object",
                    "properties": {},
                }),
                output_schema: None,
            },
            ToolInfo {
                name: "nexvigilant_capabilities".into(),
                description: "[NexVigilant Station] Search NexVigilant capabilities by keyword or domain. Find tools for adverse events, drug interactions, signal detection, labeling, and more.".into(),
                input_schema: serde_json::json!({
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search keyword (e.g., 'adverse events', 'signal', 'interaction')"
                        },
                        "domain": {
                            "type": "string",
                            "description": "Filter by domain (e.g., 'fda', 'dailymed', 'clinicaltrials')"
                        }
                    },
                }),
                output_schema: None,
            },
            ToolInfo {
                name: "nexvigilant_station_health".into(),
                description: "[NexVigilant Station] Station telemetry dashboard — total calls, error rates, per-domain stats, top tools, recent activity. Owner visibility into the open house.".into(),
                input_schema: serde_json::json!({
                    "type": "object",
                    "properties": {},
                }),
                output_schema: None,
            },
            ToolInfo {
                name: "nexvigilant_chart_course".into(),
                description: "[NexVigilant Station] Chart a research course — predefined multi-tool workflows for drug safety profiling, signal investigation, target analysis, and HEXIM1 research. Call with no args to list courses, or provide 'course' to get the step-by-step plan.".into(),
                input_schema: serde_json::json!({
                    "type": "object",
                    "properties": {
                        "course": {
                            "type": "string",
                            "description": "Course name (e.g., 'drug-safety-profile', 'signal-investigation', 'hexim1-landscape'). Omit to list all available courses."
                        }
                    },
                }),
                output_schema: None,
            },
        ];

        tools.extend(self.configs
            .iter()
            .flat_map(|config| {
                config.tools.iter().map(move |tool| {
                    let prefixed_name = format!("{}_{}", config.domain.replace('.', "_"), tool.name.replace('-', "_"));

                    // Build JSON Schema for input parameters
                    let mut properties = serde_json::Map::new();
                    let mut required = Vec::new();

                    for param in &tool.parameters {
                        let mut prop = serde_json::Map::new();
                        prop.insert("type".into(), Value::String(param.param_type.clone()));
                        if let Some(desc) = &param.description {
                            prop.insert("description".into(), Value::String(desc.clone()));
                        }
                        properties.insert(param.name.clone(), Value::Object(prop));
                        if param.required {
                            required.push(Value::String(param.name.clone()));
                        }
                    }

                    let input_schema = serde_json::json!({
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    });

                    ToolInfo {
                        name: prefixed_name,
                        description: format!("[{}] {}", config.domain, tool.description),
                        input_schema,
                        output_schema: tool.output_schema.clone(),
                    }
                })
            })
            .collect::<Vec<_>>());

        tools
    }

    /// Find a tool definition by its prefixed MCP name.
    pub fn find_tool(&self, mcp_name: &str) -> Option<(&HubConfig, &ToolDef)> {
        for config in &self.configs {
            let domain_prefix = format!("{}_", config.domain.replace('.', "_"));
            if let Some(tool_name) = mcp_name.strip_prefix(&domain_prefix) {
                let tool_name_dashed = tool_name.replace('_', "-");
                if let Some(tool) = config.tools.iter().find(|t| {
                    t.name.replace('-', "_") == tool_name || t.name == tool_name_dashed
                }) {
                    return Some((config, tool));
                }
            }
        }
        None
    }

    /// Total tool count across all configs.
    pub fn tool_count(&self) -> usize {
        self.configs.iter().map(|c| c.tools.len()).sum()
    }
}
