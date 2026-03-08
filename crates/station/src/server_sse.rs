use std::collections::HashMap;
use std::sync::Arc;

use axum::extract::{Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::response::IntoResponse;
use axum::routing::{get, post};
use axum::Json;
use tokio::sync::{broadcast, mpsc, Mutex};
use tokio_stream::wrappers::ReceiverStream;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

use crate::auth::{ApiKeyGate, AuthResult};
use crate::config::ConfigRegistry;
use crate::protocol::{JsonRpcRequest, StationEvent, StationEventNotification};
use crate::server::handle_request;
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
    registry: ConfigRegistry,
    telemetry: StationTelemetry,
    event_tx: broadcast::Sender<StationEvent>,
    sessions: Mutex<HashMap<String, SessionInfo>>,
    auth_gate: ApiKeyGate,
}

/// Run the MCP server over SSE (Server-Sent Events) transport.
///
/// MCP SSE protocol:
///   GET  /sse              → opens SSE stream, receives `endpoint` event
///   POST /message?sessionId=xxx → client sends JSON-RPC, response on SSE stream
///   GET  /health           → liveness check
pub async fn run_sse(
    registry: ConfigRegistry,
    telemetry: StationTelemetry,
    event_tx: broadcast::Sender<StationEvent>,
    host: &str,
    port: u16,
) -> anyhow::Result<()> {
    let auth_gate = ApiKeyGate::from_env();
    let state = Arc::new(AppState {
        registry,
        telemetry,
        event_tx,
        sessions: Mutex::new(HashMap::new()),
        auth_gate,
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

    let app = axum::Router::new()
        .route("/sse", get(handle_sse))
        .route("/message", post(handle_message))
        .route("/health", get(handle_health))
        .with_state(state);

    let addr = format!("{host}:{port}");
    let listener = tokio::net::TcpListener::bind(&addr).await?;
    info!(addr = %addr, "Station SSE transport listening");
    axum::serve(listener, app)
        .with_graceful_shutdown(crate::shutdown_signal())
        .await?;
    info!("Station SSE transport shut down gracefully");
    Ok(())
}

async fn handle_sse(
    State(state): State<Arc<AppState>>,
) -> Sse<impl tokio_stream::Stream<Item = Result<Event, axum::Error>>> {
    let session_id = Uuid::new_v4().to_string();
    let (tx, rx) = mpsc::channel::<Result<Event, axum::Error>>(32);

    // Send the endpoint event — tells the client where to POST requests
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
            // Still return an SSE stream — but it will just have the endpoint event
            // and no session registered, so /message will 404
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

    // Subscribe this SSE session to station events
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
                debug!(session_id = %event_session_id, "SSE session closed, stopping event forward");
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

async fn handle_health(
    State(state): State<Arc<AppState>>,
) -> Json<serde_json::Value> {
    let sessions = state.sessions.lock().await;
    Json(serde_json::json!({
        "status": "ok",
        "transport": "sse",
        "configs": state.registry.configs.len(),
        "tools": state.registry.tool_count(),
        "courses": crate::science::course_count(),
        "active_sessions": sessions.len(),
        "server": "nexvigilant-station",
        "version": env!("CARGO_PKG_VERSION"),
    }))
}
