//! Discovery: intent string -> ranked tool candidates.
//!
//! Loads `configs/*.json` once, flattens to `(config, tool)` pairs, and ranks
//! by token-overlap score between the intent and each tool's searchable text
//! (config title + tool name + tool description).
//!
//! This is a deliberate **T1 + T2** primitive composition:
//! - `μ` (mapping): intent -> text corpus per tool
//! - `κ` (comparison): token-set Jaccard with a domain-boost multiplier
//! - `σ` (sequence): sorted descending by score, truncated to `limit`

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};

/// One tool parameter as declared in a Station config.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolParameter {
    /// Parameter name.
    pub name: String,
    /// JSON-schema type (`string`, `integer`, `boolean`, `array`, `object`).
    #[serde(rename = "type")]
    pub ty: String,
    /// Human-readable description.
    #[serde(default)]
    pub description: String,
    /// Whether the parameter is required.
    #[serde(default)]
    pub required: bool,
}

/// One tool inside a Station config.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConfigTool {
    /// Tool name (unique within the config).
    pub name: String,
    /// Tool description.
    #[serde(default)]
    pub description: String,
    /// Declared parameters.
    #[serde(default)]
    pub parameters: Vec<ToolParameter>,
}

/// A single Station config JSON shape.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StationConfig {
    /// Domain the config routes to (e.g. `api.fda.gov`).
    pub domain: String,
    /// Human-readable title.
    #[serde(default)]
    pub title: String,
    /// Config-level description.
    #[serde(default)]
    pub description: String,
    /// Tools exposed by this config.
    #[serde(default)]
    pub tools: Vec<ConfigTool>,
}

/// Loaded catalog of all configs — built once, reused per discovery call.
#[derive(Debug, Clone, Default)]
pub struct ConfigIndex {
    /// Flattened (config_stem, tool) rows ready for ranking.
    pub entries: Vec<IndexEntry>,
    /// Document frequency per token — how many entries contain each token.
    /// Precomputed for IDF-based rankers; JaccardRanker ignores this.
    pub doc_freq: HashMap<String, u32>,
    /// Total number of entries (`N` in IDF formulas).
    pub doc_count: u32,
}

/// One indexed (config, tool) row.
#[derive(Debug, Clone)]
pub struct IndexEntry {
    /// Filename stem (e.g. `openfda`) — debug/human hint.
    pub config_stem: String,
    /// Config title (human-readable).
    pub title: String,
    /// Config domain (the ROUTING KEY — what execute accepts).
    pub domain: String,
    /// Tool name within the config.
    pub tool: String,
    /// Tool description.
    pub description: String,
    /// Precomputed lowercase token set for ranking.
    pub tokens: HashSet<String>,
}

/// A ranked discovery result.
///
/// `config` and `tool` are the exact values to pass back to `mode=execute`.
/// The meta-tool contract guarantees: `discover(intent) → {config, tool, ...}`
/// then `execute({config, tool, params})` works without any transformation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolCandidate {
    /// Config addressing key — the domain (e.g. `api.fda.gov`) that execute accepts.
    pub config: String,
    /// Tool name to pass to `execute` (matches the config's declared tool name).
    pub tool: String,
    /// Filename stem (e.g. `openfda`) — human/debug hint, NOT the routing key.
    pub config_stem: String,
    /// Config title (human context).
    pub title: String,
    /// Tool description.
    pub description: String,
    /// Match score in `[0, 1+]`. Higher is better.
    pub score: f64,
}

impl ConfigIndex {
    /// Load every `*.json` under `configs_dir` into the index.
    ///
    /// Non-JSON entries and files that fail to parse are skipped with a
    /// `tracing::warn`; they do not abort the load. This matches Station's
    /// own tolerance for partial config fleets.
    pub fn load(configs_dir: impl AsRef<Path>) -> Result<Self> {
        let dir = configs_dir.as_ref();
        let read = fs::read_dir(dir).with_context(|| format!("reading {}", dir.display()))?;

        let mut entries = Vec::new();
        for entry_result in read {
            let entry = match entry_result {
                Ok(e) => e,
                Err(err) => {
                    tracing::warn!(error = %err, "skipping unreadable dir entry");
                    continue;
                }
            };
            let path = entry.path();
            if path.extension().and_then(|s| s.to_str()) != Some("json") {
                continue;
            }
            match load_config(&path) {
                Ok(rows) => entries.extend(rows),
                Err(err) => {
                    tracing::warn!(path = %path.display(), error = %err, "skipping bad config");
                }
            }
        }
        Ok(Self::from_entries(entries))
    }

