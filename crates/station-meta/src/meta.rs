//! Single-entry dispatcher for the meta-tool.
//!
//! The MCP tool accepts a `MetaRequest` and produces a `MetaResponse`. Mode
//! determines which arm runs:
//!
//! | `mode`     | Required fields                    | Action                                |
//! |------------|------------------------------------|---------------------------------------|
//! | `discover` | `intent`                           | Rank indexed tools, return top-N      |
//! | `execute`  | `config`, `tool`, `params` (opt)   | Forward to Cloud Run, return JSON     |
//! | `explain`  | none (optional `pool`)             | Return budget taxonomy + (opt) regime |
//!
//! Invalid combinations produce `MetaResponse::error` with a specific reason
//! so the model can self-correct without re-querying.
//!
//! ## The `explain` arm
//!
//! `explain` gives the model self-visibility into its own token economics
//! using the Atkinson Energy Charge taxonomy (same as `nexcore-energy`):
//!
//! - No `pool` field → return the reference taxonomy (regime bands, waste classes)
//! - With `pool = {t_atp, t_adp, t_amp}` → also compute the caller's current
//!   regime and recommended strategy
//!
//! Constants are inlined (not pulled from `nexcore-energy`) to keep
//! `station-meta` self-contained. If the thresholds ever drift between crates,
//! add a shared constants crate.

use anyhow::Result;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::discover::{ConfigIndex, IdfRanker, JaccardRanker, Ranker, ToolCandidate, discover_with};
use crate::execute::{ExecutionRequest, ExecutionResult, StationClient, execute};
use crate::DEFAULT_DISCOVER_LIMIT;

/// Incoming request to the meta-tool.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MetaRequest {
    /// `"discover"`, `"execute"`, or `"explain"`.
    pub mode: String,
    /// Intent string for discovery.
    #[serde(default)]
    pub intent: Option<String>,
    /// Max discover results.
    #[serde(default)]
    pub limit: Option<usize>,
    /// Config stem for execute.
    #[serde(default)]
    pub config: Option<String>,
    /// Tool name for execute.
    #[serde(default)]
    pub tool: Option<String>,
    /// Parameters for execute.
    #[serde(default)]
    pub params: Option<Value>,
    /// Optional token-pool snapshot for `explain` — if provided, the response
    /// computes the caller's current regime and strategy recommendation.
    /// Keys: `t_atp`, `t_adp`, `t_amp` (all u64).
    #[serde(default)]
    pub pool: Option<PoolSnapshot>,
    /// Optional ranker selector for `discover`. `"jaccard"` (default) or `"idf"`.
    /// Unrecognised values fall back to Jaccard with a noted error field
    /// so the model learns the right vocabulary without an outright failure.
    #[serde(default)]
    pub ranker: Option<String>,
}

/// Minimal token-pool snapshot accepted by `mode=explain`.
///
/// Mirrors `nexcore_energy::TokenPool` but defined locally so `station-meta`
/// doesn't take a dependency on the nexcore workspace.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct PoolSnapshot {
    /// Tokens remaining (available for productive work).
    pub t_atp: u64,
    /// Tokens spent productively (artifacts, tool calls with value).
    pub t_adp: u64,
    /// Tokens wasted (retries, failed tool calls, verbose no-op output).
    pub t_amp: u64,
}

/// Envelope returned to the caller.
///
/// Exactly one of `candidates`, `execution`, `explanation`, or `error` is populated.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MetaResponse {
    /// Echo of the dispatched mode for observability.
    pub mode: String,
    /// Populated on successful discovery.
    #[serde(default)]
    pub candidates: Option<Vec<ToolCandidate>>,
    /// Populated on successful execution.
    #[serde(default)]
    pub execution: Option<ExecutionResult>,
    /// Populated on `mode=explain`.
    #[serde(default)]
    pub explanation: Option<ExplainResponse>,
    /// Populated on request-shape errors or transport errors.
    #[serde(default)]
    pub error: Option<String>,
}

// ============================================================================
// Explain response — token-budget self-visibility for the model
// ============================================================================

/// Atkinson Energy Charge threshold for Anabolic regime.
pub const EC_ANABOLIC: f64 = 0.85;
/// Threshold for Homeostatic regime (lower bound).
pub const EC_HOMEOSTATIC: f64 = 0.70;
/// Threshold for Catabolic regime (lower bound).
pub const EC_CATABOLIC: f64 = 0.50;

