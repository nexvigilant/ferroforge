//! Firestore-backed usage persistence for toll billing.
//!
//! Writes metering records to Firestore via REST API.
//! Cloud Run instances use the metadata server for auth (no service account key needed).
//! Local dev uses `GOOGLE_APPLICATION_CREDENTIALS` or skips Firestore entirely.
//!
//! Collection schema:
//!   station_usage/{client_id}/daily/{YYYY-MM-DD}
//!     input_tokens: i64 (increment)
//!     output_tokens: i64 (increment)
//!     tool_calls: i64 (increment)
//!     cost_microcents: i64 (increment)
//!     last_updated: string (ISO 8601)

use crate::metering::MeteringRecord;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, SystemTime};
use tracing::{info, warn};

/// Firestore project and auth configuration.
pub struct UsageStore {
    /// Google Cloud project ID (e.g., "nexvigilant-digital-clubhouse")
    project_id: String,
    /// Cached access token + expiry
    token_cache: Mutex<Option<CachedToken>>,
    /// Buffered records awaiting flush
    buffer: Mutex<Vec<MeteringRecord>>,
    /// Whether Firestore persistence is enabled
    enabled: bool,
}

struct CachedToken {
    access_token: String,
    expires_at: SystemTime,
}

/// Firestore field value for increment operations.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct FirestoreCommit {
    writes: Vec<FirestoreWrite>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct FirestoreWrite {
    transform: FirestoreTransform,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct FirestoreTransform {
    document: String,
    field_transforms: Vec<FieldTransform>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct FieldTransform {
    field_path: String,
    increment: FirestoreValue,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct FirestoreValue {
    integer_value: String,
}

/// Usage summary returned to billing API consumers.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredUsage {
    pub client_id: String,
    pub date: String,
    pub input_tokens: i64,
    pub output_tokens: i64,
    pub tool_calls: i64,
    pub cost_microcents: i64,
}

impl UsageStore {
    /// Create a new Firestore-backed usage store.
    ///
    /// Pass `None` for `project_id` to disable Firestore persistence
    /// (local dev mode — metering still works in-memory via StationMeter).
    pub fn new(project_id: Option<String>) -> Self {
        let enabled = project_id.is_some();
        if enabled {
            info!(
                "UsageStore: Firestore persistence enabled (project: {})",
                project_id.as_deref().unwrap_or("?")
            );
        } else {
            info!("UsageStore: Firestore disabled (local dev mode)");
        }

        Self {
            project_id: project_id.unwrap_or_default(),
            token_cache: Mutex::new(None),
            buffer: Mutex::new(Vec::with_capacity(100)),
            enabled,
        }
    }

    /// Buffer a metering record for batch flush.
    /// Only buffers records with a client_id (free tier is not persisted to Firestore).
    pub fn buffer_record(&self, record: MeteringRecord) {
        if !self.enabled || record.free_tier || record.client_id.is_none() {
            return;
        }

        let should_flush = {
            let mut buf = match self.buffer.lock() {
                Ok(b) => b,
                Err(_) => return,
            };
            buf.push(record);
            buf.len() >= 100
        };

        if should_flush {
            self.flush();
        }
    }

    /// Flush all buffered records to Firestore.
    pub fn flush(&self) {
        if !self.enabled {
            return;
        }

        let batch = {
            let mut buf = match self.buffer.lock() {
                Ok(b) => b,
                Err(_) => return,
            };
            if buf.is_empty() {
                return;
            }
            std::mem::take(&mut *buf)
        };

        // Aggregate by client_id + date
        let mut aggregates: HashMap<(String, String), AggregatedUsage> = HashMap::new();

        for record in &batch {
            let client_id = match &record.client_id {
                Some(id) => id.clone(),
                None => continue,
            };
            let date = record.timestamp.get(..10).unwrap_or("unknown").to_string();
            let entry = aggregates
                .entry((client_id, date))
                .or_insert_with(AggregatedUsage::default);
            entry.input_tokens += record.input_tokens as i64;
            entry.output_tokens += record.output_tokens as i64;
            entry.tool_calls += 1;
            entry.cost_microcents += record.cost_microcents.unwrap_or(0) as i64;
        }

        // Write each aggregate as a Firestore document transform (increment)
        let token = match self.get_access_token() {
            Some(t) => t,
            None => {
                warn!(
                    "UsageStore: no access token, dropping {} records",
                    batch.len()
                );
                return;
            }
        };

        for ((client_id, date), usage) in &aggregates {
            let doc_path = format!(
                "projects/{}/databases/(default)/documents/station_usage/{}/daily/{}",
                self.project_id, client_id, date
            );

            let commit = FirestoreCommit {
                writes: vec![FirestoreWrite {
                    transform: FirestoreTransform {
                        document: doc_path,
                        field_transforms: vec![
                            FieldTransform {
                                field_path: "input_tokens".into(),
                                increment: FirestoreValue {
                                    integer_value: usage.input_tokens.to_string(),
                                },
                            },
                            FieldTransform {
                                field_path: "output_tokens".into(),
                                increment: FirestoreValue {
                                    integer_value: usage.output_tokens.to_string(),
                                },
                            },
                            FieldTransform {
                                field_path: "tool_calls".into(),
                                increment: FirestoreValue {
                                    integer_value: usage.tool_calls.to_string(),
                                },
                            },
                            FieldTransform {
                                field_path: "cost_microcents".into(),
                                increment: FirestoreValue {
                                    integer_value: usage.cost_microcents.to_string(),
                                },
                            },
                        ],
                    },
                }],
            };

            let url = format!(
                "https://firestore.googleapis.com/v1/projects/{}/databases/(default)/documents:commit",
                self.project_id
            );

            match ureq::post(&url)
                .set("Authorization", &format!("Bearer {}", token))
                .set("Content-Type", "application/json")
                .send_json(serde_json::to_value(&commit).unwrap_or_default())
            {
                Ok(_) => {
                    info!(
                        "UsageStore: flushed {} tokens for {} on {}",
                        usage.input_tokens + usage.output_tokens,
                        client_id,
                        date
                    );
                }
                Err(e) => {
                    warn!("UsageStore: Firestore write failed for {}/{}: {}", client_id, date, e);
                }
            }
        }

        info!(
            "UsageStore: flushed {} records across {} client-days",
            batch.len(),
            aggregates.len()
        );
    }

    /// Get an access token from the Cloud Run metadata server or local credentials.
    fn get_access_token(&self) -> Option<String> {
        // Check cache first
        if let Ok(cache) = self.token_cache.lock() {
            if let Some(ref cached) = *cache {
                if SystemTime::now() < cached.expires_at {
                    return Some(cached.access_token.clone());
                }
            }
        }

        // Try Cloud Run metadata server (automatic identity on GCP)
        let token_info = ureq::get(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        )
        .set("Metadata-Flavor", "Google")
        .call()
        .ok()?
        .into_json::<MetadataTokenResponse>()
        .ok()?;

        let expires_at = SystemTime::now() + Duration::from_secs(token_info.expires_in.saturating_sub(60));

        if let Ok(mut cache) = self.token_cache.lock() {
            *cache = Some(CachedToken {
                access_token: token_info.access_token.clone(),
                expires_at,
            });
        }

        Some(token_info.access_token)
    }
}

/// Cloud Run metadata server token response.
#[derive(Deserialize)]
struct MetadataTokenResponse {
    access_token: String,
    expires_in: u64,
}

/// Aggregated usage for a single client-day.
#[derive(Default)]
struct AggregatedUsage {
    input_tokens: i64,
    output_tokens: i64,
    tool_calls: i64,
    cost_microcents: i64,
}

impl Drop for UsageStore {
    /// Flush remaining buffered records on shutdown.
    fn drop(&mut self) {
        self.flush();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::metering::MeteringRecord;

    #[test]
    fn test_usage_store_disabled_mode() {
        let store = UsageStore::new(None);
        assert!(!store.enabled);

        // Should not panic or error
        store.buffer_record(MeteringRecord {
            timestamp: "2026-03-26T12:00:00Z".to_string(),
            client_id: Some("nv_test1234_".to_string()),
            tool_name: "test_tool".to_string(),
            domain: "test".to_string(),
            input_tokens: 50,
            output_tokens: 200,
            cost_microcents: Some(100),
            free_tier: false,
        });

        // Flush should be a no-op
        store.flush();
    }

    #[test]
    fn test_free_tier_not_buffered() {
        let store = UsageStore::new(Some("test-project".into()));

        store.buffer_record(MeteringRecord {
            timestamp: "2026-03-26T12:00:00Z".to_string(),
            client_id: None, // anonymous
            tool_name: "nexvigilant_chart_course".to_string(),
            domain: "nexvigilant".to_string(),
            input_tokens: 30,
            output_tokens: 100,
            cost_microcents: None,
            free_tier: true,
        });

        let buf = store.buffer.lock().unwrap();
        assert!(buf.is_empty(), "free tier records should not be buffered");
    }

    #[test]
    fn test_metered_record_buffered() {
        let store = UsageStore::new(Some("test-project".into()));

        store.buffer_record(MeteringRecord {
            timestamp: "2026-03-26T12:00:00Z".to_string(),
            client_id: Some("nv_abcd1234_".to_string()),
            tool_name: "api_fda_gov_search".to_string(),
            domain: "api.fda.gov".to_string(),
            input_tokens: 50,
            output_tokens: 200,
            cost_microcents: Some(375),
            free_tier: false,
        });

        let buf = store.buffer.lock().unwrap();
        assert_eq!(buf.len(), 1, "metered record should be buffered");
    }
}
