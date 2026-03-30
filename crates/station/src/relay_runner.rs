//! relay_runner — Parses and executes `ferroforge/relays/*.yaml` chains.
//!
//! # Design
//!
//! Each relay YAML defines a sequence of hops (`σ`). Per-hop fidelity `F_i` is
//! measured against actual tool output quality:
//!
//!   F_i = 1.0   if the hop succeeded and all `extract` keys were populated
//!   F_i = 0.5   if `continue_on_error: true` and the hop errored (partial signal)
//!   F_i = 0.0   if the hop errored and `continue_on_error` is absent/false
//!
//! F_total = Product(F_i) — multiplicative composition (`N+→`).
//!
//! Variable substitution (`$var`) resolves against a growing context map (`ς`)
//! seeded from chain-level inputs and extended with each hop's `extract` output.
//!
//! Dotpath extraction (`κ`) navigates serde_json `Value` trees via
//! `"results[0].reactions[0]"` style paths.

#![deny(clippy::unwrap_used, clippy::expect_used, clippy::panic)]
#![forbid(unsafe_code)]

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::HashMap;
use std::path::Path;

// ---------------------------------------------------------------------------
// Schema — mirrors the relay YAML structure
// ---------------------------------------------------------------------------

/// A complete relay chain loaded from a YAML file.
#[derive(Debug, Clone, Deserialize)]
pub struct RelayChainSpec {
    pub name: String,
    pub description: String,
    pub hops: Vec<HopSpec>,
}

/// One step in the relay chain.
#[derive(Debug, Clone, Deserialize)]
pub struct HopSpec {
    /// MCP tool name (e.g., `rxnav_nlm_nih_gov_search_drugs`).
    pub tool: String,
    /// Raw args as YAML mapping; values may contain `$var` references.
    #[serde(default)]
    pub args: HashMap<String, Value>,
    /// Keys to extract from the tool response, mapped to dotpath expressions.
    #[serde(default)]
    pub extract: HashMap<String, String>,
    /// When true, hop errors produce F_i = 0.5 instead of failing the chain.
    #[serde(default)]
    pub continue_on_error: bool,
}

// ---------------------------------------------------------------------------
// Execution types
// ---------------------------------------------------------------------------

/// Per-hop fidelity — clamped `[0.0, 1.0]`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct HopFidelity(f64);

impl HopFidelity {
    pub const PERFECT: HopFidelity = HopFidelity(1.0);
    pub const PARTIAL: HopFidelity = HopFidelity(0.5);
    pub const ZERO: HopFidelity = HopFidelity(0.0);

    pub fn new(v: f64) -> Self {
        HopFidelity(v.clamp(0.0, 1.0))
    }

    pub fn value(self) -> f64 {
        self.0
    }
}

