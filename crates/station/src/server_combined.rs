use std::collections::HashMap;
use std::sync::Arc;

use axum::extract::{Query, State};
use axum::http::{HeaderValue, Method, StatusCode};
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
}

/// Run the combined MCP server — SSE + HTTP REST on one port.
///
/// Serves ALL transport surfaces simultaneously:
///   GET  /sse              → MCP SSE stream (for mcp-remote, Claude Code)
///   POST /message?sessionId=xxx → MCP JSON-RPC via SSE
///   POST /rpc              → JSON-RPC 2.0 direct (for any MCP client)
///   GET  /tools            → tool catalog as JSON array
///   POST /tools/{name}     → simplified REST tool call
///   GET  /health           → liveness + stats
pub async fn run_combined(
    registry: ConfigRegistry,
    telemetry: StationTelemetry,
    event_tx: broadcast::Sender<StationEvent>,
    host: &str,
    port: u16,
) -> anyhow::Result<()> {
    let state = Arc::new(AppState {
        registry,
        telemetry,
        event_tx,
        sessions: Mutex::new(HashMap::new()),
    });

    let cors = CorsLayer::new()
        .allow_origin("*".parse::<HeaderValue>().expect("valid header"))
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS])
        .allow_headers([
            axum::http::header::CONTENT_TYPE,
            axum::http::header::AUTHORIZATION,
        ]);

    let app = axum::Router::new()
        // SSE transport (MCP protocol — mcp-remote, Claude Code)
        .route("/sse", get(handle_sse))
        .route("/message", post(handle_message))
        // HTTP REST transport (any agent framework)
        .route("/rpc", post(handle_rpc))
        .route("/tools", get(handle_list_tools))
        .route("/tools/{name}", post(handle_tool_call))
        // Health
        .route("/health", get(handle_health))
        .layer(cors)
        .with_state(state);

    let addr = format!("{host}:{port}");
    let listener = tokio::net::TcpListener::bind(&addr).await?;
    info!(addr = %addr, "Station combined transport listening (SSE + HTTP)");
    axum::serve(listener, app).await?;
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

    info!(session_id = %session_id, "SSE session opened");
    state.sessions.lock().await.insert(session_id.clone(), tx.clone());

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
    Query(query): Query<MessageQuery>,
    Json(request): Json<JsonRpcRequest>,
) -> impl IntoResponse {
    let session_id = &query.session_id;

    let sessions = state.sessions.lock().await;
    let Some(tx) = sessions.get(session_id) else {
        warn!(session_id = %session_id, "Unknown session");
        return StatusCode::NOT_FOUND;
    };

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

// ═══════════════════════════════════════════════════════════════════
// HTTP REST handlers (any agent framework)
// ═══════════════════════════════════════════════════════════════════

async fn handle_rpc(
    State(state): State<Arc<AppState>>,
    Json(request): Json<JsonRpcRequest>,
) -> impl IntoResponse {
    debug!(method = %request.method, "HTTP RPC request");
    let response = handle_request(&state.registry, &state.telemetry, &request, Some(&state.event_tx));
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
    axum::extract::Path(name): axum::extract::Path<String>,
    Json(arguments): Json<Value>,
) -> impl IntoResponse {
    info!(tool = %name, "HTTP tool call");

    let request = JsonRpcRequest {
        jsonrpc: "2.0".into(),
        id: Some(Value::String("http-1".into())),
        method: "tools/call".into(),
        params: Some(serde_json::json!({
            "name": name,
            "arguments": arguments,
        })),
    };

    let response = handle_request(&state.registry, &state.telemetry, &request, Some(&state.event_tx));
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
    Json(serde_json::json!({
        "status": "ok",
        "transport": "combined",
        "surfaces": {
            "sse": "/sse",
            "rpc": "/rpc",
            "rest": "/tools",
        },
        "configs": state.registry.configs.len(),
        "tools": state.registry.tool_count(),
        "active_sessions": sessions.len(),
        "server": "nexvigilant-station",
        "version": env!("CARGO_PKG_VERSION"),
    }))
}
