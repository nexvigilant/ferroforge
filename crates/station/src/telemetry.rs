//! Station Telemetry — observability for the open house.
//!
//! Every tool call is measured: what was called, from which domain,
//! how long it took, whether it succeeded. Matthew queries this via
//! the `nexvigilant_station_health` meta-tool to see what agents
//! are doing inside the house.
//!
//! Data flows to:
//!   1. In-memory ring buffer (fast queries, bounded)
//!   2. JSONL file on disk (persistent audit trail)
//!   3. stderr tracing (existing log infrastructure)

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Instant;
use tracing::{info, warn};

/// Maximum entries in the in-memory ring buffer.
const MAX_RING_ENTRIES: usize = 10_000;

/// A single tool call record.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolCallRecord {
    /// ISO 8601 timestamp
    pub timestamp: String,
    /// Full MCP tool name (e.g., "api_fda_gov_search_adverse_events")
    pub tool_name: String,
    /// Domain extracted from tool prefix (e.g., "api.fda.gov")
    pub domain: String,
    /// Wall-clock duration in milliseconds
    pub duration_ms: u64,
    /// Tool response status: "ok", "error", "stub", "no_handler"
    pub status: String,
    /// Whether the MCP response flagged isError
    pub is_error: bool,
}

/// Aggregate statistics for a domain.
#[derive(Debug, Clone, Serialize)]
pub struct DomainStats {
    pub domain: String,
    pub call_count: u64,
    pub error_count: u64,
    pub avg_duration_ms: f64,
    pub top_tools: Vec<(String, u64)>,
}

/// Station-wide health summary.
#[derive(Debug, Clone, Serialize)]
pub struct StationHealth {
    pub station: String,
    pub uptime_seconds: u64,
    pub total_calls: u64,
    pub total_errors: u64,
    pub error_rate_pct: f64,
    pub avg_duration_ms: f64,
    pub calls_per_minute: f64,
    pub domains: Vec<DomainStats>,
    pub top_tools: Vec<(String, u64)>,
    pub recent_calls: Vec<ToolCallRecord>,
}

/// Core telemetry engine.
pub struct StationTelemetry {
    ring: Mutex<Vec<ToolCallRecord>>,
    log_path: Option<PathBuf>,
    start_time: Instant,
}

impl StationTelemetry {
    /// Create a new telemetry instance, optionally writing to a JSONL file.
    pub fn new(log_path: Option<PathBuf>) -> Self {
        if let Some(ref path) = log_path {
            info!(path = %path.display(), "Telemetry JSONL log enabled");
        }
        Self {
            ring: Mutex::new(Vec::with_capacity(MAX_RING_ENTRIES)),
            log_path,
            start_time: Instant::now(),
        }
    }

    /// Record a completed tool call.
    pub fn record(&self, record: ToolCallRecord) {
        // Append to JSONL file
        if let Some(ref path) = self.log_path {
            if let Ok(json) = serde_json::to_string(&record) {
                if let Ok(mut file) = OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(path)
                {
                    let _ = writeln!(file, "{json}");
                }
            }
        }

        // Push to ring buffer
        let mut ring = match self.ring.lock() {
            Ok(r) => r,
            Err(e) => {
                warn!(error = %e, "Telemetry ring lock poisoned");
                return;
            }
        };

        if ring.len() >= MAX_RING_ENTRIES {
            ring.remove(0);
        }
        ring.push(record);
    }

    /// Generate a health summary from the ring buffer.
    pub fn health(&self) -> StationHealth {
        let ring = match self.ring.lock() {
            Ok(r) => r,
            Err(_) => {
                return StationHealth {
                    station: "NexVigilant Station".into(),
                    uptime_seconds: self.start_time.elapsed().as_secs(),
                    total_calls: 0,
                    total_errors: 0,
                    error_rate_pct: 0.0,
                    avg_duration_ms: 0.0,
                    calls_per_minute: 0.0,
                    domains: vec![],
                    top_tools: vec![],
                    recent_calls: vec![],
                };
            }
        };

        let total_calls = ring.len() as u64;
        let total_errors = ring.iter().filter(|r| r.is_error).count() as u64;
        let uptime_secs = self.start_time.elapsed().as_secs().max(1);
        let total_duration_ms: u64 = ring.iter().map(|r| r.duration_ms).sum();

        // Per-domain aggregation
        let mut domain_map: HashMap<String, Vec<&ToolCallRecord>> = HashMap::new();
        let mut tool_counts: HashMap<String, u64> = HashMap::new();

        for record in ring.iter() {
            domain_map
                .entry(record.domain.clone())
                .or_default()
                .push(record);
            *tool_counts.entry(record.tool_name.clone()).or_default() += 1;
        }

        let mut domains: Vec<DomainStats> = domain_map
            .into_iter()
            .map(|(domain, records)| {
                let call_count = records.len() as u64;
                let error_count = records.iter().filter(|r| r.is_error).count() as u64;
                let avg_duration_ms = if call_count > 0 {
                    records.iter().map(|r| r.duration_ms).sum::<u64>() as f64 / call_count as f64
                } else {
                    0.0
                };

                // Top tools for this domain
                let mut domain_tools: HashMap<String, u64> = HashMap::new();
                for r in &records {
                    *domain_tools.entry(r.tool_name.clone()).or_default() += 1;
                }
                let mut top_tools: Vec<(String, u64)> = domain_tools.into_iter().collect();
                top_tools.sort_by(|a, b| b.1.cmp(&a.1));
                top_tools.truncate(5);

                DomainStats {
                    domain,
                    call_count,
                    error_count,
                    avg_duration_ms,
                    top_tools,
                }
            })
            .collect();

        domains.sort_by(|a, b| b.call_count.cmp(&a.call_count));

        // Global top tools
        let mut top_tools: Vec<(String, u64)> = tool_counts.into_iter().collect();
        top_tools.sort_by(|a, b| b.1.cmp(&a.1));
        top_tools.truncate(10);

        // Recent calls (last 20)
        let recent_calls: Vec<ToolCallRecord> = ring
            .iter()
            .rev()
            .take(20)
            .cloned()
            .collect();

        StationHealth {
            station: "NexVigilant Station".into(),
            uptime_seconds: uptime_secs,
            total_calls,
            total_errors,
            error_rate_pct: if total_calls > 0 {
                (total_errors as f64 / total_calls as f64) * 100.0
            } else {
                0.0
            },
            avg_duration_ms: if total_calls > 0 {
                total_duration_ms as f64 / total_calls as f64
            } else {
                0.0
            },
            calls_per_minute: total_calls as f64 / (uptime_secs as f64 / 60.0),
            domains,
            top_tools,
            recent_calls,
        }
    }

