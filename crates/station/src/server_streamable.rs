//! MCP Streamable HTTP transport — required for Claude.ai Connectors.
//!
//! Implements the MCP 2025-03-26 Streamable HTTP transport spec:
//! - Single POST endpoint at `/mcp` accepts JSON-RPC requests
//! - Responses can be direct JSON (for simple requests) or SSE streams
//! - Session management via `Mcp-Session-Id` header
//! - GET `/mcp` returns SSE stream for server-initiated notifications
//! - DELETE `/mcp` terminates a session
//!
//! This runs alongside the existing SSE + HTTP REST routes in combined mode,
//! so the same Cloud Run deployment serves both legacy and Streamable clients.

use std::collections::HashMap;
use std::sync::Arc;

use axum::extract::State;
use axum::http::{HeaderMap, StatusCode};
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::response::IntoResponse;
use tokio::sync::{broadcast, mpsc, Mutex};
use tokio_stream::wrappers::ReceiverStream;
use tracing::{debug, info, warn};
use uuid::Uuid;

use crate::auth::{ApiKeyGate, AuthResult};
use crate::config::ConfigRegistry;
use crate::protocol::{JsonRpcRequest, JsonRpcResponse, StationEvent, StationEventNotification};
use crate::server::{handle_request, handle_request_with_auth};
use crate::telemetry::StationTelemetry;

/// Maximum concurrent Streamable HTTP sessions.
const MAX_STREAMABLE_SESSIONS: usize = 500;

/// Session idle timeout (seconds) before reaping.
const STREAMABLE_IDLE_TIMEOUT_SECS: u64 = 600;

/// How often the reaper runs (seconds).
const STREAMABLE_REAPER_INTERVAL_SECS: u64 = 120;

/// Session metadata for Streamable HTTP transport.
struct StreamableSession {
    /// SSE channel for server-initiated notifications (GET /mcp).
    notification_tx: Option<mpsc::Sender<Result<Event, axum::Error>>>,
    #[allow(dead_code)] // Available for diagnostics and future health reporting
    created_at: tokio::time::Instant,
    last_activity: tokio::time::Instant,
    request_count: u64,
}


/// Shared state for the Streamable HTTP transport.
///
/// Uses `Arc` references to the registry and telemetry from the parent
/// combined server — no cloning needed.
pub struct StreamableState {
    pub registry: Arc<ConfigRegistry>,
    pub telemetry: Arc<StationTelemetry>,
    pub event_tx: broadcast::Sender<StationEvent>,
    sessions: Mutex<HashMap<String, StreamableSession>>,
    pub auth_gate: ApiKeyGate,
    pub meter: Arc<crate::metering::StationMeter>,
}

impl StreamableState {
    pub fn new(
        registry: Arc<ConfigRegistry>,
        telemetry: Arc<StationTelemetry>,
        event_tx: broadcast::Sender<StationEvent>,
        auth_gate: ApiKeyGate,
        meter: Arc<crate::metering::StationMeter>,
    ) -> Self {
        Self {
            registry,
            telemetry,
            event_tx,
            sessions: Mutex::new(HashMap::new()),
            auth_gate,
            meter,
        }
    }

    /// Spawn the session reaper task.
    pub fn spawn_reaper(state: Arc<StreamableState>) {
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(
                std::time::Duration::from_secs(STREAMABLE_REAPER_INTERVAL_SECS),
            );
            loop {
                interval.tick().await;
                let mut sessions = state.sessions.lock().await;
                let before = sessions.len();
                let cutoff = tokio::time::Instant::now()
                    - std::time::Duration::from_secs(STREAMABLE_IDLE_TIMEOUT_SECS);
                sessions.retain(|id, info| {
                    let alive = info.last_activity > cutoff;
                    if !alive {
                        debug!(session_id = %id, "Reaping idle streamable session");
                    }
                    alive
                });
                let reaped = before - sessions.len();
                if reaped > 0 {
                    info!(reaped, remaining = sessions.len(), "Streamable session reaper cycle");
                }
            }
        });
    }
}

/// Extract or create a session ID from the `Mcp-Session-Id` header.
fn get_session_id(headers: &HeaderMap) -> Option<String> {
    headers
        .get("mcp-session-id")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.to_string())
}

// ═══════════════════════════════════════════════════════════════════
// POST /mcp — Main Streamable HTTP endpoint
// ═══════════════════════════════════════════════════════════════════

