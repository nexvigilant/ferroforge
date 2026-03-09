use std::collections::HashMap;
use std::net::IpAddr;
use std::sync::Arc;
use std::time::{Duration, Instant};

use axum::body::Body;
use axum::extract::{ConnectInfo, State};
use axum::http::{HeaderMap, Request, StatusCode};
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};
use tokio::sync::Mutex;
use tracing::warn;

/// Per-IP token bucket rate limiter.
///
/// Design: in-memory, per-instance (not globally coordinated).
/// Cloud Run instances each maintain independent buckets — acceptable for
/// abuse prevention. Global coordination would require Redis.
///
/// Primitives: ν(frequency governance) + ∂(boundary enforcement) + ς(mutable state)
/// Maximum requests per window per IP.
const MAX_REQUESTS: u32 = 120;

/// Window duration for the token bucket.
const WINDOW_SECS: u64 = 60;

/// How many IPs to track before pruning stale entries.
const MAX_TRACKED_IPS: usize = 10_000;

/// Entries older than this are pruned (seconds).
const PRUNE_AGE_SECS: u64 = 300;

struct Bucket {
    tokens: u32,
    last_refill: Instant,
}

impl Bucket {
    fn new() -> Self {
        Self {
            tokens: MAX_REQUESTS,
            last_refill: Instant::now(),
        }
    }

    /// Attempt to consume one token. Returns true if allowed.
    fn try_consume(&mut self) -> bool {
        self.refill();
        if self.tokens > 0 {
            self.tokens -= 1;
            true
        } else {
            false
        }
    }

    /// Refill tokens based on elapsed time since last refill.
    fn refill(&mut self) {
        let now = Instant::now();
        let elapsed = now.duration_since(self.last_refill);
        if elapsed >= Duration::from_secs(WINDOW_SECS) {
            self.tokens = MAX_REQUESTS;
            self.last_refill = now;
        }
    }

    /// How long until the bucket refills (for Retry-After header).
    fn retry_after(&self) -> u64 {
        let elapsed = Instant::now().duration_since(self.last_refill);
        let remaining = Duration::from_secs(WINDOW_SECS).saturating_sub(elapsed);
        remaining.as_secs().max(1)
    }
}

/// Shared rate limiter state, wrapped in Arc<Mutex> for axum middleware.
pub struct RateLimiter {
    buckets: Mutex<HashMap<IpAddr, Bucket>>,
}

impl RateLimiter {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            buckets: Mutex::new(HashMap::new()),
        })
    }
}

/// Extract client IP from request headers or connection info.
///
/// Priority: X-Forwarded-For (Cloud Run sets this) → ConnectInfo → fallback.
fn extract_ip(headers: &HeaderMap, connect_info: Option<&ConnectInfo<std::net::SocketAddr>>) -> IpAddr {
    // Cloud Run appends the real client IP as the rightmost entry in X-Forwarded-For.
    // Using the last entry prevents attackers from spoofing via controlled first entries.
    if let Some(ip) = headers
        .get("x-forwarded-for")
        .and_then(|xff| xff.to_str().ok())
        .and_then(|val| val.split(',').next_back())
        .and_then(|last| last.trim().parse::<IpAddr>().ok())
    {
        return ip;
    }

    // Fallback to direct connection
    if let Some(info) = connect_info {
        return info.0.ip();
    }

    // Last resort — treat as single client
    IpAddr::V4(std::net::Ipv4Addr::UNSPECIFIED)
}

/// Axum middleware layer for rate limiting.
///
/// Applies to all routes. Returns 429 Too Many Requests with Retry-After header
/// when a client exceeds MAX_REQUESTS per WINDOW_SECS.
pub async fn rate_limit_middleware(
    State(limiter): State<Arc<RateLimiter>>,
    headers: HeaderMap,
    request: Request<Body>,
    next: Next,
) -> Response {
    let connect_info = request.extensions().get::<ConnectInfo<std::net::SocketAddr>>().cloned();
    let ip = extract_ip(&headers, connect_info.as_ref());

    let mut buckets = limiter.buckets.lock().await;

    // Prune stale entries if we're tracking too many IPs
    if buckets.len() > MAX_TRACKED_IPS {
        let cutoff = Instant::now() - Duration::from_secs(PRUNE_AGE_SECS);
        buckets.retain(|_, b| b.last_refill > cutoff);
    }

    let bucket = buckets.entry(ip).or_insert_with(Bucket::new);

    if bucket.try_consume() {
        drop(buckets); // Release lock before calling next
        next.run(request).await
    } else {
        let retry_after = bucket.retry_after();
        drop(buckets);
        warn!(ip = %ip, retry_after, "Rate limit exceeded");
        (
            StatusCode::TOO_MANY_REQUESTS,
            [("retry-after", retry_after.to_string())],
            "Rate limit exceeded. Try again later.",
        )
            .into_response()
    }
}