    /// Build an index from pre-computed entries. Precomputes corpus statistics
    /// (document frequencies) needed by IDF-based rankers. Used by `load` and
    /// by tests that construct indexes directly.
    #[must_use]
    pub fn from_entries(entries: Vec<IndexEntry>) -> Self {
        let mut doc_freq: HashMap<String, u32> = HashMap::new();
        for entry in &entries {
            for token in &entry.tokens {
                *doc_freq.entry(token.clone()).or_insert(0) += 1;
            }
        }
        let doc_count = u32::try_from(entries.len()).unwrap_or(u32::MAX);
        Self {
            entries,
            doc_freq,
            doc_count,
        }
    }

    /// Total number of (config, tool) rows in the index.
    #[must_use]
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Whether the index is empty.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

fn load_config(path: &PathBuf) -> Result<Vec<IndexEntry>> {
    let text = fs::read_to_string(path)?;
    let cfg: StationConfig = serde_json::from_str(&text)?;
    let config_stem = path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .to_string();

    let mut rows = Vec::with_capacity(cfg.tools.len());
    for tool in cfg.tools {
        let tokens = tokenize(&[
            &cfg.title,
            &cfg.description,
            &cfg.domain,
            &tool.name,
            &tool.description,
        ]);
        rows.push(IndexEntry {
            config_stem: config_stem.clone(),
            title: cfg.title.clone(),
            domain: cfg.domain.clone(),
            tool: tool.name,
            description: tool.description,
            tokens,
        });
    }
    Ok(rows)
}

/// Crate-internal tokenize helper exposed for cross-module tests.
#[doc(hidden)]
pub fn tokenize_for_test(sources: &[&str]) -> HashSet<String> {
    tokenize(sources)
}

/// Tokenize one or more strings into a lowercase alphanumeric token set.
/// Tokens shorter than 3 chars are dropped (they're too noisy for ranking).
fn tokenize(sources: &[&str]) -> HashSet<String> {
    let mut out = HashSet::new();
    for src in sources {
        for raw in src.split(|c: char| !c.is_alphanumeric()) {
            let lower = raw.to_ascii_lowercase();
            if lower.len() >= 3 {
                out.insert(lower);
            }
        }
    }
    out
}

/// Rank tools by overlap with `intent`, return top `limit` candidates.
///
/// Uses [`JaccardRanker`] (Jaccard + exact-name boost). For IDF-weighted ranking
/// over corpus statistics, call [`discover_with`] with [`IdfRanker`] instead.
#[must_use]
pub fn discover(index: &ConfigIndex, intent: &str, limit: usize) -> Vec<ToolCandidate> {
    discover_with(index, intent, limit, &JaccardRanker)
}

// ============================================================================
// Ranker trait + two implementations
// ============================================================================
//
// `discover()` uses `JaccardRanker` (current behavior, backward compatible).
// `discover_with(&IdfRanker, ...)` ranks by IDF-weighted overlap — rare terms
// like "FAERS" outweigh common terms like "search". Better precision when the
// corpus has a long-tail vocabulary (which ours does — 3,095 tools).

/// A scoring function over `(intent, entry, corpus)`. Returns a non-negative
/// score; higher is more relevant. Zero means "no match" and is filtered out.
pub trait Ranker: Sync {
    /// Score an entry against the intent. Corpus-wide stats are available via `index`.
    fn score(
        &self,
        intent_tokens: &HashSet<String>,
        intent_lower: &str,
        entry: &IndexEntry,
        index: &ConfigIndex,
    ) -> f64;
}

/// Default ranker: Jaccard similarity + exact tool-name boost.
///
/// - Jaccard = |intent ∩ entry| / |intent ∪ entry|  in `[0, 1]`
/// - Exact boost = +0.5 if intent contains the tool name verbatim
///
/// Simple, no corpus-wide statistics required.
#[derive(Debug, Clone, Copy, Default)]
pub struct JaccardRanker;

impl Ranker for JaccardRanker {
    fn score(
        &self,
        intent_tokens: &HashSet<String>,
        intent_lower: &str,
        entry: &IndexEntry,
        _index: &ConfigIndex,
    ) -> f64 {
        let inter = intent_tokens.intersection(&entry.tokens).count();
        if inter == 0 {
            return 0.0;
        }
        let union = intent_tokens.union(&entry.tokens).count().max(1);
        #[allow(clippy::cast_precision_loss)]
        let jaccard = inter as f64 / union as f64;

        let tool_lower = entry.tool.replace('_', " ").to_ascii_lowercase();
        let exact_boost = if intent_lower.contains(&tool_lower) || intent_lower.contains(&entry.tool) {
            0.5
        } else {
            0.0
        };
        jaccard + exact_boost
    }
}

/// IDF-weighted presence ranker. For each intent term that appears in the entry,
/// add its inverse-document-frequency weight:
///
/// ```text
/// idf(t) = ln((N - df(t) + 0.5) / (df(t) + 0.5) + 1)
/// score = Σ idf(t)  for t in intent ∩ entry
///       + exact_name_boost (same as Jaccard)
/// ```
///
/// Rare terms like "faers" or "meddra" dominate the score; common terms like
/// "search" or "get" add little. Good for intents with distinguishing vocabulary.
#[derive(Debug, Clone, Copy, Default)]
pub struct IdfRanker;

impl Ranker for IdfRanker {
    fn score(
        &self,
        intent_tokens: &HashSet<String>,
        intent_lower: &str,
        entry: &IndexEntry,
        index: &ConfigIndex,
    ) -> f64 {
        #[allow(clippy::cast_precision_loss, clippy::cast_lossless)]
        let n_docs = index.doc_count as f64;
        if n_docs < 1.0 {
            return 0.0;
        }
        let mut sum_idf = 0.0_f64;
        let mut matched = 0_usize;
        for term in intent_tokens.intersection(&entry.tokens) {
            #[allow(clippy::cast_precision_loss, clippy::cast_lossless)]
            let df = *index.doc_freq.get(term).unwrap_or(&1) as f64;
            // Smoothed IDF (BM25-style): ln((N - df + 0.5) / (df + 0.5) + 1)
            // The +1 inside ln keeps IDF non-negative even for very common terms.
            let idf = ((n_docs - df + 0.5) / (df + 0.5) + 1.0).ln();
            sum_idf += idf;
            matched += 1;
        }
        if matched == 0 {
            return 0.0;
        }
        let tool_lower = entry.tool.replace('_', " ").to_ascii_lowercase();
        let exact_boost = if intent_lower.contains(&tool_lower) || intent_lower.contains(&entry.tool) {
            0.5
        } else {
            0.0
        };
        sum_idf + exact_boost
    }
}

/// Rank using a specific `Ranker`. `discover()` is a convenience wrapper that
/// uses `JaccardRanker` for backward compatibility.
#[must_use]
pub fn discover_with(
    index: &ConfigIndex,
    intent: &str,
    limit: usize,
    ranker: &dyn Ranker,
) -> Vec<ToolCandidate> {
    let intent_tokens = tokenize(&[intent]);
    if intent_tokens.is_empty() {
        return Vec::new();
    }
    let intent_lower = intent.to_ascii_lowercase();

    let mut scored: Vec<(f64, &IndexEntry)> = index
        .entries
        .iter()
        .map(|e| (ranker.score(&intent_tokens, &intent_lower, e, index), e))
        .filter(|(s, _)| *s > 0.0)
        .collect();

    scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    scored
        .into_iter()
        .take(limit)
        .map(|(score, e)| ToolCandidate {
            config: e.domain.clone(),
            tool: e.tool.clone(),
            config_stem: e.config_stem.clone(),
            title: e.title.clone(),
            description: e.description.clone(),
            score,
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mk_index() -> ConfigIndex {
        // Using `from_entries` (not a struct literal) so corpus stats —
        // doc_freq and doc_count — are populated. IdfRanker needs them.
        ConfigIndex::from_entries(vec![
            IndexEntry {
                config_stem: "openfda".into(),
                title: "openFDA FAERS".into(),
                domain: "api.fda.gov".into(),
                tool: "search_adverse_events".into(),
                description: "Search FAERS adverse event reports by drug, reaction, or outcome"
                    .into(),
                tokens: tokenize(&[
                    "openFDA FAERS",
                    "api.fda.gov",
                    "search_adverse_events",
                    "Search FAERS adverse event reports by drug, reaction, or outcome",
                ]),
            },
            IndexEntry {
                config_stem: "rxnav".into(),
                title: "RxNav".into(),
                domain: "rxnav.nlm.nih.gov".into(),
                tool: "get_rxcui".into(),
                description: "Map drug name to RxCUI code".into(),
                tokens: tokenize(&[
                    "RxNav",
                    "rxnav.nlm.nih.gov",
                    "get_rxcui",
                    "Map drug name to RxCUI code",
                ]),
            },
            IndexEntry {
                config_stem: "meddra".into(),
                title: "MedDRA Terminology".into(),
                domain: "meddra.org".into(),
                tool: "search_terms".into(),
                description: "Search MedDRA preferred terms and SOCs".into(),
                tokens: tokenize(&[
                    "MedDRA Terminology",
                    "meddra.org",
                    "search_terms",
                    "Search MedDRA preferred terms and SOCs",
                ]),
            },
        ])
    }

    #[test]
    fn discover_ranks_faers_first_for_adverse_events() {
        let idx = mk_index();
        let hits = discover(&idx, "find adverse events for metformin", 3);
        assert!(!hits.is_empty(), "expected at least one hit");
        assert_eq!(hits[0].tool, "search_adverse_events");
        // config is now the domain (routing key), stem is for human display
        assert_eq!(hits[0].config, "api.fda.gov");
        assert_eq!(hits[0].config_stem, "openfda");
    }

    #[test]
    fn discover_ranks_meddra_first_for_preferred_term() {
        let idx = mk_index();
        let hits = discover(&idx, "look up meddra preferred term", 3);
        assert!(!hits.is_empty());
        assert_eq!(hits[0].config, "meddra.org");
        assert_eq!(hits[0].config_stem, "meddra");
    }

    #[test]
    fn discover_empty_intent_returns_empty() {
        let idx = mk_index();
        assert!(discover(&idx, "", 5).is_empty());
        assert!(discover(&idx, "   ", 5).is_empty());
    }

    #[test]
    fn discover_unrelated_intent_returns_empty_not_catalog() {
        let idx = mk_index();
        // No overlap with any indexed tokens.
        let hits = discover(&idx, "quantum chromodynamics lattice", 5);
        assert!(hits.is_empty(), "filter-by-score > 0 must suppress noise");
    }

    #[test]
    fn discover_respects_limit() {
        let idx = mk_index();
        let hits = discover(&idx, "search drug adverse terms", 1);
        assert_eq!(hits.len(), 1);
    }

    #[test]
    fn exact_tool_name_in_intent_gets_boost() {
        let idx = mk_index();
        let hits = discover(&idx, "I need search_adverse_events", 3);
        assert!(!hits.is_empty());
        assert_eq!(hits[0].tool, "search_adverse_events");
        assert!(hits[0].score > 0.5, "exact-name boost should dominate");
    }

    #[test]
    fn tokenize_drops_short_tokens_and_punctuation() {
        let tok = tokenize(&["A an the search-adverse events!"]);
        assert!(tok.contains("search"));
        assert!(tok.contains("adverse"));
        assert!(tok.contains("events"));
        assert!(!tok.contains("an")); // < 3 chars
        assert!(!tok.contains("a")); // < 3 chars
    }

    #[test]
    fn index_len_matches_entries() {
        let idx = mk_index();
        assert_eq!(idx.len(), 3);
        assert!(!idx.is_empty());
    }

    // ========== IdfRanker behavioural tests ==========

    #[test]
    fn idf_index_precomputes_doc_freq_and_count() {
        let idx = mk_index();
        assert_eq!(idx.doc_count, 3);
        // "search" appears in openfda tokens AND meddra tokens (both have
        // "Search FAERS..." / "Search MedDRA..." in their source text), so df=2.
        assert_eq!(idx.doc_freq.get("search").copied(), Some(2));
        // "faers" is rare — only openfda corpus — so df=1.
        assert_eq!(idx.doc_freq.get("faers").copied(), Some(1));
        // "drug" appears in openfda (reports by drug...) and rxnav (Map drug name),
        // but NOT meddra (which talks about preferred terms). df=2.
        assert_eq!(idx.doc_freq.get("drug").copied(), Some(2));
    }

    #[test]
    fn idf_ranker_weights_rare_terms_higher_than_common_terms() {
        let idx = mk_index();
        // Intent uses both "search" (df=2, common) and "faers" (df=1, rare).
        // IdfRanker should rank openfda (contains "faers") strictly above
        // meddra (contains "search" but not "faers").
        let hits = discover_with(&idx, "search faers", 3, &IdfRanker);
        assert!(hits.len() >= 2);
        let openfda_score = hits
            .iter()
            .find(|h| h.config_stem == "openfda")
            .map(|h| h.score)
            .expect("openfda in results");
        let meddra_score = hits
            .iter()
            .find(|h| h.config_stem == "meddra")
            .map(|h| h.score)
            .unwrap_or(0.0);
        assert!(
            openfda_score > meddra_score,
            "IdfRanker should rank openfda (rare term 'faers') > meddra (common term 'search'); \
             got openfda={openfda_score}, meddra={meddra_score}"
        );
    }

    #[test]
    fn idf_and_jaccard_rankers_both_find_obvious_matches() {
        let idx = mk_index();
        // Both rankers must return openfda first for a clear FAERS intent.
        let jaccard_hits = discover_with(&idx, "search FAERS adverse events", 3, &JaccardRanker);
        let idf_hits = discover_with(&idx, "search FAERS adverse events", 3, &IdfRanker);
        assert!(!jaccard_hits.is_empty());
        assert!(!idf_hits.is_empty());
        assert_eq!(jaccard_hits[0].config_stem, "openfda");
        assert_eq!(idf_hits[0].config_stem, "openfda");
    }

    #[test]
    fn idf_ranker_returns_zero_for_zero_overlap() {
        let idx = mk_index();
        // No overlap → score 0 → filtered out.
        let hits = discover_with(&idx, "quantum chromodynamics", 5, &IdfRanker);
        assert!(hits.is_empty());
    }

    #[test]
    fn discover_is_backward_compatible_with_jaccard() {
        // The old discover() API must still work and return Jaccard-scored results.
        let idx = mk_index();
        let jaccard_direct = discover_with(&idx, "find adverse events", 3, &JaccardRanker);
        let via_discover = discover(&idx, "find adverse events", 3);
        assert_eq!(via_discover.len(), jaccard_direct.len());
        for (a, b) in via_discover.iter().zip(jaccard_direct.iter()) {
            assert_eq!(a.config, b.config);
            assert_eq!(a.tool, b.tool);
            assert!((a.score - b.score).abs() < 1e-9);
        }
    }

    #[test]
    fn load_gracefully_skips_missing_dir_components() {
        // Pointing at a dir that exists but has no .json files returns empty.
        let tmp = std::env::temp_dir().join(format!("station-meta-test-{}", std::process::id()));
        let _ = std::fs::create_dir_all(&tmp);
        let idx = ConfigIndex::load(&tmp).expect("empty dir should load");
        assert_eq!(idx.len(), 0);
        let _ = std::fs::remove_dir_all(&tmp);
    }
}