/// Handle POST /mcp — the primary Streamable HTTP endpoint.
///
/// Per the MCP spec:
/// - `initialize` creates a new session, response includes `Mcp-Session-Id`
/// - Subsequent requests must include the session ID header
/// - Response is direct JSON for most methods
/// - Could be SSE for long-running operations (not needed for tools/list, tools/call)
pub async fn handle_mcp_post(
    State(state): State<Arc<StreamableState>>,
    headers: HeaderMap,
    body: String,
) -> impl IntoResponse {
    // Try parsing as single request first, then as batch array.
    // MCP Streamable HTTP spec requires batch support.
    let request: JsonRpcRequest = match serde_json::from_str(&body) {
        Ok(r) => r,
        Err(_) => {
            // Try batch: parse as array, process each, return array response.
            // MCP Streamable HTTP spec requires batch support.
            if let Ok(batch) = serde_json::from_str::<Vec<JsonRpcRequest>>(&body) {
                let mut responses = Vec::new();
                let mut session_id = None;
                for req in &batch {
                    // Handle initialize within batch — create session
                    if req.method == "initialize" {
                        let sid = Uuid::new_v4().to_string();
                        let now = tokio::time::Instant::now();
                        state.sessions.lock().await.insert(sid.clone(), StreamableSession {
                            notification_tx: None,
                            created_at: now,
                            last_activity: now,
                            request_count: 1,
                        });
                        info!(session_id = %sid, "Streamable HTTP session created (batch)");
                        session_id = Some(sid);
                    }
                    // Skip notifications (no response expected)
                    if req.id.is_none() {
                        continue;
                    }
                    let batch_auth = headers
                        .get(axum::http::header::AUTHORIZATION)
                        .and_then(|v| v.to_str().ok());
                    if let Some(resp) = handle_request_with_auth(
                        &state.registry,
                        &state.telemetry,
                        Some(&state.meter),
                        &state.auth_gate,
                        req,
                        Some(&state.event_tx),
                        batch_auth,
                    ) {
                        responses.push(resp);
                    }
                }
                let json = serde_json::to_string(&responses).unwrap_or_default();
                let sid = session_id.as_deref().unwrap_or("");
                return (
                    StatusCode::OK,
                    [
                        ("content-type", "application/json"),
                        ("mcp-session-id", sid),
                    ],
                    json,
                ).into_response();
            }
            let resp = JsonRpcResponse::error(
                None,
                crate::protocol::PARSE_ERROR,
                "Parse error: expected JSON-RPC request object or batch array",
            );
            return (StatusCode::OK, [("content-type", "application/json")], serde_json::to_string(&resp).unwrap_or_default()).into_response();
        }
    };

    // Handle initialize — create session, advertise Streamable HTTP protocol version
    if request.method == "initialize" {
        return handle_streamable_initialize(state, request).await.into_response();
    }

    // Handle notifications (no id = no response expected)
    if request.method == "notifications/initialized" || request.id.is_none() {
        // Update session activity if session exists
        if let Some(session_id) = get_session_id(&headers) {
            let mut sessions = state.sessions.lock().await;
            if let Some(info) = sessions.get_mut(&session_id) {
                info.last_activity = tokio::time::Instant::now();
            }
        }
        return StatusCode::ACCEPTED.into_response();
    }

    // Session tracking is optional — Claude.ai connectors may not forward
    // the Mcp-Session-Id header. Process requests statelessly if absent.
    let session_id = get_session_id(&headers);

    // Update session activity if session exists
    if let Some(ref sid) = session_id {
        let mut sessions = state.sessions.lock().await;
        if let Some(info) = sessions.get_mut(sid) {
            info.last_activity = tokio::time::Instant::now();
            info.request_count += 1;
        }
    }

    // Auth gate for tools/call
    if request.method == "tools/call" {
        let auth_header = headers
            .get(axum::http::header::AUTHORIZATION)
            .and_then(|v| v.to_str().ok());
        let result = state.auth_gate.check_rpc(auth_header, request.params.as_ref());
        if !matches!(result, AuthResult::Allowed) {
            warn!(session_id = ?session_id, "Unauthorized streamable tool call");
            let resp = JsonRpcResponse::error(
                request.id,
                -32600,
                "Unauthorized",
            );
            return (
                StatusCode::UNAUTHORIZED,
                [("content-type", "application/json")],
                serde_json::to_string(&resp).unwrap_or_default(),
            ).into_response();
        }
    }

    debug!(
        session_id = ?session_id,
        method = %request.method,
        "Streamable HTTP request"
    );

    // Handle notifications (no id = no response expected)
    if request.id.is_none() {
        return StatusCode::ACCEPTED.into_response();
    }

    // Process the request through the shared handler (with auth for tools/list filtering)
    let auth_header = headers
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok());
    let response = handle_request_with_auth(
        &state.registry,
        &state.telemetry,
        Some(&state.meter),
        &state.auth_gate,
        &request,
        Some(&state.event_tx),
        auth_header,
    );

    match response {
        Some(resp) => {
            let json = serde_json::to_string(&resp).unwrap_or_default();
            let sid = session_id.as_deref().unwrap_or("");
            (
                StatusCode::OK,
                [
                    ("content-type", "application/json"),
                    ("mcp-session-id", sid),
                ],
                json,
            ).into_response()
        }
        None => StatusCode::ACCEPTED.into_response(),
    }
}

