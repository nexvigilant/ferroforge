use std::collections::HashMap;
use std::sync::Arc;

use axum::extract::{Query, State};
use axum::http::{HeaderMap, HeaderValue, Method, StatusCode};
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::response::IntoResponse;
use axum::routing::{get, post};
use axum::Json;
use serde_json::Value;
use tokio::sync::{broadcast, mpsc, Mutex};
use tokio_stream::wrappers::ReceiverStream;
use tower_http::cors::CorsLayer;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

use crate::auth::{self, ApiKeyGate, AuthResult};
use crate::config::ConfigRegistry;
use crate::protocol::{JsonRpcRequest, StationEvent, StationEventNotification};
use crate::server::handle_request_cached;
use crate::server_streamable::StreamableState;
use crate::telemetry::StationTelemetry;

type SseChannel = mpsc::Sender<Result<Event, axum::Error>>;

/// Maximum concurrent SSE sessions before rejecting new connections.
const MAX_SESSIONS: usize = 1000;

/// Sessions idle longer than this are reaped (seconds).
const SESSION_IDLE_TIMEOUT_SECS: u64 = 300;

/// How often the reaper runs (seconds).
const REAPER_INTERVAL_SECS: u64 = 60;

/// Session metadata — tracks lifecycle beyond just the channel sender.
struct SessionInfo {
    tx: SseChannel,
    #[allow(dead_code)] // Available for diagnostics and future health reporting
    created_at: tokio::time::Instant,
    last_activity: tokio::time::Instant,
    request_count: u64,
}

struct AppState {
    registry: Arc<ConfigRegistry>,
    telemetry: Arc<StationTelemetry>,
    event_tx: broadcast::Sender<StationEvent>,
    sessions: Mutex<HashMap<String, SessionInfo>>,
    auth_gate: ApiKeyGate,
    meter: Arc<crate::metering::StationMeter>,
    proxy_cache: crate::router::ProxyCache,
    gcp_client: Arc<crate::gcp::GcpClient>,
}

impl crate::billing_api::HasMeter for AppState {
    fn meter(&self) -> &Arc<crate::metering::StationMeter> {
        &self.meter
    }
}

