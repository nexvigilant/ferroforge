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
use std::collections::{HashMap, VecDeque};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Instant;
use tracing::{info, warn};

/// Maximum entries in the in-memory ring buffer.
const MAX_RING_ENTRIES: usize = 10_000;

/// Rate limit window in seconds (sliding window).
const RATE_LIMIT_WINDOW_SECS: u64 = 60;

/// Per-domain rate limits (calls per minute).
/// Conservative: stay well under upstream API limits to leave headroom.
/// Meta tools (nexvigilant.*) and science tools are unlimited (local computation).
const DOMAIN_RATE_LIMITS: &[(&str, u64)] = &[
    // Live API proxies — respect upstream limits
    ("api.fda.gov", 30),             // upstream: 40/min without key
    ("open-vigil.fr", 30),           // inherits openFDA (builds 2x2 from FAERS)
    ("pubmed.ncbi.nlm.nih.gov", 120),// upstream: 3/sec = 180/min, keep headroom
    ("clinicaltrials.gov", 60),      // undocumented, be respectful
    ("dailymed.nlm.nih.gov", 60),    // undocumented, be respectful
    ("rxnav.nlm.nih.gov", 300),      // upstream: 20/sec, very generous
    ("accessdata.fda.gov", 30),      // same org as openFDA
    // Stub domains — no real API calls, but limit anyway to prevent abuse
    ("www.ema.europa.eu", 30),
    ("eudravigilance.ema.europa.eu", 30),
    ("vigiaccess.org", 30),
    ("go.drugbank.com", 30),
    ("meddra.org", 30),
    ("ich.org", 30),
    ("cioms.ch", 30),
    ("who-umc.org", 30),
    ("www.fda.gov", 30),
];

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
    /// Error message when is_error is true (why it failed, not just that it failed)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error_message: Option<String>,
    /// Caller identity extracted from API key prefix or auth header (who called)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub client_id: Option<String>,
    /// Unique request ID for cross-call correlation (links related calls in a workflow)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub request_id: Option<String>,
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

/// SLO thresholds — aligned with CLAUDE.md Service Level Objectives.
///
/// | Metric          | Target   | Constant                  |
/// |-----------------|----------|---------------------------|
/// | Error rate warn | <5%      | ERROR_RATE_WARN_PCT       |
/// | Error rate crit | <10%     | ERROR_RATE_CRITICAL_PCT   |
/// | Latency P99     | <5000ms  | LATENCY_P99_TARGET_MS     |
/// | Proxy timeout   | 30s      | router.rs proxy_timeout   |
const ERROR_RATE_WARN_PCT: f64 = 5.0;
const ERROR_RATE_CRITICAL_PCT: f64 = 10.0;
const LATENCY_P99_TARGET_MS: u64 = 5_000;

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
    /// P99 latency in milliseconds (99th percentile of call durations).
    pub latency_p99_ms: u64,
    /// Whether P99 latency exceeds the 5000ms SLO target.
    pub latency_slo_ok: bool,
    /// SLO alert: "ok", "warn" (>5% errors), or "critical" (>10% errors or P99 > 5s).
    pub slo_status: String,
    /// Domains with error rates above the warning threshold.
    pub degraded_domains: Vec<String>,
    /// Health trend: "improving", "stable", or "degrading" based on recent error rate direction.
    pub trend: String,
    /// SHA-256 hash of the loaded config set (detects config drift between deploys).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub config_hash: Option<String>,
}

/// Result of a rate limit check.
#[derive(Debug, Clone, Serialize)]
pub struct RateLimitCheck {
    /// Whether the call is allowed.
    pub allowed: bool,
    /// Domain that was checked.
    pub domain: String,
    /// Calls in the current window.
    pub current_count: u64,
    /// Maximum calls allowed per window.
    pub limit: u64,
    /// Seconds until the oldest call in the window expires.
    pub retry_after_secs: u64,
}

/// Core telemetry engine.
pub struct StationTelemetry {
    ring: Mutex<VecDeque<ToolCallRecord>>,
    log_path: Option<PathBuf>,
    start_time: Instant,
    /// When true, rate limiting is disabled (stdio/local transport).
    local_mode: bool,
}

impl StationTelemetry {
    /// Create a new telemetry instance, optionally writing to a JSONL file.
    pub fn new(log_path: Option<PathBuf>) -> Self {
        if let Some(ref path) = log_path {
            info!(path = %path.display(), "Telemetry JSONL log enabled");
        }
        Self {
            ring: Mutex::new(VecDeque::with_capacity(MAX_RING_ENTRIES)),
            log_path,
            start_time: Instant::now(),
            local_mode: false,
        }
    }