/// Handle the initialize request — creates a new session.
async fn handle_streamable_initialize(
    state: Arc<StreamableState>,
    request: JsonRpcRequest,
) -> impl IntoResponse {
    // Check session cap
    {
        let sessions = state.sessions.lock().await;
        if sessions.len() >= MAX_STREAMABLE_SESSIONS {
            warn!(
                count = sessions.len(),
                max = MAX_STREAMABLE_SESSIONS,
                "Streamable session cap reached"
            );
            let resp = JsonRpcResponse::error(
                request.id,
                -32000,
                "Server at capacity. Try again later.",
            );
            return (
                StatusCode::SERVICE_UNAVAILABLE,
                [("content-type", "application/json")],
                serde_json::to_string(&resp).unwrap_or_default(),
            ).into_response();
        }
    }

    // Create session
    let session_id = Uuid::new_v4().to_string();
    let now = tokio::time::Instant::now();

    {
        let mut sessions = state.sessions.lock().await;
        sessions.insert(session_id.clone(), StreamableSession {
            notification_tx: None,
            created_at: now,
            last_activity: now,
            request_count: 1,
        });
    }

    info!(session_id = %session_id, "Streamable HTTP session created");

    // Process initialize through the shared handler
    let response = handle_request(
        &state.registry,
        &state.telemetry,
        &state.auth_gate,
        &request,
        Some(&state.event_tx),
    );

    match response {
        Some(resp) => {
            // Patch protocol version to 2025-03-26 for Streamable HTTP transport
            let mut json_val = serde_json::to_value(&resp).unwrap_or_default();
            if let Some(result) = json_val.get_mut("result")
                && let Some(obj) = result.as_object_mut()
            {
                obj.insert(
                    "protocolVersion".to_string(),
                    serde_json::Value::String("2025-03-26".to_string()),
                );
            }
            let json = serde_json::to_string(&json_val).unwrap_or_default();
            (
                StatusCode::OK,
                [
                    ("content-type", "application/json"),
                    ("mcp-session-id", session_id.as_str()),
                ],
                json,
            ).into_response()
        }
        None => StatusCode::ACCEPTED.into_response(),
    }
}

// ═══════════════════════════════════════════════════════════════════
// GET /mcp — SSE stream for server-initiated notifications
// ═══════════════════════════════════════════════════════════════════

/// Handle GET /mcp — opens an SSE stream for server-to-client notifications.
///
/// Per the MCP spec, clients can open a GET connection to receive
/// server-initiated messages (e.g., tool list changes, progress updates).
pub async fn handle_mcp_get(
    State(state): State<Arc<StreamableState>>,
    headers: HeaderMap,
) -> impl IntoResponse {
    let session_id = match get_session_id(&headers) {
        Some(id) => id,
        None => {
            return (StatusCode::BAD_REQUEST, "Missing Mcp-Session-Id header").into_response();
        }
    };

    let (tx, rx) = mpsc::channel::<Result<Event, axum::Error>>(32);

    // Store the notification channel in the session
    {
        let mut sessions = state.sessions.lock().await;
        let Some(info) = sessions.get_mut(&session_id) else {
            return (StatusCode::NOT_FOUND, "Unknown session").into_response();
        };
        info.notification_tx = Some(tx.clone());
        info.last_activity = tokio::time::Instant::now();
    }

    // Forward station events to this SSE stream
    let mut event_rx = state.event_tx.subscribe();
    let event_session_id = session_id.clone();
    tokio::spawn(async move {
        while let Ok(station_event) = event_rx.recv().await {
            let notification = StationEventNotification::new(station_event);
            let json = match serde_json::to_string(&notification) {
                Ok(j) => j,
                Err(_) => continue,
            };
            let sse_event = Event::default().event("message").data(json);
            if tx.send(Ok(sse_event)).await.is_err() {
                debug!(session_id = %event_session_id, "Streamable SSE stream closed");
                break;
            }
        }
    });

    Sse::new(ReceiverStream::new(rx))
        .keep_alive(KeepAlive::default())
        .into_response()
}

// ═══════════════════════════════════════════════════════════════════
// DELETE /mcp — Session termination
// ═══════════════════════════════════════════════════════════════════

/// Handle DELETE /mcp — terminates a session.
pub async fn handle_mcp_delete(
    State(state): State<Arc<StreamableState>>,
    headers: HeaderMap,
) -> impl IntoResponse {
    let session_id = match get_session_id(&headers) {
        Some(id) => id,
        None => {
            return StatusCode::BAD_REQUEST;
        }
    };

    let mut sessions = state.sessions.lock().await;
    if sessions.remove(&session_id).is_some() {
        info!(session_id = %session_id, "Streamable session terminated");
        StatusCode::OK
    } else {
        StatusCode::NOT_FOUND
    }
}