/// Metabolic regime inferred from `PoolSnapshot`.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum Regime {
    /// EC > 0.85 — invest freely.
    Anabolic,
    /// 0.70 ≤ EC ≤ 0.85 — balanced operation.
    Homeostatic,
    /// 0.50 ≤ EC < 0.70 — conserve.
    Catabolic,
    /// EC < 0.50 — checkpoint and halt.
    Crisis,
}

impl Regime {
    /// Classify a computed EC into a regime.
    #[must_use]
    pub fn from_ec(ec: f64) -> Self {
        if ec > EC_ANABOLIC {
            Self::Anabolic
        } else if ec >= EC_HOMEOSTATIC {
            Self::Homeostatic
        } else if ec >= EC_CATABOLIC {
            Self::Catabolic
        } else {
            Self::Crisis
        }
    }

    /// One-line recommendation paired with the regime.
    #[must_use]
    pub const fn recommendation(self) -> &'static str {
        match self {
            Self::Anabolic => "Invest freely — Opus permitted, deep exploration OK.",
            Self::Homeostatic => "Balanced — Sonnet for high-yield work, Haiku for low-yield.",
            Self::Catabolic => "Conserve — Haiku + cache-first, minimize exploration.",
            Self::Crisis => "Checkpoint — save state and stop, do not call expensive models.",
        }
    }
}

/// The explanation payload. Contains the stable taxonomy; the `current` field
/// is populated only when the caller provided a `pool` snapshot.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExplainResponse {
    /// Brief description of the budget model.
    pub summary: String,
    /// Regime threshold bands (stable across versions).
    pub regimes: Vec<RegimeBand>,
    /// The five waste classes the Stop hook (token-waste-autopsy) measures.
    pub waste_classes: Vec<WasteClassDesc>,
    /// The three model-cost tiers (Haiku=1.0 baseline).
    pub strategy_tiers: Vec<StrategyTier>,
    /// Populated only if the caller passed a `pool` snapshot.
    #[serde(default)]
    pub current: Option<CurrentState>,
}

/// One threshold band of the regime taxonomy.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RegimeBand {
    pub regime: Regime,
    pub ec_min: f64,
    pub ec_max: f64,
    pub recommendation: String,
}

/// One waste class and its prevention hint.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WasteClassDesc {
    pub name: String,
    pub prevention: String,
}

/// One strategy tier with relative token cost.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StrategyTier {
    pub strategy: String,
    pub relative_cost: f64,
    pub when: String,
}

/// Per-request computed state when `pool` was provided.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CurrentState {
    pub energy_charge: f64,
    pub regime: Regime,
    pub recommendation: String,
    pub waste_ratio: f64,
    pub burn_rate: f64,
    pub total: u64,
}

/// Build the stable reference taxonomy. Pure function, no inputs, no I/O.
#[must_use]
fn build_taxonomy() -> (Vec<RegimeBand>, Vec<WasteClassDesc>, Vec<StrategyTier>) {
    let regimes = vec![
        RegimeBand {
            regime: Regime::Anabolic,
            ec_min: EC_ANABOLIC,
            ec_max: 1.0,
            recommendation: Regime::Anabolic.recommendation().into(),
        },
        RegimeBand {
            regime: Regime::Homeostatic,
            ec_min: EC_HOMEOSTATIC,
            ec_max: EC_ANABOLIC,
            recommendation: Regime::Homeostatic.recommendation().into(),
        },
        RegimeBand {
            regime: Regime::Catabolic,
            ec_min: EC_CATABOLIC,
            ec_max: EC_HOMEOSTATIC,
            recommendation: Regime::Catabolic.recommendation().into(),
        },
        RegimeBand {
            regime: Regime::Crisis,
            ec_min: 0.0,
            ec_max: EC_CATABOLIC,
            recommendation: Regime::Crisis.recommendation().into(),
        },
    ];
    let waste_classes = vec![
        WasteClassDesc {
            name: "HeatLoss".into(),
            prevention: "Compress output. Advertised surface that the model never references is heat.".into(),
        },
        WasteClassDesc {
            name: "SubstrateCycling".into(),
            prevention: "Don't call MCP for data the SessionStart hook already injected.".into(),
        },
        WasteClassDesc {
            name: "Uncoupled".into(),
            prevention: "Require artifacts. Assistant turns without Edit/Write/Bash are suspect.".into(),
        },
        WasteClassDesc {
            name: "FutileCycling".into(),
            prevention: "Check permissions before editing. Avoid Read→Write→Read loops on the same file.".into(),
        },
        WasteClassDesc {
            name: "Retry".into(),
            prevention: "Validate inputs before tool calls. Don't retry the same call expecting different results.".into(),
        },
    ];
    let strategy_tiers = vec![
        StrategyTier {
            strategy: "Opus".into(),
            relative_cost: 15.0,
            when: "Anabolic regime AND coupling_ratio > 2.0 (high-yield work).".into(),
        },
        StrategyTier {
            strategy: "Sonnet".into(),
            relative_cost: 5.0,
            when: "Homeostatic regime with high coupling, or Anabolic with low coupling.".into(),
        },
        StrategyTier {
            strategy: "Haiku".into(),
            relative_cost: 1.0,
            when: "Catabolic regime, low-yield lookups, or default for non-complex tasks.".into(),
        },
    ];
    (regimes, waste_classes, strategy_tiers)
}