/// The outcome of a single hop.
#[derive(Debug, Clone, Serialize)]
pub struct HopResult {
    pub hop_index: usize,
    pub tool: String,
    /// Resolved args (after `$var` substitution).
    pub resolved_args: HashMap<String, Value>,
    /// Values extracted from the tool response.
    pub extracted: HashMap<String, Value>,
    /// Raw tool response (set by dispatcher).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub raw_response: Option<Value>,
    pub fidelity: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// Summary of a complete relay chain execution.
#[derive(Debug, Clone, Serialize)]
pub struct RelayRunResult {
    pub chain: String,
    pub description: String,
    pub f_total: f64,
    pub signal_loss_pct: f64,
    pub hops_total: usize,
    pub hops_passed: usize,
    pub hops_partial: usize,
    pub hops_failed: usize,
    pub hop_results: Vec<HopResult>,
    pub final_context: HashMap<String, Value>,
}

// ---------------------------------------------------------------------------
// YAML loading
// ---------------------------------------------------------------------------

/// Load and parse a relay chain YAML file.
pub fn load_chain(path: &Path) -> Result<RelayChainSpec> {
    let text = std::fs::read_to_string(path)
        .with_context(|| format!("reading relay YAML: {}", path.display()))?;
    let chain: RelayChainSpec = serde_yaml::from_str(&text)
        .with_context(|| format!("parsing relay YAML: {}", path.display()))?;
    if chain.hops.is_empty() {
        bail!("{}: relay chain has no hops", chain.name);
    }
    Ok(chain)
}

/// Load all `*.yaml` files from a directory.
pub fn load_all_chains(relay_dir: &Path) -> Result<Vec<RelayChainSpec>> {
    let mut chains = Vec::new();
    let entries = std::fs::read_dir(relay_dir)
        .with_context(|| format!("reading relay dir: {}", relay_dir.display()))?;
    for entry in entries {
        let entry = entry.context("reading dir entry")?;
        let p = entry.path();
        if p.extension().and_then(|e| e.to_str()) == Some("yaml") {
            match load_chain(&p) {
                Ok(c) => chains.push(c),
                Err(e) => tracing::warn!(path = %p.display(), error = %e, "skipping invalid relay YAML"),
            }
        }
    }
    chains.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(chains)
}

// ---------------------------------------------------------------------------
// Variable resolution — `$var` substitution + dotpath extraction
// ---------------------------------------------------------------------------

/// Substitute `$var` references in a string using `context`.
/// Unknown vars are left as-is (forward references resolved at runtime).
pub fn substitute_vars(s: &str, context: &HashMap<String, Value>) -> Value {
    // If the entire string is a single `$var`, return the typed value directly.
    if let Some(var) = s.strip_prefix('$') {
        if let Some(v) = context.get(var) {
            return v.clone();
        }
        // Unresolved — return original string
        return Value::String(s.to_owned());
    }
    // Otherwise do textual substitution (e.g., partial embeds)
    let mut result = s.to_owned();
    for (k, v) in context {
        let placeholder = format!("${k}");
        if result.contains(&placeholder) {
            let replacement = match v {
                Value::String(s) => s.clone(),
                other => other.to_string(),
            };
            result = result.replace(&placeholder, &replacement);
        }
    }
    Value::String(result)
}

/// Apply `$var` substitution to an args map.
pub fn resolve_args(
    raw: &HashMap<String, Value>,
    context: &HashMap<String, Value>,
) -> HashMap<String, Value> {
    raw.iter()
        .map(|(k, v)| {
            let resolved = match v {
                Value::String(s) => substitute_vars(s, context),
                other => other.clone(),
            };
            (k.clone(), resolved)
        })
        .collect()
}

/// Navigate a `serde_json::Value` with a dotpath like `"results[0].reactions[0]"`.
/// Returns `None` if any segment fails to resolve.
pub fn dotpath_get<'v>(value: &'v Value, path: &str) -> Option<&'v Value> {
    let mut current = value;
    for segment in path.split('.') {
        // Handle array indexing: `results[0]`
        if let Some((name, idx_str)) = segment.split_once('[') {
            let idx_str = idx_str.trim_end_matches(']');
            let idx: usize = idx_str.parse().ok()?;
            // Descend into object key first (if non-empty)
            if !name.is_empty() {
                current = current.get(name)?;
            }
            current = current.get(idx)?;
        } else {
            current = current.get(segment)?;
        }
    }
    Some(current)
}

/// Extract values from `response` using the hop's `extract` map.
/// Returns `(extracted_map, fully_populated)`.
pub fn extract_values(
    response: &Value,
    extract: &HashMap<String, String>,
) -> (HashMap<String, Value>, bool) {
    let mut out = HashMap::new();
    let mut all_found = true;
    for (key, path) in extract {
        match dotpath_get(response, path) {
            Some(v) => {
                out.insert(key.clone(), v.clone());
            }
            None => {
                all_found = false;
                tracing::debug!(key = %key, path = %path, "extract path not found in response");
            }
        }
    }
    (out, all_found || extract.is_empty())
}

// ---------------------------------------------------------------------------
// Fidelity computation
// ---------------------------------------------------------------------------

/// Compute F_i for a single hop given success/error status and extraction completeness.
pub fn hop_fidelity(
    succeeded: bool,
    fully_extracted: bool,
    continue_on_error: bool,
) -> HopFidelity {
    if succeeded {
        if fully_extracted {
            HopFidelity::PERFECT
        } else {
            // Partial extraction — some extract paths missing
            HopFidelity::new(0.75)
        }
    } else if continue_on_error {
        HopFidelity::PARTIAL
    } else {
        HopFidelity::ZERO
    }
}