    /// Create a telemetry instance with local mode (rate limiting disabled).
    /// Use for stdio transport where the single local user should never be throttled.
    pub fn new_local(log_path: Option<PathBuf>) -> Self {
        let mut t = Self::new(log_path);
        t.local_mode = true;
        t
    }

    /// Record a completed tool call.
    pub fn record(&self, record: ToolCallRecord) {
        // Structured log to stderr → Cloud Run captures to Cloud Logging
        info!(
            tool = %record.tool_name,
            domain = %record.domain,
            duration_ms = record.duration_ms,
            status = %record.status,
            is_error = record.is_error,
            "tool_call"
        );

        // Append to JSONL file (local dev audit trail, ephemeral on Cloud Run)
        if let Some(ref path) = self.log_path
            && let Ok(json) = serde_json::to_string(&record)
            && let Ok(mut file) = OpenOptions::new()
                .create(true)
                .append(true)
                .open(path)
        {
            let _ = writeln!(file, "{json}");
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
            ring.pop_front();
        }
        ring.push_back(record);
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
                    latency_p99_ms: 0,
                    latency_slo_ok: true,
                    slo_status: "ok".into(),
                    degraded_domains: vec![],
                    trend: "stable".into(),
                    config_hash: None,
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

        let error_rate_pct = if total_calls > 0 {
            (total_errors as f64 / total_calls as f64) * 100.0
        } else {
            0.0
        };

        // P99 latency — sort durations, pick 99th percentile
        let latency_p99_ms = if total_calls > 0 {
            let mut durations: Vec<u64> = ring.iter().map(|r| r.duration_ms).collect();
            durations.sort_unstable();
            let p99_idx = ((durations.len() as f64) * 0.99).ceil() as usize;
            durations[p99_idx.min(durations.len()) - 1]
        } else {
            0
        };
        let latency_slo_ok = latency_p99_ms <= LATENCY_P99_TARGET_MS;

        // SLO status — composite of error rate AND latency
        let slo_status = if error_rate_pct >= ERROR_RATE_CRITICAL_PCT || !latency_slo_ok {
            "critical".to_string()
        } else if error_rate_pct >= ERROR_RATE_WARN_PCT {
            "warn".to_string()
        } else {
            "ok".to_string()
        };

        // Find per-domain degradation
        let degraded_domains: Vec<String> = domains
            .iter()
            .filter(|d| d.call_count >= 5) // only flag domains with meaningful sample size
            .filter(|d| {
                let rate = (d.error_count as f64 / d.call_count as f64) * 100.0;
                rate >= ERROR_RATE_WARN_PCT
            })
            .map(|d| d.domain.clone())
            .collect();

        // Trend detection: compare error rate of first half vs second half of ring buffer.
        // "improving" = second half has lower error rate, "degrading" = higher, "stable" = same.
        let trend = if total_calls >= 10 {
            let mid = ring.len() / 2;
            let first_half_errors =
                ring.iter().take(mid).filter(|r| r.is_error).count() as f64;
            let second_half_errors =
                ring.iter().skip(mid).filter(|r| r.is_error).count() as f64;
            let first_rate = first_half_errors / mid as f64;
            let second_rate = second_half_errors / (ring.len() - mid) as f64;
            let delta = second_rate - first_rate;
            if delta < -0.02 {
                "improving"
            } else if delta > 0.02 {
                "degrading"
            } else {
                "stable"
            }
        } else {
            "stable" // Not enough data to detect trend
        };

        StationHealth {
            station: "NexVigilant Station".into(),
            uptime_seconds: uptime_secs,
            total_calls,
            total_errors,
            error_rate_pct,
            avg_duration_ms: if total_calls > 0 {
                total_duration_ms as f64 / total_calls as f64
            } else {
                0.0
            },
            calls_per_minute: total_calls as f64 / (uptime_secs as f64 / 60.0),
            domains,
            top_tools,
            recent_calls,
            latency_p99_ms,
            latency_slo_ok,
            slo_status,
            degraded_domains,
            trend: trend.into(),
            config_hash: None, // Set by caller via set_config_hash()
        }
    }