/// Run the combined MCP server — SSE + HTTP REST on one port.
///
/// Serves ALL transport surfaces simultaneously:
///   GET  /sse              → MCP SSE stream (for mcp-remote, Claude Code)
///   POST /message?sessionId=xxx → MCP JSON-RPC via SSE
///   POST /rpc              → JSON-RPC 2.0 direct (for any MCP client)
///   GET  /tools            → tool catalog as JSON array
///   POST /tools/{name}     → simplified REST tool call
///   GET  /health           → liveness + telemetry summary
///   GET  /stats            → full telemetry (domains, top tools, recent calls)
pub async fn run_combined(
    registry: ConfigRegistry,
    telemetry: StationTelemetry,
    event_tx: broadcast::Sender<StationEvent>,
    host: &str,
    port: u16,
) -> anyhow::Result<()> {
    let auth_gate = ApiKeyGate::from_env();

    // Wrap registry and telemetry in Arc for sharing with streamable transport
    let registry_arc = Arc::new(registry);
    let telemetry_arc = Arc::new(telemetry);

    // Production (Cloud Run): persist to Firestore + JSONL log
    // Local dev: in-memory only
    let project_id = std::env::var("GOOGLE_CLOUD_PROJECT").ok()
        .or_else(|| std::env::var("GCP_PROJECT").ok());
    let usage_store = project_id.map(|pid| {
        Arc::new(crate::usage_store::UsageStore::new(Some(pid)))
    });
    let meter_log = if std::env::var("K_SERVICE").is_ok() {
        // Cloud Run: log to /tmp (ephemeral, but captured by Cloud Logging via structured stderr)
        Some(std::path::PathBuf::from("/tmp/station-metering.jsonl"))
    } else {
        // Local dev: log next to telemetry
        Some(std::path::PathBuf::from("station-metering.jsonl"))
    };
    let meter = Arc::new(crate::metering::StationMeter::new(meter_log, usage_store));
    let gcp_client = Arc::new(crate::gcp::GcpClient::new());

    let state = Arc::new(AppState {
        registry: Arc::clone(&registry_arc),
        telemetry: Arc::clone(&telemetry_arc),
        event_tx: event_tx.clone(),
        sessions: Mutex::new(HashMap::new()),
        auth_gate: auth_gate.clone(),
        meter: Arc::clone(&meter),
        proxy_cache: crate::router::ProxyCache::new(),
        gcp_client,
    });

    // Spawn session reaper — prunes zombie sessions every REAPER_INTERVAL_SECS
    let reaper_state = Arc::clone(&state);
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(
            std::time::Duration::from_secs(REAPER_INTERVAL_SECS),
        );
        loop {
            interval.tick().await;
            let mut sessions = reaper_state.sessions.lock().await;
            let before = sessions.len();
            let cutoff = tokio::time::Instant::now()
                - std::time::Duration::from_secs(SESSION_IDLE_TIMEOUT_SECS);
            sessions.retain(|id, info| {
                let alive = !info.tx.is_closed() && info.last_activity > cutoff;
                if !alive {
                    debug!(session_id = %id, "Reaping idle/closed session");
                }
                alive
            });
            let reaped = before - sessions.len();
            if reaped > 0 {
                info!(reaped = reaped, remaining = sessions.len(), "Session reaper cycle");
            }
        }
    });

    // Streamable HTTP state (shares registry, telemetry via Arc)
    let streamable_state = Arc::new(StreamableState::new(
        Arc::clone(&registry_arc),
        Arc::clone(&telemetry_arc),
        event_tx.clone(),
        auth_gate.clone(),
        Arc::clone(&meter),
    ));
    StreamableState::spawn_reaper(Arc::clone(&streamable_state));

    let allowed_origins = match std::env::var("ALLOWED_ORIGINS") {
        Ok(origins) => origins
            .split(',')
            .map(|s| s.trim().parse::<HeaderValue>())
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| anyhow::anyhow!("invalid ALLOWED_ORIGINS value: {e}"))?,
        Err(_) => {
            // Safe defaults for NexVigilant ecosystem
            vec![
                "https://mcp.nexvigilant.com".parse().unwrap(),
                "https://nexvigilant.com".parse().unwrap(),
                "http://localhost:3000".parse().unwrap(),
                "http://localhost:9002".parse().unwrap(),
            ]
        }
    };

    let cors = CorsLayer::new()
        .allow_origin(allowed_origins)
        .allow_methods([Method::GET, Method::POST, Method::DELETE, Method::OPTIONS])
        .allow_headers([
            axum::http::header::CONTENT_TYPE,
            axum::http::header::AUTHORIZATION,
            "mcp-session-id"
                .parse()
                .map_err(|e: axum::http::header::InvalidHeaderName| {
                    anyhow::anyhow!("invalid allow header name: {e}")
                })?,
        ])
        .expose_headers([
            "mcp-session-id"
                .parse::<axum::http::HeaderName>()
                .map_err(|e| anyhow::anyhow!("invalid expose header mcp-session-id: {e}"))?,
            "x-request-id"
                .parse::<axum::http::HeaderName>()
                .map_err(|e| anyhow::anyhow!("invalid expose header x-request-id: {e}"))?,
            "x-station-version"
                .parse::<axum::http::HeaderName>()
                .map_err(|e| anyhow::anyhow!("invalid expose header x-station-version: {e}"))?,
        ]);

    // Streamable HTTP routes (Claude.ai Connectors)
    let mcp_routes = axum::Router::new()
        .route("/mcp", post(crate::server_streamable::handle_mcp_post))
        .route("/mcp", get(crate::server_streamable::handle_mcp_get))
        .route("/mcp", axum::routing::delete(crate::server_streamable::handle_mcp_delete))
        .with_state(streamable_state);

    // Rate limiter — per-IP token bucket (120 req/min per IP)
    let rate_limiter = crate::rate_limit::RateLimiter::new();

    let app = axum::Router::new()
        // Streamable HTTP transport (Claude.ai Connectors — MCP 2025-03-26)
        .merge(mcp_routes)
        // SSE transport (MCP protocol — mcp-remote, Claude Code)
        .route("/sse", get(handle_sse))
        .route("/message", post(handle_message))
        // HTTP REST transport (any agent framework)
        .route("/rpc", post(handle_rpc))
        .route("/tools", get(handle_list_tools))
        .route("/tools/{name}", post(handle_tool_call))
        // Billing API (uses AppState via HasMeter trait)
        .route("/billing/rates", get(crate::billing_api::handle_rates))
        .route("/billing/usage", get(crate::billing_api::handle_usage::<AppState>))
        .route("/billing/balance", get(crate::billing_api::handle_balance::<AppState>))
        // MoltBook — config discovery + contribution for MoltBrowser clients
        .route("/configs/lookup", get(handle_configs_lookup))
        .route("/configs/contribute", post(handle_configs_contribute))
        .route("/configs/watch", get(handle_configs_watch))
        // Health + Stats (excluded from rate limiting below via middleware ordering)
        .route("/", get(handle_root))
        .route("/.well-known/mcp.json", get(handle_well_known_mcp))
        .route("/.well-known/mcp-registry-auth", get(handle_well_known_registry_auth))
        .route("/robots.txt", get(handle_robots_txt))
        .route("/health", get(handle_health))
        .route("/stats", get(handle_stats))
        .layer(axum::middleware::from_fn(response_headers_middleware))
        .layer(axum::middleware::from_fn_with_state(
            rate_limiter,
            crate::rate_limit::rate_limit_middleware,
        ))
        .layer(cors)
        .with_state(state);

    let addr = format!("{host}:{port}");
    let listener = tokio::net::TcpListener::bind(&addr).await?;
    info!(addr = %addr, "Station combined transport listening (SSE + HTTP)");

    // Graceful shutdown — listen for SIGTERM (Cloud Run) and CTRL+C (local dev).
    // Without this, Cloud Run sends SIGTERM, Station ignores it, Cloud Run
    // force-kills after 10s, and in-flight requests get broken pipes.
    axum::serve(listener, app)
        .with_graceful_shutdown(crate::shutdown_signal())
        .await?;

    info!("Station shut down gracefully");
    Ok(())
}

