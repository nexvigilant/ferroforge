//! # Extremis — Self-Healing Relay Chains
//!
//! The Extremis upgrade: chains that sense, adapt, and heal.
//!
//! 1. **Auto-heal**: If a hop fails, try fallback tools automatically
//! 2. **Sense**: Extract signals from results and trigger downstream chains
//! 3. **Adapt**: Adjust chain parameters based on intermediate results
//! 4. **Regenerate**: If signal strength drops, route to backup data sources
//!
//! ```text
//! Normal chain:   A → B → C → D
//! Extremis chain: A → B(fail) → B'(fallback) → C(adapt threshold) → D
//! ```

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::HashMap;

/// Fallback mapping: if primary tool fails, try these alternatives.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Fallback {
    /// Primary tool that might fail
    pub primary: String,
    /// Ordered list of fallback tools to try
    pub alternatives: Vec<String>,
    /// Max attempts before giving up
    #[serde(default = "default_max_attempts")]
    pub max_attempts: usize,
}

fn default_max_attempts() -> usize { 3 }

/// Adaptive threshold: adjust parameters based on intermediate results.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Adaptation {
    /// Basket variable to watch
    pub watch: String,
    /// Condition: "gt", "lt", "eq", "contains"
    pub condition: String,
    /// Threshold value
    pub threshold: Value,
    /// Action: modify a basket variable or skip a hop
    pub action: AdaptAction,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum AdaptAction {
    /// Set a basket variable to a new value
    #[serde(rename = "set")]
    Set { key: String, value: Value },
    /// Skip the next N hops
    #[serde(rename = "skip")]
    Skip { count: usize },
    /// Trigger a different chain
    #[serde(rename = "branch")]
    Branch { chain: String },
    /// Emit a signal (for external consumption)
    #[serde(rename = "signal")]
    Signal { name: String, severity: String },
}

/// Extremis-enhanced chain — wraps a base chain with self-healing capabilities.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtremisChain {
    /// Base chain name to enhance
    pub base_chain: String,
    /// Fallback mappings for tools that might fail
    #[serde(default)]
    pub fallbacks: Vec<Fallback>,
    /// Adaptive rules applied after each hop
    #[serde(default)]
    pub adaptations: Vec<Adaptation>,
    /// Auto-triggered chains based on basket state
    #[serde(default)]
    pub triggers: Vec<Trigger>,
}

/// Auto-trigger: fire a chain when a condition is met.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Trigger {
    /// Basket variable to watch
    pub watch: String,
    /// Condition
    pub condition: String,
    /// Threshold
    pub threshold: Value,
    /// Chain to trigger
    pub chain: String,
    /// Additional args to pass
    #[serde(default)]
    pub inject: HashMap<String, String>,
}

/// Check if a condition is met against a basket value.
pub fn evaluate_condition(basket_value: &Value, condition: &str, threshold: &Value) -> bool {
    match condition {
        "gt" => {
            let bv = basket_value.as_f64().unwrap_or(0.0);
            let tv = threshold.as_f64().unwrap_or(0.0);
            bv > tv
        }
        "lt" => {
            let bv = basket_value.as_f64().unwrap_or(0.0);
            let tv = threshold.as_f64().unwrap_or(0.0);
            bv < tv
        }
        "eq" => basket_value == threshold,
        "neq" => basket_value != threshold,
        "contains" => {
            let bv = basket_value.as_str().unwrap_or("");
            let tv = threshold.as_str().unwrap_or("");
            bv.contains(tv)
        }
        "signal_detected" => {
            basket_value.as_str() == Some("signal_detected")
        }
        "true" => {
            basket_value.as_bool().unwrap_or(false)
        }
        _ => false,
    }
}

/// Find the best fallback tool for a failed primary.
pub fn find_fallback<'a>(
    primary: &str,
    fallbacks: &'a [Fallback],
    attempt: usize,
) -> Option<&'a str> {
    for fb in fallbacks {
        if fb.primary == primary && attempt < fb.alternatives.len() && attempt < fb.max_attempts {
            return Some(&fb.alternatives[attempt]);
        }
    }
    None
}

/// Apply adaptations to the basket after a hop completes.
pub fn apply_adaptations(
    basket: &mut super::Basket,
    adaptations: &[Adaptation],
) -> Vec<AdaptAction> {
    let mut actions = Vec::new();

    for adapt in adaptations {
        if let Some(val) = basket.get(&adapt.watch) {
            if evaluate_condition(val, &adapt.condition, &adapt.threshold) {
                match &adapt.action {
                    AdaptAction::Set { key, value } => {
                        basket.insert(key.clone(), value.clone());
                    }
                    action => {
                        actions.push(action.clone());
                    }
                }
            }
        }
    }

    actions
}

/// Check triggers and return chains that should fire.
pub fn check_triggers(
    basket: &super::Basket,
    triggers: &[Trigger],
) -> Vec<(String, HashMap<String, Value>)> {
    let mut fired = Vec::new();

    for trigger in triggers {
        if let Some(val) = basket.get(&trigger.watch) {
            if evaluate_condition(val, &trigger.condition, &trigger.threshold) {
                let mut args = HashMap::new();
                // Inject basket values into triggered chain args
                for (key, basket_key) in &trigger.inject {
                    if let Some(v) = basket.get(basket_key) {
                        args.insert(key.clone(), v.clone());
                    }
                }
                fired.push((trigger.chain.clone(), args));
            }
        }
    }

    fired
}

/// Build the default Extremis configuration for PV signal detection.
pub fn default_pv_extremis() -> ExtremisChain {
    ExtremisChain {
        base_chain: "full-investigation".to_string(),
        fallbacks: vec![
            // If OpenVigil fails, try computing PRR from FAERS data directly
            Fallback {
                primary: "open-vigil_fr_compute_disproportionality".to_string(),
                alternatives: vec![
                    "calculate_nexvigilant_com_compute_prr".to_string(),
                ],
                max_attempts: 2,
            },
            // If DailyMed fails, try DrugBank for label info
            Fallback {
                primary: "dailymed_nlm_nih_gov_get_adverse_reactions".to_string(),
                alternatives: vec![
                    "go_drugbank_com_get_adverse_effects".to_string(),
                ],
                max_attempts: 2,
            },
        ],
        adaptations: vec![
            // If PRR > 2.0 (signal threshold), escalate to full causality assessment
            Adaptation {
                watch: "prr".to_string(),
                condition: "gt".to_string(),
                threshold: json!(2.0),
                action: AdaptAction::Signal {
                    name: "signal_threshold_crossed".to_string(),
                    severity: "high".to_string(),
                },
            },
            // If cases < 3, skip causality (insufficient data)
            Adaptation {
                watch: "cases".to_string(),
                condition: "lt".to_string(),
                threshold: json!(3),
                action: AdaptAction::Skip { count: 1 },
            },
        ],
        triggers: vec![
            // If signal detected AND serious, auto-trigger regulatory check
            Trigger {
                watch: "signal".to_string(),
                condition: "signal_detected".to_string(),
                threshold: json!("signal_detected"),
                chain: "regulatory-intel".to_string(),
                inject: [("drug".to_string(), "drug".to_string())].into_iter().collect(),
            },
        ],
    }
}