/// Compute the `CurrentState` from a `PoolSnapshot` using the Atkinson formula.
#[must_use]
fn compute_current(pool: &PoolSnapshot) -> CurrentState {
    let total = pool.t_atp + pool.t_adp + pool.t_amp;
    #[allow(clippy::cast_precision_loss)]
    let (ec, waste_ratio, burn_rate) = if total == 0 {
        (1.0, 0.0, 0.0)
    } else {
        let total_f = total as f64;
        let ec = (pool.t_atp as f64 + 0.5 * pool.t_adp as f64) / total_f;
        let spent = pool.t_adp + pool.t_amp;
        let waste = if spent == 0 {
            0.0
        } else {
            pool.t_amp as f64 / spent as f64
        };
        let burn = 1.0 - (pool.t_atp as f64 / total_f);
        (ec, waste, burn)
    };
    let regime = Regime::from_ec(ec);
    CurrentState {
        energy_charge: ec,
        regime,
        recommendation: regime.recommendation().into(),
        waste_ratio,
        burn_rate,
        total,
    }
}

impl MetaResponse {
    fn discovery(hits: Vec<ToolCandidate>) -> Self {
        Self {
            mode: "discover".into(),
            candidates: Some(hits),
            execution: None,
            explanation: None,
            error: None,
        }
    }

    fn execution(result: ExecutionResult) -> Self {
        Self {
            mode: "execute".into(),
            candidates: None,
            execution: Some(result),
            explanation: None,
            error: None,
        }
    }

    fn explanation(exp: ExplainResponse) -> Self {
        Self {
            mode: "explain".into(),
            candidates: None,
            execution: None,
            explanation: Some(exp),
            error: None,
        }
    }

    fn err(mode: &str, msg: impl Into<String>) -> Self {
        Self {
            mode: mode.into(),
            candidates: None,
            execution: None,
            explanation: None,
            error: Some(msg.into()),
        }
    }
}

/// Build the explain payload, optionally personalised by the caller's pool.
#[must_use]
pub fn build_explain(pool: Option<&PoolSnapshot>) -> ExplainResponse {
    let (regimes, waste_classes, strategy_tiers) = build_taxonomy();
    ExplainResponse {
        summary: "Atkinson Energy Charge (EC = (tATP + 0.5·tADP) / total) drives regime selection. \
                  Provide a `pool` snapshot to see your current regime."
            .into(),
        regimes,
        waste_classes,
        strategy_tiers,
        current: pool.map(compute_current),
    }
}