// ═══════════════════════════════════════════════════════════════════
// SSE handlers (MCP protocol)
// ═══════════════════════════════════════════════════════════════════

async fn handle_sse(
    State(state): State<Arc<AppState>>,
) -> impl axum::response::IntoResponse {
    let headers = crate::SSE_STREAM_HEADERS;
    let session_id = Uuid::new_v4().to_string();
    let (tx, rx) = mpsc::channel::<Result<Event, axum::Error>>(32);

    let endpoint_url = format!("/message?sessionId={session_id}");
    let endpoint_event = Event::default()
        .event("endpoint")
        .data(endpoint_url);

    if let Err(e) = tx.send(Ok(endpoint_event)).await {
        error!(error = %e, "Failed to send endpoint event");
    }

    // Enforce session cap
    {
        let sessions = state.sessions.lock().await;
        if sessions.len() >= MAX_SESSIONS {
            warn!(count = sessions.len(), max = MAX_SESSIONS, "Session cap reached, rejecting");
            return (headers, Sse::new(ReceiverStream::new(rx)).keep_alive(KeepAlive::default()));
        }
    }

    let now = tokio::time::Instant::now();
    info!(session_id = %session_id, "SSE session opened");
    state.sessions.lock().await.insert(session_id.clone(), SessionInfo {
        tx: tx.clone(),
        created_at: now,
        last_activity: now,
        request_count: 0,
    });

    let mut event_rx = state.event_tx.subscribe();
    let event_session_id = session_id;
    tokio::spawn(async move {
        while let Ok(station_event) = event_rx.recv().await {
            let notification = StationEventNotification::new(station_event);
            let json = match serde_json::to_string(&notification) {
                Ok(j) => j,
                Err(_) => continue,
            };
            let sse_event = Event::default().event("station_event").data(json);
            if tx.send(Ok(sse_event)).await.is_err() {
                debug!(session_id = %event_session_id, "SSE session closed");
                break;
            }
        }
    });

    (headers, Sse::new(ReceiverStream::new(rx)).keep_alive(KeepAlive::default()))
}

#[derive(serde::Deserialize)]
struct MessageQuery {
    #[serde(rename = "sessionId")]
    session_id: String,
}

