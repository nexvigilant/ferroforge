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
use crate::server::handle_request;
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

    let state = Arc::new(AppState {
        registry: Arc::clone(&registry_arc),
        telemetry: Arc::clone(&telemetry_arc),
        event_tx: event_tx.clone(),
        sessions: Mutex::new(HashMap::new()),
        auth_gate: auth_gate.clone(),
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
    ));
    StreamableState::spawn_reaper(Arc::clone(&streamable_state));

    let cors = CorsLayer::new()
        .allow_origin("*".parse::<HeaderValue>().expect("valid header"))
        .allow_methods([Method::GET, Method::POST, Method::DELETE, Method::OPTIONS])
        .allow_headers([
            axum::http::header::CONTENT_TYPE,
            axum::http::header::AUTHORIZATION,
            "mcp-session-id".parse().expect("valid header name"),
        ])
        .expose_headers([
            "mcp-session-id".parse::<axum::http::HeaderName>().expect("valid header name"),
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
        // Health + Stats (excluded from rate limiting below via middleware ordering)
        .route("/health", get(handle_health))
        .route("/stats", get(handle_stats))
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
) -> Sse<impl tokio_stream::Stream<Item = Result<Event, axum::Error>>> {
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
            return Sse::new(ReceiverStream::new(rx)).keep_alive(KeepAlive::default());
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

    Sse::new(ReceiverStream::new(rx)).keep_alive(KeepAlive::default())
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

    // Auth gate: check tools/call requests (before locking sessions)
    if request.method == "tools/call" {
        let auth_header = headers
            .get(axum::http::header::AUTHORIZATION)
            .and_then(|v| v.to_str().ok());
        let result = state.auth_gate.check_rpc(auth_header, request.params.as_ref());
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

    let response = handle_request(&state.registry, &state.telemetry, &state.auth_gate, &request, Some(&state.event_tx));

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

    // Auth gate: check tools/call requests for non-meta tools
    if request.method == "tools/call" {
        let auth_header = headers
            .get(axum::http::header::AUTHORIZATION)
            .and_then(|v| v.to_str().ok());
        let result = state.auth_gate.check_rpc(auth_header, request.params.as_ref());
        if !matches!(result, AuthResult::Allowed) {
            return (StatusCode::UNAUTHORIZED, Json(auth::auth_error_json(&result))).into_response();
        }
    }

    let response = handle_request(&state.registry, &state.telemetry, &state.auth_gate, &request, Some(&state.event_tx));
    match response {
        Some(resp) => (StatusCode::OK, Json(resp)).into_response(),
        None => StatusCode::ACCEPTED.into_response(),
    }
}

async fn handle_list_tools(
    State(state): State<Arc<AppState>>,
) -> Json<Value> {
    let tools = state.registry.tool_infos();
    info!(count = tools.len(), "HTTP tools list");
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
        .and_then(|v| v.to_str().ok());
    let result = state.auth_gate.check(auth_header, &name);
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

    let response = handle_request(&state.registry, &state.telemetry, &state.auth_gate, &request, Some(&state.event_tx));
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