    /// Get uptime in seconds.
    pub fn uptime_secs(&self) -> u64 {
        self.start_time.elapsed().as_secs()
    }
}

/// Extract domain from a prefixed MCP tool name.
/// "api_fda_gov_search_adverse_events" → "api.fda.gov"
/// "nexvigilant_directory" → "nexvigilant"
pub fn extract_domain(tool_name: &str) -> String {
    // Known domain prefixes (ordered longest first)
    const PREFIXES: &[(&str, &str)] = &[
        ("eudravigilance_ema_europa_eu_", "eudravigilance.ema.europa.eu"),
        ("science_nexvigilant_com_", "science.nexvigilant.com"),
        ("pubmed_ncbi_nlm_nih_gov_", "pubmed.ncbi.nlm.nih.gov"),
        ("dailymed_nlm_nih_gov_", "dailymed.nlm.nih.gov"),
        ("rxnav_nlm_nih_gov_", "rxnav.nlm.nih.gov"),
        ("www_ema_europa_eu_", "www.ema.europa.eu"),
        ("clinicaltrials_gov_", "clinicaltrials.gov"),
        ("accessdata_fda_gov_", "accessdata.fda.gov"),
        ("go_drugbank_com_", "go.drugbank.com"),
        ("vigiaccess_org_", "vigiaccess.org"),
        ("api_fda_gov_", "api.fda.gov"),
        ("open-vigil_fr_", "open-vigil.fr"),
        ("who-umc_org_", "who-umc.org"),
        ("www_fda_gov_", "www.fda.gov"),
        ("meddra_org_", "meddra.org"),
        ("cioms_ch_", "cioms.ch"),
        ("ich_org_", "ich.org"),
    ];

    for (prefix, domain) in PREFIXES {
        if tool_name.starts_with(prefix) {
            return (*domain).to_string();
        }
    }

    if tool_name.starts_with("nexvigilant_") {
        return "nexvigilant.meta".to_string();
    }

    "unknown".to_string()
}

/// Create an ISO 8601 timestamp for the current moment.
pub fn now_iso8601() -> String {
    // Use basic time formatting without chrono dependency
    use std::time::SystemTime;
    let duration = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap_or_default();
    let secs = duration.as_secs();

    // Simple UTC formatting
    let days = secs / 86400;
    let time_secs = secs % 86400;
    let hours = time_secs / 3600;
    let minutes = (time_secs % 3600) / 60;
    let seconds = time_secs % 60;

    // Days since epoch to date (simplified, good enough for logging)
    let mut y = 1970i64;
    let mut remaining_days = days as i64;

    loop {
        let days_in_year = if y % 4 == 0 && (y % 100 != 0 || y % 400 == 0) {
            366
        } else {
            365
        };
        if remaining_days < days_in_year {
            break;
        }
        remaining_days -= days_in_year;
        y += 1;
    }

    let leap = y % 4 == 0 && (y % 100 != 0 || y % 400 == 0);
    let month_days: &[i64] = if leap {
        &[31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    } else {
        &[31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    };

    let mut m = 0usize;
    for (i, &md) in month_days.iter().enumerate() {
        if remaining_days < md {
            m = i;
            break;
        }
        remaining_days -= md;
    }

    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        y,
        m + 1,
        remaining_days + 1,
        hours,
        minutes,
        seconds,
    )
}

/// Start a timing measurement. Returns an Instant.
pub fn start_timer() -> Instant {
    Instant::now()
}

/// Complete a timing measurement. Returns milliseconds elapsed.
pub fn elapsed_ms(start: Instant) -> u64 {
    start.elapsed().as_millis() as u64
}