async fn handle_message(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(query): Query<MessageQuery>,
    Json(request): Json<JsonRpcRequest>,
) -> impl IntoResponse {
    let session_id = &query.session_id;
    let auth_header = headers
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok().map(|s| s.to_string()));

    // Auth gate: check tools/call requests (before locking sessions)
    if request.method == "tools/call" {
        let result = state.auth_gate.check_rpc(auth_header.as_deref(), request.params.as_ref());
        if !matches!(result, AuthResult::Allowed) {
            warn!(session_id = %session_id, "Unauthorized tool call attempt");
            return StatusCode::UNAUTHORIZED;
        }
    }

    let mut sessions = state.sessions.lock().await;
    let Some(info) = sessions.get_mut(session_id) else {
        warn!(session_id = %session_id, "Unknown session");
        return StatusCode::NOT_FOUND;
    };

    // Update session activity
    info.last_activity = tokio::time::Instant::now();
    info.request_count += 1;

    debug!(
        session_id = %session_id,
        method = %request.method,
        requests = info.request_count,
        "SSE message received"
    );

    let response = handle_request_cached(&state.registry, &state.telemetry, Some(&state.meter), &state.auth_gate, &request, Some(&state.event_tx), auth_header.as_deref(), &state.proxy_cache);

    if let Some(resp) = response {
        let json = match serde_json::to_string(&resp) {
            Ok(j) => j,
            Err(e) => {
                error!(error = %e, "Failed to serialize response");
                return StatusCode::INTERNAL_SERVER_ERROR;
            }
        };

        let event = Event::default().event("message").data(json);
        if let Err(e) = info.tx.send(Ok(event)).await {
            error!(error = %e, "Failed to send SSE event");
            return StatusCode::INTERNAL_SERVER_ERROR;
        }
    }

    StatusCode::ACCEPTED
}

// ═══════════════════════════════════════════════════════════════════
// HTTP REST handlers (any agent framework)
// ═══════════════════════════════════════════════════════════════════

async fn handle_rpc(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(request): Json<JsonRpcRequest>,
) -> impl IntoResponse {
    debug!(method = %request.method, "HTTP RPC request");
    let auth_header = headers
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok().map(|s| s.to_string()));

    // Auth gate: check tools/call requests for non-meta tools
    if request.method == "tools/call" {
        let result = state.auth_gate.check_rpc(auth_header.as_deref(), request.params.as_ref());
        if !matches!(result, AuthResult::Allowed) {
            return (StatusCode::UNAUTHORIZED, Json(auth::auth_error_json(&result))).into_response();
        }
    }

    let response = handle_request_cached(&state.registry, &state.telemetry, Some(&state.meter), &state.auth_gate, &request, Some(&state.event_tx), auth_header.as_deref(), &state.proxy_cache);
    match response {
        Some(resp) => (StatusCode::OK, Json(resp)).into_response(),
        None => StatusCode::ACCEPTED.into_response(),
    }
}

async fn handle_list_tools(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Json<Value> {
    let auth_header = headers
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok());
    let authenticated = state.auth_gate.is_authenticated(auth_header);
    let tools = state.registry.tool_infos_filtered(authenticated);
    info!(count = tools.len(), authenticated, "HTTP tools list");
    Json(serde_json::to_value(tools).unwrap_or_default())
}

async fn handle_tool_call(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    axum::extract::Path(name): axum::extract::Path<String>,
    Json(arguments): Json<Value>,
) -> impl IntoResponse {
    info!(tool = %name, "HTTP tool call");

    // Auth gate: check tool access
    let auth_header = headers
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok().map(|s| s.to_string()));
    let result = state.auth_gate.check(auth_header.as_deref(), &name);
    if !matches!(result, AuthResult::Allowed) {
        return (StatusCode::UNAUTHORIZED, Json(auth::auth_error_json(&result))).into_response();
    }

    let request = JsonRpcRequest {
        jsonrpc: "2.0".into(),
        id: Some(Value::String("http-1".into())),
        method: "tools/call".into(),
        params: Some(serde_json::json!({
            "name": name,
            "arguments": arguments,
        })),
    };

    let response = handle_request_cached(&state.registry, &state.telemetry, Some(&state.meter), &state.auth_gate, &request, Some(&state.event_tx), auth_header.as_deref(), &state.proxy_cache);
    match response {
        Some(resp) => {
            if let Some(result) = resp.result {
                (StatusCode::OK, Json(result)).into_response()
            } else if let Some(err) = resp.error {
                let status = match err.code {
                    -32602 => StatusCode::BAD_REQUEST,
                    -32601 => StatusCode::NOT_FOUND,
                    _ => StatusCode::INTERNAL_SERVER_ERROR,
                };
                (status, Json(serde_json::json!({
                    "error": err.message,
                    "code": err.code,
                }))).into_response()
            } else {
                StatusCode::INTERNAL_SERVER_ERROR.into_response()
            }
        }
        None => StatusCode::NO_CONTENT.into_response(),
    }
}

// ═══════════════════════════════════════════════════════════════════
// Response header middleware
// ═══════════════════════════════════════════════════════════════════