/// Compute F_total = Product(F_i) for all hops.
pub fn compose_fidelity(fidelities: &[HopFidelity]) -> f64 {
    fidelities.iter().fold(1.0_f64, |acc, f| acc * f.value())
}

// ---------------------------------------------------------------------------
// Dispatcher trait — injected for testability
// ---------------------------------------------------------------------------

/// Dispatch a single tool call. In production this shells out to `dispatch.py`;
/// in tests a mock dispatcher is injected.
pub trait ToolDispatcher: Send + Sync {
    /// Call `tool_name` with `args`, returning the JSON response or an error.
    fn call(&self, tool_name: &str, args: &HashMap<String, Value>) -> Result<Value>;
}

/// Dry-run dispatcher — returns a synthetic response without network calls.
/// Fidelity = PERFECT for all hops (all extracts are stubbed as `"<dry-run>"`).
pub struct DryRunDispatcher;

impl ToolDispatcher for DryRunDispatcher {
    fn call(&self, tool_name: &str, _args: &HashMap<String, Value>) -> Result<Value> {
        Ok(json!({
            "status": "dry-run",
            "tool": tool_name,
            "note": "No real call made — dry-run mode",
            // Stub common extract paths so chains with simple dotpaths succeed
            "results": [{"rxcui": "dry-run", "reactions": ["dry-run-event"]}],
            "total_matching": 0,
            "scores": {"PRR": 1.0, "ROR": 1.0, "IC": 0.0},
            "signal_assessment": "insufficient_data",
            "contingency_table": {"a_drug_event": 0},
            "total_score": 0,
            "category": "doubtful",
            "is_serious": false,
            "criteria_met": [],
            "count": 0,
            "status": "dry-run",
            "prr": 1.0,
            "chi_square": 0.0,
            "signal": false,
        }))
    }
}

/// Shell dispatcher — routes tool calls through `scripts/dispatch.py`.
pub struct ShellDispatcher {
    /// Path to the ferroforge root directory.
    pub ferroforge_dir: std::path::PathBuf,
}

impl ToolDispatcher for ShellDispatcher {
    fn call(&self, tool_name: &str, args: &HashMap<String, Value>) -> Result<Value> {
        use std::process::Command;
        let args_json = serde_json::to_string(args).context("serializing args")?;
        let dispatch_py = self.ferroforge_dir.join("scripts").join("dispatch.py");

        let output = Command::new("python3")
            .arg(&dispatch_py)
            .arg(tool_name)
            .arg(&args_json)
            .output()
            .with_context(|| format!("spawning dispatch.py for {tool_name}"))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            bail!("dispatch.py failed for {tool_name}: {stderr}");
        }

        let response: Value = serde_json::from_slice(&output.stdout)
            .with_context(|| format!("parsing dispatch.py output for {tool_name}"))?;
        Ok(response)
    }
}

// ---------------------------------------------------------------------------
// Runner — orchestrates the σ pipeline
// ---------------------------------------------------------------------------

