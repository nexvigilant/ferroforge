use std::sync::Arc;

use axum::extract::State;
use axum::http::{HeaderMap, StatusCode};
use axum::response::IntoResponse;
use axum::routing::{get, post};
use axum::Json;
use serde_json::Value;
use tokio::sync::broadcast;
use tracing::{debug, info};

use crate::auth::{self, ApiKeyGate, AuthResult};
use crate::config::ConfigRegistry;
use crate::protocol::{JsonRpcRequest, StationEvent};
use crate::server::handle_request;
use crate::telemetry::StationTelemetry;

struct AppState {
    registry: ConfigRegistry,
    telemetry: StationTelemetry,
    event_tx: broadcast::Sender<StationEvent>,
    auth_gate: ApiKeyGate,
}

/// Run the MCP server over HTTP REST transport (Skyway).
///
/// Any agent framework (LangChain, CrewAI, AutoGen, raw HTTP) can call tools via:
///   POST /rpc              → JSON-RPC 2.0 (full MCP protocol)
///   POST /tools/{name}     → simplified REST: body is arguments, response is result
///   GET  /tools            → list all available tools
///   GET  /health           → liveness check
pub async fn run_http(
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
        auth_gate,
    });

    let app = axum::Router::new()
        .route("/rpc", post(handle_rpc))
        .route("/tools", get(handle_list_tools))
        .route("/tools/{name}", post(handle_tool_call))
        .route("/health", get(handle_health))
        .with_state(state);

    let addr = format!("{host}:{port}");
    let listener = tokio::net::TcpListener::bind(&addr).await?;
    info!(addr = %addr, "Station HTTP transport listening");
    axum::serve(listener, app)
        .with_graceful_shutdown(crate::shutdown_signal())
        .await?;
    info!("Station HTTP transport shut down gracefully");
    Ok(())
}

// Full JSON-RPC 2.0 endpoint — speaks native MCP protocol
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

    let response = handle_request(&state.registry, &state.telemetry, None, &state.auth_gate, &request, Some(&state.event_tx), None);
    match response {
        Some(resp) => (StatusCode::OK, Json(resp)).into_response(),
        None => StatusCode::ACCEPTED.into_response(),
    }
}

// Simplified REST: GET /tools → tool list as JSON array
async fn handle_list_tools(
    State(state): State<Arc<AppState>>,
) -> Json<Value> {
    let tools = state.registry.tool_infos();
    info!(count = tools.len(), "HTTP tools list");
    Json(serde_json::to_value(tools).unwrap_or_default())
}

// Simplified REST: POST /tools/{name} → call a tool, body = arguments
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

    // Synthesize a JSON-RPC request from the REST call
    let request = JsonRpcRequest {
        jsonrpc: "2.0".into(),
        id: Some(Value::String("http-1".into())),
        method: "tools/call".into(),
        params: Some(serde_json::json!({
            "name": name,
            "arguments": arguments,
        })),
    };

    let response = handle_request(&state.registry, &state.telemetry, None, &state.auth_gate, &request, Some(&state.event_tx), None);
    match response {
        Some(resp) => {
            // Unwrap the JSON-RPC envelope for REST clients
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

async fn handle_health(
    State(state): State<Arc<AppState>>,
) -> Json<Value> {
    Json(serde_json::json!({
        "status": "ok",
        "transport": "http",
        "configs": state.registry.configs.len(),
        "tools": state.registry.tool_count(),
        "courses": crate::science::course_count(),
        "server": "nexvigilant-station",
        "version": env!("CARGO_PKG_VERSION"),
        "git_sha": env!("GIT_SHA"),
    }))
}