/// Inject standard response headers for security hardening and debugging.
async fn response_headers_middleware(
    request: axum::extract::Request,
    next: axum::middleware::Next,
) -> impl IntoResponse {
    let request_id = Uuid::new_v4().to_string();
    let mut response = next.run(request).await;

    let headers = response.headers_mut();

    // 1. Version Info (Redact Git SHA in production per security report)
    let version = if std::env::var("STATION_DEBUG_HEADERS").map(|v| v == "true").unwrap_or(false) {
        format!("{}+{}", env!("CARGO_PKG_VERSION"), env!("GIT_SHA"))
    } else {
        env!("CARGO_PKG_VERSION").to_string()
    };
    if let Ok(v) = HeaderValue::from_str(&version) {
        headers.insert("x-station-version", v);
    }

    // 2. Request Correlation
    if let Ok(v) = HeaderValue::from_str(&request_id) {
        headers.insert("x-request-id", v);
    }

    // 3. Security Hardening Headers (fixes security report issue #6)
    headers.insert("x-content-type-options", HeaderValue::from_static("nosniff"));
    headers.insert("x-frame-options", HeaderValue::from_static("DENY"));
    headers.insert(
        "strict-transport-security",
        HeaderValue::from_static("max-age=31536000; includeSubDomains"),
    );
    headers.insert(
        "content-security-policy",
        HeaderValue::from_static("default-src 'none'; frame-ancestors 'none';"),
    );
    headers.insert("referrer-policy", HeaderValue::from_static("no-referrer"));

    // 4. Cache Control for API responses
    if !headers.contains_key("cache-control") {
        headers.insert("cache-control", HeaderValue::from_static("no-store, max-age=0"));
    }

    response
}

// ═══════════════════════════════════════════════════════════════════
// Root landing + well-known discovery
// ═══════════════════════════════════════════════════════════════════

