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
}

impl ConfigRegistry {
    /// Load all config files from a directory.
    pub fn load_from_dir(dir: &Path) -> Result<Self> {
        let mut configs = Vec::new();

        if !dir.exists() {
            info!(path = %dir.display(), "Config directory does not exist, starting empty");
            return Ok(Self { configs });
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

        Ok(Self { configs })
    }

    /// Convert all tools to MCP ToolInfo for tools/list.
    pub fn tool_infos(&self) -> Vec<ToolInfo> {
        self.configs
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
                    }
                })
            })
            .collect()
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
