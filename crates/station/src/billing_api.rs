//! Billing API endpoints for NexVigilant Station toll billing.
//!
//! Exposed as REST routes on the Station server:
//!   GET /billing/usage   — usage summary for authenticated caller
//!   GET /billing/rates   — public rate card (no auth required)
//!   GET /billing/balance — pre-paid credit balance (placeholder)

use axum::http::{HeaderMap, StatusCode};
use axum::response::IntoResponse;
use axum::Json;
use serde_json::json;
use tracing::info;

use crate::pricing;

/// GET /billing/usage — requires Bearer auth, returns usage for the caller's key prefix.
pub async fn handle_usage(headers: HeaderMap) -> impl IntoResponse {
    let auth_header = headers
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok());

    let client_id = match crate::metering::extract_client_id(auth_header) {
        Some(id) => id,
        None => {
            return (
                StatusCode::UNAUTHORIZED,
                Json(json!({"error": "Valid API key required. Use Bearer nv_... header."})),
            )
                .into_response()
        }
    };

    info!(client = %client_id, "Billing usage request");

    // In metering-only mode, return placeholder
    // Full implementation reads from Firestore via usage_store
    (StatusCode::OK, Json(json!({
        "client_id": client_id,
        "period": "current",
        "input_tokens": 0,
        "output_tokens": 0,
        "tool_calls": 0,
        "estimated_cost_microcents": 0,
        "estimated_cost_usd": "$0.0000",
        "harness_markup_pct": pricing::harness_markup_pct(),
        "status": "metering_only",
        "message": "Usage data is being collected. Full reporting available after metering validation."
    }))).into_response()
}

/// GET /billing/rates — public rate card, no auth required.
pub async fn handle_rates() -> impl IntoResponse {
    let card = pricing::get_rate_card();

    Json(json!({
        "harness_premium_pct": pricing::harness_markup_pct(),
        "description": "Standard model rates + 30% NexVigilant harness premium",
        "formula": "total = base_cost * 1.30",
        "free_tools": [
            "nexvigilant_chart_course",
            "nexvigilant_directory",
            "nexvigilant_capabilities",
            "nexvigilant_station_health",
            "nexvigilant_ring_health"
        ],
        "rates": card,
    }))
}

/// GET /billing/balance — pre-paid credit balance (placeholder for Stripe integration).
pub async fn handle_balance(headers: HeaderMap) -> impl IntoResponse {
    let auth_header = headers
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok());

    let client_id = match crate::metering::extract_client_id(auth_header) {
        Some(id) => id,
        None => {
            return (
                StatusCode::UNAUTHORIZED,
                Json(json!({"error": "Valid API key required"})),
            )
                .into_response()
        }
    };

    info!(client = %client_id, "Billing balance request");

    (StatusCode::OK, Json(json!({
        "client_id": client_id,
        "balance_microcents": 0,
        "balance_usd": "$0.00",
        "status": "pre_launch",
        "message": "Billing is in metering-only mode. Credits and payments coming soon."
    }))).into_response()
}
