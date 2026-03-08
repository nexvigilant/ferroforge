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

struct AppState {
    registry: ConfigRegistry,
    telemetry: StationTelemetry,
    event_tx: broadcast::Sender<StationEvent>,
    sessions: Mutex<HashMap<String, SseChannel>>,
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

    let app = axum::Router::new()
        .route("/sse", get(handle_sse))
        .route("/message", post(handle_message))
        .route("/health", get(handle_health))
        .with_state(state);

    let addr = format!("{host}:{port}");
    let listener = tokio::net::TcpListener::bind(&addr).await?;
    info!(addr = %addr, "Station SSE transport listening");
    axum::serve(listener, app).await?;
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

    info!(session_id = %session_id, "SSE session opened");
    state.sessions.lock().await.insert(session_id.clone(), tx.clone());

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

    let sessions = state.sessions.lock().await;
    let Some(tx) = sessions.get(session_id) else {
        warn!(session_id = %session_id, "Unknown session");
        return StatusCode::NOT_FOUND;
    };

    // Auth gate: check tools/call requests
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

    debug!(
        session_id = %session_id,
        method = %request.method,
        "SSE message received"
    );

    let response = handle_request(&state.registry, &state.telemetry, &request, Some(&state.event_tx));

    if let Some(resp) = response {
        let json = match serde_json::to_string(&resp) {
            Ok(j) => j,
            Err(e) => {
                error!(error = %e, "Failed to serialize response");
                return StatusCode::INTERNAL_SERVER_ERROR;
            }
        };

        let event = Event::default().event("message").data(json);
        if let Err(e) = tx.send(Ok(event)).await {
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
        "active_sessions": sessions.len(),
        "server": "nexvigilant-station",
        "version": env!("CARGO_PKG_VERSION"),
    }))
}
