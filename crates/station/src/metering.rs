//! Token metering for NexVigilant Station toll billing.
//!
//! Counts tokens flowing through Station per tool call, extracts caller
//! identity from API key prefix, and records usage for billing.
//!
//! Token estimation: byte_length / 4 (conservative approximation).
//! This is tool-call traffic (JSON), not LLM inference, so exact
//! tokenization is unnecessary. Validated against Vertex AI reports
//! before billing goes live.

use crate::usage_store::UsageStore;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use tracing::info;

/// Metering record for a single tool call.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeteringRecord {
    /// ISO 8601 timestamp
    pub timestamp: String,
    /// Caller identity from API key prefix (e.g., "nv_abcd1234")
    /// None for anonymous (free tier) callers.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub client_id: Option<String>,
    /// MCP tool name
    pub tool_name: String,
    /// Domain extracted from tool prefix
    pub domain: String,
    /// Estimated input tokens (request JSON bytes / 4)
    pub input_tokens: u64,
    /// Estimated output tokens (response content bytes / 4)
    pub output_tokens: u64,
    /// Cost in microcents (1/10000 of a cent), if pricing is available
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cost_microcents: Option<u64>,
    /// Whether this call was on the free tier (no billing)
    pub free_tier: bool,
}

/// Accumulated usage for a client over a billing period.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct UsageSummary {
    pub client_id: String,
    pub period: String,
    pub total_input_tokens: u64,
    pub total_output_tokens: u64,
    pub total_tool_calls: u64,
    pub total_cost_microcents: u64,
    pub tool_breakdown: HashMap<String, u64>,
}

/// Token metering engine.
pub struct StationMeter {
    /// Accumulated records awaiting flush
    buffer: Mutex<Vec<MeteringRecord>>,
    /// JSONL file for persistent metering trail
    log_path: Option<PathBuf>,
    /// In-memory usage summaries by client_id
    summaries: Mutex<HashMap<String, UsageSummary>>,
    /// Firestore-backed usage persistence (None = local dev mode)
    usage_store: Option<Arc<UsageStore>>,
}

impl StationMeter {
    /// Create a new metering engine.
    ///
    /// Pass `usage_store` for Firestore persistence (production).
    /// Pass `None` for local dev (in-memory + JSONL only).
    pub fn new(log_path: Option<PathBuf>, usage_store: Option<Arc<UsageStore>>) -> Self {
        if let Some(ref path) = log_path {
            info!("Metering log: {}", path.display());
        }
        Self {
            buffer: Mutex::new(Vec::with_capacity(100)),
            log_path,
            summaries: Mutex::new(HashMap::new()),
            usage_store,
        }
    }

    /// Record a metered tool call.
    pub fn record(&self, record: MeteringRecord) {
        // Update in-memory summary
        if let Some(ref client_id) = record.client_id
            && let Ok(mut summaries) = self.summaries.lock()
        {
            let summary = summaries
                .entry(client_id.clone())
                .or_insert_with(|| UsageSummary {
                    client_id: client_id.clone(),
                    period: current_period(),
                    ..Default::default()
                });
            summary.total_input_tokens += record.input_tokens;
            summary.total_output_tokens += record.output_tokens;
            summary.total_tool_calls += 1;
            summary.total_cost_microcents += record.cost_microcents.unwrap_or(0);
            *summary
                .tool_breakdown
                .entry(record.tool_name.clone())
                .or_insert(0) += 1;
        }

        // Write to JSONL log
        if let Some(ref path) = self.log_path
            && let Ok(json) = serde_json::to_string(&record)
            && let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path)
        {
            let _ = writeln!(file, "{json}");
        }