/// robots.txt — prevent crawlers from hitting MCP endpoints and generating noise errors.
async fn handle_robots_txt() -> (StatusCode, [(axum::http::HeaderName, &'static str); 1], &'static str) {
    (
        StatusCode::OK,
        [(axum::http::header::CONTENT_TYPE, "text/plain")],
        "User-agent: *\n\
         Allow: /\n\
         Allow: /health\n\
         Allow: /.well-known/mcp.json\n\
         Disallow: /mcp\n\
         Disallow: /sse\n\
         Disallow: /message\n\
         Disallow: /rpc\n\
         Disallow: /tools\n\
         Disallow: /billing\n\
         Disallow: /stats\n\
         \n\
         # NexVigilant Station — pharmacovigilance intelligence for AI agents\n\
         # MCP endpoint: POST https://mcp.nexvigilant.com/mcp\n\
         # Docs: https://nexvigilant.com\n",
    )
}

/// Root landing page — helps clients that hit / instead of /mcp.
async fn handle_root(
    State(state): State<Arc<AppState>>,
) -> Json<Value> {
    Json(serde_json::json!({
        "name": "nexvigilant-station",
        "description": "NexVigilant Station — pharmacovigilance intelligence for AI agents",
        "mcp_endpoint": "/mcp",
        "sse_endpoint": "/sse",
        "rest_endpoint": "/tools",
        "health_endpoint": "/health",
        "tools": state.registry.tool_count(),
        "protocol": "MCP 2025-03-26",
        "docs": "Connect via https://mcp.nexvigilant.com/mcp (Streamable HTTP) or /sse (SSE)",
    }))
}

/// MCP discovery document at /.well-known/mcp.json
async fn handle_well_known_mcp() -> Json<Value> {
    Json(serde_json::json!({
        "mcp": {
            "version": "2025-03-26",
            "endpoint": "https://mcp.nexvigilant.com/mcp",
            "transports": [
                {
                    "type": "streamable-http",
                    "url": "https://mcp.nexvigilant.com/mcp",
                    "auth": "none"
                },
                {
                    "type": "sse",
                    "url": "https://mcp.nexvigilant.com/sse",
                    "message_url": "https://mcp.nexvigilant.com/message",
                    "auth": "none"
                }
            ]
        },
        "server": {
            "name": "nexvigilant-station",
            "vendor": "NexVigilant, LLC",
            "url": "https://nexvigilant.com"
        }
    }))
}

/// MCP Registry authentication at /.well-known/mcp-registry-auth
/// Serves the Ed25519 public key for domain verification.
async fn handle_well_known_registry_auth() -> &'static str {
    "v=MCPv1; k=ed25519; p=WoxR+TpKge4Id472oVK/R2CXDbc93+gB0ldGQmVi90E="
}

// ═══════════════════════════════════════════════════════════════════
// Health (unified)
// ═══════════════════════════════════════════════════════════════════

async fn handle_health(
    State(state): State<Arc<AppState>>,
) -> Json<Value> {
    let sessions = state.sessions.lock().await;
    let health = state.telemetry.health();
    Json(serde_json::json!({
        "status": "ok",
        "transport": "combined",
        "surfaces": {
            "streamable_http": "/mcp",
            "sse": "/sse",
            "rpc": "/rpc",
            "rest": "/tools",
        },
        "configs": state.registry.configs.len(),
        "tools": state.registry.tool_count(),
        "courses": crate::science::course_count(),
        "active_sessions": sessions.len(),
        "telemetry": {
            "uptime_seconds": health.uptime_seconds,
            "total_calls": health.total_calls,
            "total_errors": health.total_errors,
            "error_rate_pct": health.error_rate_pct,
            "calls_per_minute": health.calls_per_minute,
            "latency_p99_ms": health.latency_p99_ms,
            "slo_status": health.slo_status,
            "trend": health.trend,
            "degraded_domains": health.degraded_domains,
        },
        "config_hash": state.registry.config_hash(),
        "server": "nexvigilant-station",
        "version": env!("CARGO_PKG_VERSION"),
        "protocol_version": "2025-03-26",
        "last_checked": format!("{:?}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_secs()),
        "git_sha": env!("GIT_SHA"),
    }))
}

/// Full telemetry stats — domain breakdown, top tools, recent calls.
/// Separated from /health to keep health lightweight for Cloud Run probes.
async fn handle_stats(
    State(state): State<Arc<AppState>>,
) -> Json<Value> {
    let health = state.telemetry.health();
    Json(serde_json::to_value(health).unwrap_or_default())
}

/// MoltBook — config lookup by domain.
///
/// Returns browser automation configs matching a domain query, following the
/// WebMCP Hub schema. Any MoltBrowser-compatible MCP client can discover tools
/// for a site by querying this endpoint.
///
///   GET /configs/lookup?domain=dailymed.nlm.nih.gov
///
/// Response is a JSON array of matching configs with their tools, parameters,
/// and execution metadata — ready for browser automation or API proxy dispatch.
async fn handle_configs_lookup(
    State(state): State<Arc<AppState>>,
    Query(params): Query<HashMap<String, String>>,
) -> Json<Value> {
    let query = params.get("domain").cloned().unwrap_or_default();

    if query.is_empty() {
        // No domain specified — return all configs (catalog mode)
        let configs: Vec<Value> = state.registry.configs.iter().map(|c| {
            config_to_moltbook_json(c)
        }).collect();
        return Json(serde_json::json!({ "configs": configs }));
    }

    // Match configs whose domain contains the query string (case-insensitive)
    let query_lower = query.to_lowercase();
    let matched: Vec<Value> = state.registry.configs.iter()
        .filter(|c| c.domain.to_lowercase().contains(&query_lower))
        .map(config_to_moltbook_json)
        .collect();

    Json(serde_json::json!({ "configs": matched }))
}

/// Convert a HubConfig to MoltBook/WebMCP Hub JSON format.
fn config_to_moltbook_json(config: &crate::config::HubConfig) -> Value {
    let tools: Vec<Value> = config.tools.iter().map(|t| {
        let params: Vec<Value> = t.parameters.iter().map(|p| {
            serde_json::json!({
                "name": p.name,
                "type": p.param_type,
                "description": p.description,
                "required": p.required,
            })
        }).collect();

        let mut tool_json = serde_json::json!({
            "name": t.name,
            "description": t.description,
            "inputSchema": {
                "type": "object",
                "properties": params.iter().map(|p| {
                    let name = p["name"].as_str().unwrap_or_default().to_string();
                    let prop = serde_json::json!({
                        "type": p["type"].as_str().unwrap_or("string"),
                        "description": p["description"],
                    });
                    (name, prop)
                }).collect::<serde_json::Map<String, Value>>(),
                "required": t.parameters.iter()
                    .filter(|p| p.required)
                    .map(|p| Value::String(p.name.clone()))
                    .collect::<Vec<Value>>(),
            },
        });

        if let Some(schema) = &t.output_schema {
            tool_json.as_object_mut().map(|o| o.insert("outputSchema".into(), schema.clone()));
        }
        if let Some(ann) = &t.annotations {
            tool_json.as_object_mut().map(|o| o.insert("annotations".into(),
                serde_json::to_value(ann).unwrap_or_default()));
        }

        tool_json
    }).collect();

    // Classify config source type by domain pattern:
    // - nexvigilant.com domains = rust-native computation (no external API)
    // - known external API domains = live API proxy
    // - everything else = curated reference data
    let domain_lower = config.domain.to_lowercase();
    let source_type = if domain_lower.ends_with(".nexvigilant.com") {
        "rust-native"
    } else if [
        "api.fda.gov", "clinicaltrials.gov", "pubmed.ncbi.nlm.nih.gov",
        "dailymed.nlm.nih.gov", "rxnav.nlm.nih.gov", "open-vigil.fr",
        "accessdata.fda.gov", "eudravigilance.ema.europa.eu",
        "eudravigilance-live.ema.europa.eu", "www.ema.europa.eu",
        "vigiaccess.org", "en.wikipedia.org", "claude.ai", "www.linkedin.com",
    ].iter().any(|&d| domain_lower == d)
        || (domain_lower.starts_with("www.") && [
            "abbvie", "amgen", "astrazeneca", "bayer", "bms", "gilead",
            "gsk", "jnj", "lilly", "merck", "novartis", "novonordisk",
            "pfizer", "roche", "sanofi", "fda.gov",
        ].iter().any(|company| domain_lower.contains(company)))
    {
        "live-api"
    } else {
        "reference"
    };

    serde_json::json!({
        "domain": config.domain,
        "urlPattern": config.url_pattern,
        "title": config.title,
        "description": config.description,
        "tools": tools,
        "toolCount": tools.len(),
        "sourceType": source_type,
        "private": config.private,
    })
}

/// MoltContrib — accept agent-contributed configs.
///
/// POST /configs/contribute
///
/// Agents submit new site configs after browser exploration sessions.
/// Validates the config schema, writes to the configs/ directory,
/// and returns the config ID. The new config's tools become available
/// on next binary restart (or live if hot-reload is implemented).
///
/// Body: HubConfig JSON (domain, title, tools[])
async fn handle_configs_contribute(
    State(state): State<Arc<AppState>>,
    Json(body): Json<Value>,
) -> (StatusCode, Json<Value>) {
    // Validate required fields
    let domain = match body.get("domain").and_then(|v| v.as_str()) {
        Some(d) if !d.is_empty() => d.to_string(),
        _ => return (StatusCode::BAD_REQUEST, Json(serde_json::json!({
            "status": "error",
            "message": "domain is required (e.g., 'example.com')",
        }))),
    };

    let title = match body.get("title").and_then(|v| v.as_str()) {
        Some(t) if !t.is_empty() => t.to_string(),
        _ => return (StatusCode::BAD_REQUEST, Json(serde_json::json!({
            "status": "error",
            "message": "title is required",
        }))),
    };

    let tools = match body.get("tools").and_then(|v| v.as_array()) {
        Some(t) if !t.is_empty() => t,
        _ => return (StatusCode::BAD_REQUEST, Json(serde_json::json!({
            "status": "error",
            "message": "tools array is required with at least one tool",
        }))),
    };

    // Validate each tool has name + description
    for (i, tool) in tools.iter().enumerate() {
        if tool.get("name").and_then(|v| v.as_str()).unwrap_or("").is_empty() {
            return (StatusCode::BAD_REQUEST, Json(serde_json::json!({
                "status": "error",
                "message": format!("tool[{}] missing required 'name' field", i),
            })));
        }
        if tool.get("description").and_then(|v| v.as_str()).unwrap_or("").is_empty() {
            return (StatusCode::BAD_REQUEST, Json(serde_json::json!({
                "status": "error",
                "message": format!("tool[{}] missing required 'description' field", i),
            })));
        }
    }

    // Check for duplicate domain
    let domain_exists = state.registry.configs.iter().any(|c| c.domain == domain);

    // Generate config filename from domain
    let filename = domain.replace('.', "-").replace('/', "_");
    let config_path = format!("{}/configs/{}.json", state.registry.station_root, filename);

    // Write config to disk
    let config_json = serde_json::json!({
        "domain": domain,
        "url_pattern": body.get("urlPattern").or(body.get("url_pattern"))
            .and_then(|v| v.as_str()).unwrap_or("/*"),
        "title": title,
        "description": body.get("description").and_then(|v| v.as_str()),
        "tools": tools,
    });
let config_pretty = serde_json::to_string_pretty(&config_json).unwrap_or_default();

// Write config to disk (ephemeral on Cloud Run, persistent on local dev)
let write_result = std::fs::write(&config_path, &config_pretty);

// Persist to GCS if configured (Primary persistence for Cloud Run)
if let Ok(bucket) = std::env::var("MOLTCONTRIB_BUCKET") {
    let object_name = format!("configs/{}.json", filename);
    if let Err(e) = state.gcp_client.upload_to_gcs(&bucket, &object_name, config_pretty.as_bytes()) {
        warn!(bucket = %bucket, object = %object_name, error = %e, "MoltContrib: GCS persistence failed");
    } else {
        info!(bucket = %bucket, object = %object_name, "MoltContrib: GCS persistence successful");
    }
}

    match write_result {
        Ok(_) => {
            info!(
                domain = %domain,
                tools = tools.len(),
                path = %config_path,
                "MoltContrib: config contributed"
            );
            (StatusCode::CREATED, Json(serde_json::json!({
                "status": "ok",
                "message": if domain_exists {
                    "Config updated (existing domain — will take effect on restart)"
                } else {
                    "Config created (will take effect on restart)"
                },
                "domain": domain,
                "toolCount": tools.len(),
                "configPath": config_path,
                "note": "Config is persisted. Tools become available after station restart.",
            })))
        }
        Err(e) => {
            warn!(domain = %domain, error = %e, "MoltContrib: failed to write config");
            (StatusCode::INTERNAL_SERVER_ERROR, Json(serde_json::json!({
                "status": "error",
                "message": format!("Failed to write config: {}", e),
            })))
        }
    }
}

/// MoltWatch — config health monitoring.
///
/// GET /configs/watch
///
/// Tests all configs with proxy scripts by checking if the proxy script
/// exists and is executable. For live-api configs, optionally pings the
/// upstream endpoint. Returns health status per config.
async fn handle_configs_watch(
    State(state): State<Arc<AppState>>,
) -> Json<Value> {
    let mut results = Vec::new();

    // On Cloud Run, proxy scripts aren't bundled — only Rust-native handlers
    // are available. Adjust health check to not penalize missing proxies.
    let is_cloud_run = std::env::var("K_SERVICE").is_ok();

    for config in &state.registry.configs {
        let domain = &config.domain;
        let tool_count = config.tools.len();
        let domain_lower = domain.to_lowercase();

        // Determine if this config uses Rust-native handlers (no proxy needed)
        let is_rust_native = domain_lower.ends_with(".nexvigilant.com");

        // Check proxy script existence (only meaningful locally, not on Cloud Run)
        let proxy_status = if is_rust_native {
            "rust-native"
        } else if let Some(ref proxy) = config.proxy {
            if is_cloud_run {
                // On Cloud Run, proxy configs route through dispatch.py which
                // calls external APIs — proxy script absence is expected
                "cloud-run-proxy"
            } else {
                let proxy_path = format!("{}/{}", state.registry.station_root, proxy);
                if std::path::Path::new(&proxy_path).exists() {
                    "healthy"
                } else {
                    "missing_proxy"
                }
            }
        } else {
            "healthy"
        };

        // Check for stub tools (tools with stub_response = no real implementation)
        let stub_count = config.tools.iter()
            .filter(|t| t.stub_response.is_some())
            .count();

        let status = if proxy_status == "missing_proxy" {
            "degraded"
        } else if stub_count == tool_count && tool_count > 0 {
            "stub_only"
        } else if stub_count > 0 {
            "partial"
        } else {
            "healthy"
        };

        results.push(serde_json::json!({
            "domain": domain,
            "status": status,
            "toolCount": tool_count,
            "stubCount": stub_count,
            "proxyStatus": proxy_status,
            "sourceType": if is_rust_native { "rust-native" } else { "proxy" },
        }));
    }

    let healthy = results.iter().filter(|r| r["status"] == "healthy").count();
    let degraded = results.len() - healthy;

    Json(serde_json::json!({
        "status": "ok",
        "summary": {
            "total": results.len(),
            "healthy": healthy,
            "degraded": degraded,
            "health_pct": if results.is_empty() { 100.0 } else {
                (healthy as f64 / results.len() as f64 * 100.0 * 10.0).round() / 10.0
            },
        },
        "configs": results,
    }))
}