/// Route one meta-request to the correct arm.
///
/// `index` powers discovery; `client` powers execution. Either may be unused
/// depending on mode.
pub fn dispatch(
    req: MetaRequest,
    index: &ConfigIndex,
    client: &dyn StationClient,
) -> Result<MetaResponse> {
    match req.mode.as_str() {
        "discover" => match req.intent {
            Some(s) if !s.trim().is_empty() => {
                let limit = req.limit.unwrap_or(DEFAULT_DISCOVER_LIMIT);
                // Select ranker. Default "jaccard" preserves pre-ranker behavior.
                // Unknown values → Jaccard with a soft-error note so the model
                // sees its mistake without losing the result set.
                let (ranker, unknown_ranker_note) = match req
                    .ranker
                    .as_deref()
                    .map(str::to_ascii_lowercase)
                    .as_deref()
                {
                    None | Some("") | Some("jaccard") => (&JaccardRanker as &dyn Ranker, None),
                    Some("idf") => (&IdfRanker as &dyn Ranker, None),
                    Some(other) => (
                        &JaccardRanker as &dyn Ranker,
                        Some(format!(
                            "unknown ranker `{other}`; fell back to jaccard. \
                             Valid: jaccard | idf"
                        )),
                    ),
                };
                let hits = discover_with(index, &s, limit, ranker);
                let mut resp = MetaResponse::discovery(hits);
                if let Some(note) = unknown_ranker_note {
                    resp.error = Some(note);
                }
                Ok(resp)
            }
            _ => Ok(MetaResponse::err(
                "discover",
                "mode=discover requires non-empty `intent`",
            )),
        },
        "explain" => {
            // No required fields. `pool` is optional.
            Ok(MetaResponse::explanation(build_explain(req.pool.as_ref())))
        }
        "execute" => {
            let config = match req.config {
                Some(c) if !c.is_empty() => c,
                _ => {
                    return Ok(MetaResponse::err(
                        "execute",
                        "mode=execute requires `config`",
                    ));
                }
            };
            let tool = match req.tool {
                Some(t) if !t.is_empty() => t,
                _ => {
                    return Ok(MetaResponse::err("execute", "mode=execute requires `tool`"));
                }
            };
            let params = req.params.unwrap_or_else(|| serde_json::json!({}));
            let exec_req = ExecutionRequest {
                config,
                tool,
                params,
            };
            let result = execute(client, exec_req)?;
            Ok(MetaResponse::execution(result))
        }
        other => Ok(MetaResponse::err(
            other,
            format!("unknown mode `{other}`; expected `discover`, `execute`, or `explain`"),
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::discover::{IndexEntry, tokenize_for_test};
    use crate::execute::{ExecutionRequest, ExecutionResult, StationClient};
    use std::cell::RefCell;

    struct NoopClient;
    impl StationClient for NoopClient {
        fn call(&self, _: &ExecutionRequest) -> Result<ExecutionResult> {
            Ok(ExecutionResult::ok(serde_json::json!({"noop": true})))
        }
    }

    struct RecordingClient {
        last: RefCell<Option<ExecutionRequest>>,
    }
    impl StationClient for RecordingClient {
        fn call(&self, req: &ExecutionRequest) -> Result<ExecutionResult> {
            *self.last.borrow_mut() = Some(req.clone());
            Ok(ExecutionResult::ok(serde_json::json!({"recorded": true})))
        }
    }

    fn mk_index() -> ConfigIndex {
        // `from_entries` computes corpus stats; required by IdfRanker and harmless
        // for JaccardRanker (which ignores them).
        ConfigIndex::from_entries(vec![IndexEntry {
            config_stem: "openfda".into(),
            title: "openFDA FAERS".into(),
            domain: "api.fda.gov".into(),
            tool: "search_adverse_events".into(),
            description: "Search FAERS adverse event reports".into(),
            tokens: tokenize_for_test(&[
                "openFDA FAERS",
                "search_adverse_events",
                "Search FAERS adverse event reports",
            ]),
        }])
    }

    #[test]
    fn dispatch_discover_happy_path() {
        let idx = mk_index();
        let req = MetaRequest {
            mode: "discover".into(),
            intent: Some("adverse event search".into()),
            limit: Some(3),
            config: None,
            tool: None,
            params: None,
            pool: None,
            ranker: None,
        };
        let resp = dispatch(req, &idx, &NoopClient).expect("ok");
        assert_eq!(resp.mode, "discover");
        assert!(resp.error.is_none());
        let hits = resp.candidates.expect("candidates");
        assert_eq!(hits[0].tool, "search_adverse_events");
    }

    #[test]
    fn dispatch_discover_empty_intent_is_shape_error() {
        let idx = mk_index();
        let req = MetaRequest {
            mode: "discover".into(),
            intent: Some("   ".into()),
            limit: None,
            config: None,
            tool: None,
            params: None,
            pool: None,
            ranker: None,
        };
        let resp = dispatch(req, &idx, &NoopClient).expect("ok");
        assert!(resp.error.is_some());
        assert!(resp.candidates.is_none());
    }

    #[test]
    fn dispatch_execute_forwards_to_client() {
        let idx = mk_index();
        let client = RecordingClient {
            last: RefCell::new(None),
        };
        let req = MetaRequest {
            mode: "execute".into(),
            intent: None,
            limit: None,
            config: Some("openfda".into()),
            tool: Some("search_adverse_events".into()),
            params: Some(serde_json::json!({"drug_name": "metformin"})),
            pool: None,
            ranker: None,
        };
        let resp = dispatch(req, &idx, &client).expect("ok");
        assert_eq!(resp.mode, "execute");
        assert!(resp.error.is_none());
        let last = client.last.borrow().clone().expect("recorded");
        assert_eq!(last.config, "openfda");
        assert_eq!(last.tool, "search_adverse_events");
        assert_eq!(last.params, serde_json::json!({"drug_name": "metformin"}));
    }

    #[test]
    fn dispatch_execute_missing_config_is_shape_error() {
        let idx = mk_index();
        let req = MetaRequest {
            mode: "execute".into(),
            intent: None,
            limit: None,
            config: None,
            tool: Some("search_adverse_events".into()),
            params: None,
            pool: None,
            ranker: None,
        };
        let resp = dispatch(req, &idx, &NoopClient).expect("ok");
        assert!(resp.error.is_some(), "missing config should error");
        assert!(resp.execution.is_none());
    }

    #[test]
    fn dispatch_execute_missing_tool_is_shape_error() {
        let idx = mk_index();
        let req = MetaRequest {
            mode: "execute".into(),
            intent: None,
            limit: None,
            config: Some("openfda".into()),
            tool: None,
            params: None,
            pool: None,
            ranker: None,
        };
        let resp = dispatch(req, &idx, &NoopClient).expect("ok");
        assert!(resp.error.is_some());
    }

    #[test]
    fn dispatch_unknown_mode_errors_with_hint() {
        let idx = mk_index();
        let req = MetaRequest {
            mode: "snorkel".into(),
            intent: None,
            limit: None,
            config: None,
            tool: None,
            params: None,
            pool: None,
            ranker: None,
        };
        let resp = dispatch(req, &idx, &NoopClient).expect("ok");
        let err = resp.error.expect("error");
        assert!(err.contains("snorkel"));
        assert!(err.contains("discover") && err.contains("execute") && err.contains("explain"));
    }

    #[test]
    fn dispatch_explain_without_pool_returns_taxonomy_only() {
        let idx = mk_index();
        let req = MetaRequest {
            mode: "explain".into(),
            intent: None,
            limit: None,
            config: None,
            tool: None,
            params: None,
            pool: None,
            ranker: None,
        };
        let resp = dispatch(req, &idx, &NoopClient).expect("ok");
        assert_eq!(resp.mode, "explain");
        assert!(resp.error.is_none());
        let exp = resp.explanation.expect("explanation");
        assert_eq!(exp.regimes.len(), 4, "must describe all 4 regimes");
        assert_eq!(exp.waste_classes.len(), 5, "must describe 5 waste classes");
        assert_eq!(exp.strategy_tiers.len(), 3);
        assert!(exp.current.is_none(), "no pool → no current state");
    }

    #[test]
    fn dispatch_explain_with_pool_computes_current_regime() {
        let idx = mk_index();
        // 90% unused, 10% productive, 0% waste → EC ~0.95 → Anabolic
        let req = MetaRequest {
            mode: "explain".into(),
            intent: None,
            limit: None,
            config: None,
            tool: None,
            params: None,
            pool: Some(PoolSnapshot {
                t_atp: 900,
                t_adp: 100,
                t_amp: 0,
            }),
            ranker: None,
        };
        let resp = dispatch(req, &idx, &NoopClient).expect("ok");
        let exp = resp.explanation.expect("explanation");
        let current = exp.current.expect("current state with pool");
        assert_eq!(current.regime, Regime::Anabolic, "EC=0.95 should be Anabolic");
        assert!((current.energy_charge - 0.95).abs() < 1e-9);
        assert_eq!(current.total, 1000);
    }

    #[test]
    fn dispatch_explain_crisis_regime_from_heavy_waste() {
        let idx = mk_index();
        // 20% left, 10% productive, 70% waste → EC = 0.25 → Crisis
        let req = MetaRequest {
            mode: "explain".into(),
            intent: None,
            limit: None,
            config: None,
            tool: None,
            params: None,
            pool: Some(PoolSnapshot {
                t_atp: 200,
                t_adp: 100,
                t_amp: 700,
            }),
            ranker: None,
        };
        let resp = dispatch(req, &idx, &NoopClient).expect("ok");
        let exp = resp.explanation.expect("explanation");
        let current = exp.current.expect("current");
        assert_eq!(current.regime, Regime::Crisis);
        assert!(current.recommendation.contains("Checkpoint"));
        // Waste ratio = t_amp / (t_adp + t_amp) = 700/800 = 0.875
        assert!((current.waste_ratio - 0.875).abs() < 1e-9);
    }

    #[test]
    fn regime_boundary_exactly_at_anabolic_threshold_is_homeostatic() {
        // EC == 0.85 should be Homeostatic (strict > on anabolic)
        assert_eq!(Regime::from_ec(0.85), Regime::Homeostatic);
        assert_eq!(Regime::from_ec(0.8500001), Regime::Anabolic);
        assert_eq!(Regime::from_ec(0.70), Regime::Homeostatic);
        assert_eq!(Regime::from_ec(0.6999), Regime::Catabolic);
        assert_eq!(Regime::from_ec(0.4999), Regime::Crisis);
    }

    #[test]
    fn dispatch_discover_defaults_to_jaccard_when_ranker_omitted() {
        let idx = mk_index();
        let req = MetaRequest {
            mode: "discover".into(),
            intent: Some("adverse event search".into()),
            limit: Some(3),
            config: None,
            tool: None,
            params: None,
            pool: None,
            ranker: None,
        };
        let resp = dispatch(req, &idx, &NoopClient).expect("ok");
        // Null ranker → Jaccard. No error set.
        assert!(resp.error.is_none());
        let hits = resp.candidates.expect("candidates");
        // Single-entry test index, so top hit is unambiguous regardless of
        // ranker. Assertion here is on "no error + hits returned".
        assert!(!hits.is_empty());
    }

    #[test]
    fn dispatch_discover_accepts_idf_ranker() {
        let idx = mk_index();
        let req = MetaRequest {
            mode: "discover".into(),
            intent: Some("adverse event".into()),
            limit: Some(3),
            config: None,
            tool: None,
            params: None,
            pool: None,
            ranker: Some("idf".into()),
        };
        let resp = dispatch(req, &idx, &NoopClient).expect("ok");
        assert!(resp.error.is_none(), "`idf` must not set error");
        let hits = resp.candidates.expect("candidates");
        assert!(!hits.is_empty());
    }

    #[test]
    fn dispatch_discover_unknown_ranker_falls_back_with_note() {
        let idx = mk_index();
        let req = MetaRequest {
            mode: "discover".into(),
            intent: Some("adverse event".into()),
            limit: Some(3),
            config: None,
            tool: None,
            params: None,
            pool: None,
            ranker: Some("bm42-turbo".into()),
        };
        let resp = dispatch(req, &idx, &NoopClient).expect("ok");
        // Soft-error: candidates still populated (using Jaccard), but error
        // field carries a hint so the model learns the vocabulary.
        let note = resp.error.as_ref().expect("soft-error note");
        assert!(note.contains("bm42-turbo"));
        assert!(note.contains("jaccard") && note.contains("idf"));
        assert!(
            resp.candidates.as_ref().is_some_and(|c| !c.is_empty()),
            "unknown ranker must still return results (not fail hard)"
        );
    }

    #[test]
    fn dispatch_discover_case_insensitive_ranker_names() {
        let idx = mk_index();
        for name in ["JACCARD", "Jaccard", "IDF", "Idf"] {
            let req = MetaRequest {
                mode: "discover".into(),
                intent: Some("adverse event".into()),
                limit: Some(3),
                config: None,
                tool: None,
                params: None,
                pool: None,
                ranker: Some(name.into()),
            };
            let resp = dispatch(req, &idx, &NoopClient).expect("ok");
            assert!(
                resp.error.is_none(),
                "case-insensitive ranker name `{name}` should be accepted"
            );
        }
    }

    #[test]
    fn dispatch_execute_defaults_params_to_empty_object() {
        let idx = mk_index();
        let client = RecordingClient {
            last: RefCell::new(None),
        };
        let req = MetaRequest {
            mode: "execute".into(),
            intent: None,
            limit: None,
            config: Some("openfda".into()),
            tool: Some("search_adverse_events".into()),
            params: None,
            pool: None,
            ranker: None,
        };
        let _ = dispatch(req, &idx, &client).expect("ok");
        let last = client.last.borrow().clone().expect("recorded");
        assert_eq!(last.params, serde_json::json!({}));
    }
}