        // Buffer for batch flush to external store
        if let Ok(mut buffer) = self.buffer.lock() {
            buffer.push(record);
            if buffer.len() >= 100 {
                let batch = std::mem::take(&mut *buffer);
                drop(buffer);
                self.flush_batch(batch);
            }
        }
    }

    /// Get usage summary for a specific client.
    pub fn get_usage(&self, client_id: &str) -> Option<UsageSummary> {
        self.summaries
            .lock()
            .ok()
            .and_then(|s| s.get(client_id).cloned())
    }

    /// Get all usage summaries (for the billing dashboard).
    pub fn get_all_usage(&self) -> Vec<UsageSummary> {
        self.summaries
            .lock()
            .ok()
            .map(|s| s.values().cloned().collect())
            .unwrap_or_default()
    }

    /// Flush buffered records to external store.
    fn flush_batch(&self, batch: Vec<MeteringRecord>) {
        let metered_count = batch.iter().filter(|r| !r.free_tier).count();
        let free_count = batch.len() - metered_count;
        let total_tokens: u64 = batch
            .iter()
            .map(|r| r.input_tokens + r.output_tokens)
            .sum();

        info!(
            "Meter flush: {} records ({} metered, {} free), {} tokens",
            batch.len(),
            metered_count,
            free_count,
            total_tokens
        );

        // Forward metered records to UsageStore for Firestore persistence
        if let Some(ref store) = self.usage_store {
            for record in batch {
                store.buffer_record(record);
            }
            store.flush();
        }
    }
}

/// Estimate token count from byte length.
/// Conservative: JSON bytes / 4. Overestimates slightly for ASCII-heavy
/// tool call payloads, which is preferable to undercharging.
pub fn estimate_tokens(bytes: usize) -> u64 {
    (bytes / 4).max(1) as u64
}

/// Extract client_id from an API key.
/// Key format: `nv_{uid_prefix}_{random_hex}`
/// Returns the prefix portion (e.g., "nv_abcd1234") for identification
/// without exposing the full key.
pub fn extract_client_id(auth_header: Option<&str>) -> Option<String> {
    let header = auth_header?;
    let key = header.strip_prefix("Bearer ")?;
    if !key.starts_with("nv_") {
        return None;
    }
    // Return first 12 chars as the client identifier
    Some(key.chars().take(12).collect())
}

/// Current billing period as YYYY-MM string.
fn current_period() -> String {
    // Use the same ISO 8601 timestamp as telemetry, then truncate to YYYY-MM
    let ts = crate::telemetry::now_iso8601();
    ts.get(..7).unwrap_or("1970-01").to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_estimate_tokens() {
        assert_eq!(estimate_tokens(0), 1); // min 1
        assert_eq!(estimate_tokens(4), 1);
        assert_eq!(estimate_tokens(100), 25);
        assert_eq!(estimate_tokens(1000), 250);
    }

    #[test]
    fn test_extract_client_id() {
        assert_eq!(
            extract_client_id(Some("Bearer nv_abcd1234_deadbeef")),
            Some("nv_abcd1234_".to_string())
        );
        assert_eq!(extract_client_id(Some("Bearer sk_test_123")), None);
        assert_eq!(extract_client_id(None), None);
        assert_eq!(extract_client_id(Some("not a bearer")), None);
    }

    #[test]
    fn test_metering_record() {
        let meter = StationMeter::new(None, None);

        meter.record(MeteringRecord {
            timestamp: "2026-03-26T12:00:00Z".to_string(),
            client_id: Some("nv_test1234_".to_string()),
            tool_name: "api_fda_gov_search_adverse_events".to_string(),
            domain: "api.fda.gov".to_string(),
            input_tokens: 50,
            output_tokens: 200,
            cost_microcents: Some(375), // 0.00375 cents
            free_tier: false,
        });

        let usage = meter.get_usage("nv_test1234_");
        assert!(usage.is_some());
        let u = usage.expect("Expected usage summary");
        assert_eq!(u.total_input_tokens, 50);
        assert_eq!(u.total_output_tokens, 200);
        assert_eq!(u.total_tool_calls, 1);
        assert_eq!(u.total_cost_microcents, 375);
    }

    #[test]
    fn test_free_tier_not_tracked_in_summary() {
        let meter = StationMeter::new(None, None);

        meter.record(MeteringRecord {
            timestamp: "2026-03-26T12:00:00Z".to_string(),
            client_id: None, // anonymous
            tool_name: "nexvigilant_chart_course".to_string(),
            domain: "nexvigilant".to_string(),
            input_tokens: 30,
            output_tokens: 100,
            cost_microcents: None,
            free_tier: true,
        });

        // No client_id = no summary entry
        assert!(meter.get_all_usage().is_empty());
    }
}