/// Execute a relay chain against a dispatcher with initial `inputs`.
///
/// `inputs` seeds the variable context (e.g., `{"drug": "metformin", "event": "lactic acidosis"}`).
pub fn run_chain(
    chain: &RelayChainSpec,
    inputs: &HashMap<String, Value>,
    dispatcher: &dyn ToolDispatcher,
) -> Result<RelayRunResult> {
    // ς — execution context, grows with each hop's extracted values
    let mut context: HashMap<String, Value> = inputs.clone();
    let mut hop_results: Vec<HopResult> = Vec::with_capacity(chain.hops.len());
    let mut fidelities: Vec<HopFidelity> = Vec::with_capacity(chain.hops.len());

    for (i, hop) in chain.hops.iter().enumerate() {
        // μ — resolve args against current context
        let resolved_args = resolve_args(&hop.args, &context);

        // → — dispatch the tool call
        let (raw_response, succeeded) = match dispatcher.call(&hop.tool, &resolved_args) {
            Ok(resp) => (Some(resp), true),
            Err(e) => {
                let msg = e.to_string();
                tracing::warn!(hop = i, tool = %hop.tool, error = %msg, "hop tool call failed");
                if !hop.continue_on_error {
                    // Hard fail — compose fidelity up to this point as ZERO and bail
                    fidelities.push(HopFidelity::ZERO);
                    hop_results.push(HopResult {
                        hop_index: i,
                        tool: hop.tool.clone(),
                        resolved_args,
                        extracted: HashMap::new(),
                        raw_response: None,
                        fidelity: 0.0,
                        error: Some(msg.clone()),
                    });
                    // Pad remaining hops with zero fidelity for F_total
                    for _ in (i + 1)..chain.hops.len() {
                        fidelities.push(HopFidelity::ZERO);
                    }
                    let f_total = compose_fidelity(&fidelities);
                    return Ok(build_result(chain, hop_results, f_total, context));
                }
                (None, false)
            }
        };

        // κ — extract values from response
        let (extracted, fully_extracted) = match &raw_response {
            Some(resp) => extract_values(resp, &hop.extract),
            None => (HashMap::new(), hop.extract.is_empty()),
        };

        // ∂ — compute F_i
        let fi = hop_fidelity(succeeded, fully_extracted, hop.continue_on_error);
        fidelities.push(fi);

        // σ → ς — extend context with extracted values for next hops
        for (k, v) in &extracted {
            context.insert(k.clone(), v.clone());
        }

        hop_results.push(HopResult {
            hop_index: i,
            tool: hop.tool.clone(),
            resolved_args,
            extracted,
            raw_response,
            fidelity: fi.value(),
            error: if succeeded { None } else { Some(format!("hop {} errored (continue_on_error=true)", i)) },
        });
    }

    let f_total = compose_fidelity(&fidelities);
    Ok(build_result(chain, hop_results, f_total, context))
}

fn build_result(
    chain: &RelayChainSpec,
    hop_results: Vec<HopResult>,
    f_total: f64,
    final_context: HashMap<String, Value>,
) -> RelayRunResult {
    let hops_passed = hop_results.iter().filter(|h| (h.fidelity - 1.0).abs() < f64::EPSILON).count();
    let hops_failed = hop_results.iter().filter(|h| h.fidelity == 0.0).count();
    let hops_partial = hop_results.len() - hops_passed - hops_failed;

    RelayRunResult {
        chain: chain.name.clone(),
        description: chain.description.clone(),
        f_total,
        signal_loss_pct: (1.0 - f_total) * 100.0,
        hops_total: hop_results.len(),
        hops_passed,
        hops_partial,
        hops_failed,
        hop_results,
        final_context,
    }
}

// ---------------------------------------------------------------------------
// Report formatting
// ---------------------------------------------------------------------------

