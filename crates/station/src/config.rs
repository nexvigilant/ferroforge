use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::Path;
use tracing::info;

use crate::protocol::{ToolAnnotations, ToolInfo};

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

    /// Private config — excluded from public deployments (--exclude-private)
    #[serde(default)]
    pub private: bool,

    /// Copyright notice for proprietary frameworks
    #[serde(default)]
    pub copyright: Option<String>,
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

    /// MCP tool annotations (readOnlyHint, destructiveHint, openWorldHint)
    #[serde(default)]
    pub annotations: Option<ToolAnnotations>,
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
    /// Load all config files from a directory (includes all configs).
    pub fn load_from_dir(dir: &Path) -> Result<Self> {
        Self::load_from_dir_filtered(dir, false)
    }

    /// Load all config files from a directory.
    /// If `exclude_private` is true, configs with `"private": true` are skipped.
    pub fn load_from_dir_filtered(dir: &Path, exclude_private: bool) -> Result<Self> {
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

            // Skip private configs when deploying publicly
            if exclude_private && config.private {
                info!(
                    domain = %config.domain,
                    path = %path.display(),
                    "Skipping private config"
                );
                continue;
            }

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
        let meta_annotations = Some(ToolAnnotations {
            read_only_hint: Some(true),
            destructive_hint: Some(false),
            open_world_hint: None,
        });

        let mut tools: Vec<ToolInfo> = vec![
            ToolInfo {
                name: "nexvigilant_chart_course".into(),
                description: "[NexVigilant Station] START HERE — Your guided entry point to NexVigilant's pharmacovigilance tools. Returns step-by-step workflows with exact tool names and parameters for any drug safety question. 6 courses: drug-safety-profile, signal-investigation, causality-assessment, benefit-risk-assessment, regulatory-intelligence, competitive-landscape. Call with no args to see all courses, or provide a course name to get the execution plan.".into(),
                input_schema: serde_json::json!({
                    "type": "object",
                    "properties": {
                        "course": {
                            "type": "string",
                            "description": "Course name: 'drug-safety-profile' (most common), 'signal-investigation', 'causality-assessment', 'benefit-risk-assessment', 'regulatory-intelligence', or 'competitive-landscape'. Omit to list all courses with descriptions."
                        }
                    },
                }),
                output_schema: None,
                annotations: meta_annotations.clone(),
            },
            ToolInfo {
                name: "nexvigilant_directory".into(),
                description: "[NexVigilant Station] Complete directory of all pharmacovigilance tools, domains, and capabilities. Lists every available tool with parameters and handler status.".into(),
                input_schema: serde_json::json!({
                    "type": "object",
                    "properties": {},
                }),
                output_schema: None,
                annotations: meta_annotations.clone(),
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
                annotations: meta_annotations.clone(),
            },
            ToolInfo {
                name: "nexvigilant_station_health".into(),
                description: "[NexVigilant Station] Station telemetry dashboard — total calls, error rates, per-domain stats, top tools, recent activity. Owner visibility into the open house.".into(),
                input_schema: serde_json::json!({
                    "type": "object",
                    "properties": {},
                }),
                output_schema: None,
                annotations: meta_annotations.clone(),
            },
            ToolInfo {
                name: "nexvigilant_ring_health".into(),
                description: "[NexVigilant Station] Aromatic ring health — computes HOMA (Harmonic Oscillator Model of Aromaticity) for the NexVigilant mission ring: Station → Micrograms → NexCore → Nucleus → Academy → Glass → Station. HOMA > 0.5 = aromatic (mission delocalized, stable). HOMA < 0 = anti-aromatic (ring destabilizes). Returns edge strengths, gradient, and next step.".into(),
                input_schema: serde_json::json!({
                    "type": "object",
                    "properties": {},
                }),
                output_schema: None,
                annotations: meta_annotations,
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

                    // Detect stub tools: has stub_response but no proxy at tool or config level
                    let is_stub = tool.stub_response.is_some()
                        && tool.proxy.is_none()
                        && config.proxy.is_none();

                    let description = if is_stub {
                        format!("[STUB — not yet live] [{}] {}", config.domain, tool.description)
                    } else {
                        format!("[{}] {}", config.domain, tool.description)
                    };

                    ToolInfo {
                        name: prefixed_name,
                        description,
                        input_schema,
                        output_schema: tool.output_schema.clone(),
                        annotations: tool.annotations.clone(),
                    }
                })
            })
            .collect::<Vec<_>>());

        tools
    }

    /// Convert tools to MCP ToolInfo, filtering by auth status.
    /// Authenticated callers see all tools. Unauthenticated see only public config tools.
    pub fn tool_infos_filtered(&self, authenticated: bool) -> Vec<ToolInfo> {
        if authenticated {
            return self.tool_infos(); // all tools
        }
        // Unauthenticated: meta-tools + public config tools only
        let all = self.tool_infos();
        let private_prefixes: Vec<String> = self.configs
            .iter()
            .filter(|c| c.private)
            .map(|c| format!("{}_", c.domain.replace('.', "_")))
            .collect();

        all.into_iter()
            .filter(|tool| {
                // Keep meta-tools (they don't have a domain prefix from configs)
                !private_prefixes.iter().any(|prefix| tool.name.starts_with(prefix))
            })
            .collect()
    }

    /// Check if a tool belongs to a private config.
    pub fn is_tool_private(&self, mcp_name: &str) -> bool {
        for config in &self.configs {
            if config.private {
                let domain_prefix = format!("{}_", config.domain.replace('.', "_"));
                if mcp_name.starts_with(&domain_prefix) {
                    return true;
                }
            }
        }
        false
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

    /// Total tool count across all configs + Rust-native meta-tools.
    /// Must match len(tool_infos()) to avoid /health vs tools/list mismatch.
    pub fn tool_count(&self) -> usize {
        const META_TOOLS: usize = 5; // chart_course, directory, capabilities, station_health, ring_health
        META_TOOLS + self.configs.iter().map(|c| c.tools.len()).sum::<usize>()
    }

    /// SHA-256 hash of the config set for drift detection.
    ///
    /// Hashes the sorted domain names + tool counts. If this value changes
    /// between deploys, the config set has drifted.
    pub fn config_hash(&self) -> String {
        use sha2::{Sha256, Digest};
        let mut hasher = Sha256::new();
        let mut domains: Vec<String> = self
            .configs
            .iter()
            .map(|c| format!("{}:{}", c.domain, c.tools.len()))
            .collect();
        domains.sort();
        for d in &domains {
            hasher.update(d.as_bytes());
        }
        format!("{:x}", hasher.finalize())
    }
}