    /// Check if a domain has exceeded its rate limit.
    ///
    /// Uses the ring buffer timestamps to count calls in the sliding window.
    /// Meta tools (nexvigilant.meta) and science tools are never rate-limited.
    pub fn check_rate_limit(&self, domain: &str) -> RateLimitCheck {
        // Stdio/local transport — never rate-limit the single local user
        if self.local_mode {
            return RateLimitCheck {
                allowed: true,
                domain: domain.to_string(),
                current_count: 0,
                limit: 0,
                retry_after_secs: 0,
            };
        }

        // Never rate-limit local computation
        if domain == "nexvigilant.meta" || domain == "science.nexvigilant.com" || domain == "unknown" {
            return RateLimitCheck {
                allowed: true,
                domain: domain.to_string(),
                current_count: 0,
                limit: 0, // 0 = unlimited
                retry_after_secs: 0,
            };
        }

        // Find the limit for this domain
        let limit = DOMAIN_RATE_LIMITS
            .iter()
            .find(|(d, _)| *d == domain)
            .map(|(_, l)| *l)
            .unwrap_or(30); // default: 30/min for unknown domains

        let ring = match self.ring.lock() {
            Ok(r) => r,
            Err(_) => {
                // If lock poisoned, allow the call (fail open)
                return RateLimitCheck {
                    allowed: true,
                    domain: domain.to_string(),
                    current_count: 0,
                    limit,
                    retry_after_secs: 0,
                };
            }
        };

        // Count calls for this domain in the sliding window
        let now = epoch_secs();
        let window_start = now.saturating_sub(RATE_LIMIT_WINDOW_SECS);

        let mut count = 0u64;
        let mut oldest_in_window = now;

        for record in ring.iter().rev() {
            if record.domain != domain {
                continue;
            }
            let record_epoch = parse_iso8601_epoch(&record.timestamp).unwrap_or(0);
            if record_epoch < window_start {
                break; // Ring is chronological, so we can stop
            }
            count += 1;
            if record_epoch < oldest_in_window {
                oldest_in_window = record_epoch;
            }
        }

        let allowed = count < limit;
        let retry_after_secs = if allowed {
            0
        } else {
            // Time until the oldest call in the window expires
            (oldest_in_window + RATE_LIMIT_WINDOW_SECS).saturating_sub(now)
        };

        RateLimitCheck {
            allowed,
            domain: domain.to_string(),
            current_count: count,
            limit,
            retry_after_secs,
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

    // Dynamic extraction: convert underscore-separated prefix to dotted domain.
    // "benefit-risk_nexvigilant_com_compute_qbr" → "benefit-risk.nexvigilant.com"
    // "en_wikipedia_org_get_article_summary" → "en.wikipedia.org"
    // Heuristic: scan for known TLD segments (_com_, _org_, _gov_, _fr_, _eu_, _ch_)
    // and take everything up to and including the TLD.
    let tlds = ["_com_", "_org_", "_gov_", "_fr_", "_eu_", "_ch_"];
    for tld in &tlds {
        if let Some(pos) = tool_name.find(tld) {
            let domain_part = &tool_name[..pos + tld.len() - 1]; // exclude trailing _
            return domain_part.replace('_', ".").to_string();
        }
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

/// Current epoch seconds (UTC).
fn epoch_secs() -> u64 {
    use std::time::SystemTime;
    SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

/// Parse an ISO 8601 timestamp back to epoch seconds.
/// Handles our format: "YYYY-MM-DDThh:mm:ssZ"
fn parse_iso8601_epoch(ts: &str) -> Option<u64> {
    // Quick parse: "2026-03-06T20:19:56Z"
    let ts = ts.trim_end_matches('Z');
    let (date, time) = ts.split_once('T')?;
    let parts: Vec<&str> = date.split('-').collect();
    if parts.len() != 3 {
        return None;
    }
    let y: u64 = parts[0].parse().ok()?;
    let m: u64 = parts[1].parse().ok()?;
    let d: u64 = parts[2].parse().ok()?;

    let time_parts: Vec<&str> = time.split(':').collect();
    if time_parts.len() != 3 {
        return None;
    }
    let h: u64 = time_parts[0].parse().ok()?;
    let min: u64 = time_parts[1].parse().ok()?;
    let sec: u64 = time_parts[2].parse().ok()?;

    // Approximate days from epoch (good enough for 60s window comparison)
    let mut days = 0u64;
    for yr in 1970..y {
        days += if yr.is_multiple_of(4) && (!yr.is_multiple_of(100) || yr.is_multiple_of(400)) {
            366
        } else {
            365
        };
    }
    let leap = y.is_multiple_of(4) && (!y.is_multiple_of(100) || y.is_multiple_of(400));
    let month_days: &[u64] = if leap {
        &[31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    } else {
        &[31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    };
    for i in 0..(m.saturating_sub(1) as usize) {
        days += month_days.get(i).copied().unwrap_or(30);
    }
    days += d.saturating_sub(1);

    Some(days * 86400 + h * 3600 + min * 60 + sec)
}

/// Start a timing measurement. Returns an Instant.
pub fn start_timer() -> Instant {
    Instant::now()
}

/// Complete a timing measurement. Returns milliseconds elapsed.
pub fn elapsed_ms(start: Instant) -> u64 {
    start.elapsed().as_millis() as u64
}