/// Print a human-readable report for a set of chain run results.
pub fn print_report(results: &[RelayRunResult]) {
    println!("{:<32} {:>5} {:>6} {:>7} {:>7} {:>8}", "Chain", "Hops", "Pass", "Partial", "Fail", "F_total");
    println!("{}", "-".repeat(72));
    for r in results {
        println!(
            "{:<32} {:>5} {:>6} {:>7} {:>7} {:>8.4}",
            r.chain, r.hops_total, r.hops_passed, r.hops_partial, r.hops_failed, r.f_total
        );
    }
    println!("{}", "-".repeat(72));
    let total_f: f64 = results.iter().map(|r| r.f_total).sum::<f64>() / results.len().max(1) as f64;
    println!("{:<32} {:>5} {:>50.4}", "AVERAGE", results.len(), total_f);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use anyhow::anyhow;

    // ------------------------------------------------------------------
    // dotpath_get
    // ------------------------------------------------------------------

    #[test]
    fn dotpath_simple_key() {
        let v = json!({"prr": 2.5});
        assert_eq!(dotpath_get(&v, "prr"), Some(&json!(2.5)));
    }

    #[test]
    fn dotpath_nested() {
        let v = json!({"scores": {"PRR": 3.1, "ROR": 2.8}});
        assert_eq!(dotpath_get(&v, "scores.PRR"), Some(&json!(3.1)));
    }

    #[test]
    fn dotpath_array_index() {
        let v = json!({"results": [{"rxcui": "41493"}]});
        assert_eq!(dotpath_get(&v, "results[0].rxcui"), Some(&json!("41493")));
    }

    #[test]
    fn dotpath_nested_array() {
        let v = json!({"results": [{"reactions": ["nausea", "vomiting"]}]});
        assert_eq!(dotpath_get(&v, "results[0].reactions[0]"), Some(&json!("nausea")));
    }

    #[test]
    fn dotpath_missing_key_returns_none() {
        let v = json!({"scores": {"PRR": 1.0}});
        assert!(dotpath_get(&v, "scores.ROR").is_none());
    }

    #[test]
    fn dotpath_out_of_bounds_returns_none() {
        let v = json!({"results": []});
        assert!(dotpath_get(&v, "results[0]").is_none());
    }

    // ------------------------------------------------------------------
    // substitute_vars
    // ------------------------------------------------------------------

    #[test]
    fn substitute_full_var() {
        let mut ctx = HashMap::new();
        ctx.insert("drug".to_owned(), json!("metformin"));
        assert_eq!(substitute_vars("$drug", &ctx), json!("metformin"));
    }

    #[test]
    fn substitute_typed_value() {
        let mut ctx = HashMap::new();
        ctx.insert("count".to_owned(), json!(42));
        assert_eq!(substitute_vars("$count", &ctx), json!(42));
    }

    #[test]
    fn substitute_partial_string() {
        let mut ctx = HashMap::new();
        ctx.insert("event".to_owned(), json!("lactic acidosis"));
        assert_eq!(substitute_vars("AE: $event", &ctx), json!("AE: lactic acidosis"));
    }

    #[test]
    fn substitute_unknown_var_preserved() {
        let ctx = HashMap::new();
        assert_eq!(substitute_vars("$unknown", &ctx), json!("$unknown"));
    }

    // ------------------------------------------------------------------
    // hop_fidelity
    // ------------------------------------------------------------------

    #[test]
    fn fidelity_perfect_on_success_full_extract() {
        assert_eq!(hop_fidelity(true, true, false), HopFidelity::PERFECT);
    }

    #[test]
    fn fidelity_partial_on_success_incomplete_extract() {
        let f = hop_fidelity(true, false, false);
        assert!((f.value() - 0.75).abs() < 1e-9);
    }

    #[test]
    fn fidelity_partial_on_error_with_continue() {
        assert_eq!(hop_fidelity(false, false, true), HopFidelity::PARTIAL);
    }

    #[test]
    fn fidelity_zero_on_error_hard_fail() {
        assert_eq!(hop_fidelity(false, false, false), HopFidelity::ZERO);
    }

    // ------------------------------------------------------------------
    // compose_fidelity
    // ------------------------------------------------------------------

    #[test]
    fn compose_three_perfect_hops() {
        let fs = vec![HopFidelity::PERFECT, HopFidelity::PERFECT, HopFidelity::PERFECT];
        assert!((compose_fidelity(&fs) - 1.0).abs() < 1e-9);
    }

    #[test]
    fn compose_with_partial() {
        let fs = vec![HopFidelity::PERFECT, HopFidelity::PARTIAL, HopFidelity::PERFECT];
        assert!((compose_fidelity(&fs) - 0.5).abs() < 1e-9);
    }

    #[test]
    fn compose_one_zero_collapses() {
        let fs = vec![HopFidelity::PERFECT, HopFidelity::ZERO, HopFidelity::PERFECT];
        assert!((compose_fidelity(&fs)).abs() < 1e-9);
    }

    // ------------------------------------------------------------------
    // run_chain with DryRunDispatcher
    // ------------------------------------------------------------------

    fn make_simple_chain() -> RelayChainSpec {
        let hop1 = HopSpec {
            tool: "rxnav_nlm_nih_gov_search_drugs".to_owned(),
            args: {
                let mut m = HashMap::new();
                m.insert("query".to_owned(), json!("$drug"));
                m
            },
            extract: {
                let mut m = HashMap::new();
                m.insert("rxcui".to_owned(), "results[0].rxcui".to_owned());
                m
            },
            continue_on_error: false,
        };
        let hop2 = HopSpec {
            tool: "api_fda_gov_search_adverse_events".to_owned(),
            args: {
                let mut m = HashMap::new();
                m.insert("drug_name".to_owned(), json!("$drug"));
                m.insert("serious".to_owned(), json!(true));
                m
            },
            extract: {
                let mut m = HashMap::new();
                m.insert("faers_total".to_owned(), "total_matching".to_owned());
                m
            },
            continue_on_error: false,
        };
        RelayChainSpec {
            name: "test-chain".to_owned(),
            description: "Unit test chain".to_owned(),
            hops: vec![hop1, hop2],
        }
    }

    #[test]
    fn dry_run_two_hop_chain_succeeds() {
        let chain = make_simple_chain();
        let mut inputs = HashMap::new();
        inputs.insert("drug".to_owned(), json!("metformin"));
        let dispatcher = DryRunDispatcher;
        let result = run_chain(&chain, &inputs, &dispatcher).expect("run_chain failed");
        assert_eq!(result.hops_total, 2);
        assert_eq!(result.chain, "test-chain");
        // F_total should be > 0
        assert!(result.f_total > 0.0, "F_total should be positive: {}", result.f_total);
    }

    #[test]
    fn dry_run_chain_context_has_inputs() {
        let chain = make_simple_chain();
        let mut inputs = HashMap::new();
        inputs.insert("drug".to_owned(), json!("warfarin"));
        let dispatcher = DryRunDispatcher;
        let result = run_chain(&chain, &inputs, &dispatcher).expect("run_chain failed");
        assert_eq!(result.final_context.get("drug"), Some(&json!("warfarin")));
    }

    #[test]
    fn continue_on_error_hop_does_not_abort() {
        // Build a chain where hop 1 always errors but has continue_on_error=true
        struct AlwaysErrDispatcher;
        impl ToolDispatcher for AlwaysErrDispatcher {
            fn call(&self, _tool: &str, _args: &HashMap<String, Value>) -> Result<Value> {
                Err(anyhow!("forced error"))
            }
        }

        let hop = HopSpec {
            tool: "some_tool".to_owned(),
            args: HashMap::new(),
            extract: HashMap::new(),
            continue_on_error: true,
        };
        let chain = RelayChainSpec {
            name: "continue-test".to_owned(),
            description: "Test continue_on_error".to_owned(),
            hops: vec![hop],
        };

        let dispatcher = AlwaysErrDispatcher;
        let result = run_chain(&chain, &HashMap::new(), &dispatcher).expect("run_chain failed");
        assert_eq!(result.hops_partial, 1, "errored hop with continue_on_error should be partial");
        assert!((result.f_total - 0.5).abs() < 1e-9);
    }

    #[test]
    fn hard_fail_hop_aborts_chain() {
        struct AlwaysErrDispatcher;
        impl ToolDispatcher for AlwaysErrDispatcher {
            fn call(&self, _tool: &str, _args: &HashMap<String, Value>) -> Result<Value> {
                Err(anyhow!("forced error"))
            }
        }

        let hop = HopSpec {
            tool: "some_tool".to_owned(),
            args: HashMap::new(),
            extract: HashMap::new(),
            continue_on_error: false,
        };
        let chain = RelayChainSpec {
            name: "hard-fail-test".to_owned(),
            description: "Test hard fail".to_owned(),
            hops: vec![hop],
        };

        let dispatcher = AlwaysErrDispatcher;
        let result = run_chain(&chain, &HashMap::new(), &dispatcher).expect("run_chain should not Err — it returns zero fidelity");
        assert_eq!(result.hops_failed, 1);
        assert!((result.f_total).abs() < 1e-9);
    }

    // ------------------------------------------------------------------
    // extract_values
    // ------------------------------------------------------------------

    #[test]
    fn extract_all_paths_present() {
        let response = json!({"scores": {"PRR": 2.0, "ROR": 1.8}});
        let mut extract = HashMap::new();
        extract.insert("prr".to_owned(), "scores.PRR".to_owned());
        extract.insert("ror".to_owned(), "scores.ROR".to_owned());
        let (out, fully) = extract_values(&response, &extract);
        assert!(fully);
        assert_eq!(out.get("prr"), Some(&json!(2.0)));
        assert_eq!(out.get("ror"), Some(&json!(1.8)));
    }

    #[test]
    fn extract_missing_path_not_fully_populated() {
        let response = json!({"scores": {"PRR": 2.0}});
        let mut extract = HashMap::new();
        extract.insert("ror".to_owned(), "scores.ROR".to_owned());
        let (_, fully) = extract_values(&response, &extract);
        assert!(!fully);
    }

    #[test]
    fn extract_empty_spec_is_fully_populated() {
        let response = json!({});
        let (_, fully) = extract_values(&response, &HashMap::new());
        assert!(fully);
    }
}
