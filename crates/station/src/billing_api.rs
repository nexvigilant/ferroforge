//! Billing API endpoints for NexVigilant Station toll billing.
//!
//! Exposed as REST routes on the Station server:
//!   GET /billing/usage   — usage summary for authenticated caller
//!   GET /billing/rates   — public rate card (no auth required)
//!   GET /billing/balance — pre-paid credit balance (placeholder)
//!
//! All stateful handlers receive `Arc<AppState>` from the combined server
//! and extract `meter` for usage lookups via the `HasMeter` trait.

use std::sync::Arc;

use axum::extract::State;
use axum::http::{HeaderMap, StatusCode};
use axum::response::IntoResponse;
use axum::Json;
use serde_json::json;
use tracing::info;

use crate::metering::StationMeter;
use crate::pricing;

/// Trait for any state type that provides access to the metering engine.
pub trait HasMeter {
    fn meter(&self) -> &Arc<StationMeter>;
}

/// GET /billing/usage — requires Bearer auth, returns usage for the caller's key prefix.
pub async fn handle_usage<S: HasMeter>(
    State(state): State<Arc<S>>,
    headers: HeaderMap,
) -> impl IntoResponse {
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

    let usage = state.meter().get_usage(&client_id);

    match usage {
        Some(u) => {
            let total_tokens = u.total_input_tokens + u.total_output_tokens;
            let cost_usd = u.total_cost_microcents as f64 / 100_000_000.0;
            (StatusCode::OK, Json(json!({
                "client_id": client_id,
                "period": u.period,
                "input_tokens": u.total_input_tokens,
                "output_tokens": u.total_output_tokens,
                "total_tokens": total_tokens,
                "tool_calls": u.total_tool_calls,
                "cost_microcents": u.total_cost_microcents,
                "cost_usd": format!("${:.4}", cost_usd),
                "harness_markup_pct": pricing::harness_markup_pct(),
                "tool_breakdown": u.tool_breakdown,
                "status": "active"
            }))).into_response()
        }
        None => {
            (StatusCode::OK, Json(json!({
                "client_id": client_id,
                "period": "current",
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "tool_calls": 0,
                "cost_microcents": 0,
                "cost_usd": "$0.0000",
                "harness_markup_pct": pricing::harness_markup_pct(),
                "tool_breakdown": {},
                "status": "active",
                "message": "No usage recorded yet for this key."
            }))).into_response()
        }
    }
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
pub async fn handle_balance<S: HasMeter>(
    State(state): State<Arc<S>>,
    headers: HeaderMap,
) -> impl IntoResponse {
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

    let usage = state.meter().get_usage(&client_id);
    let accrued = usage.map(|u| u.total_cost_microcents).unwrap_or(0);
    let accrued_usd = accrued as f64 / 100_000_000.0;

    (StatusCode::OK, Json(json!({
        "client_id": client_id,
        "accrued_cost_microcents": accrued,
        "accrued_cost_usd": format!("${:.4}", accrued_usd),
        "balance_microcents": 0,
        "balance_usd": "$0.00",
        "status": "metering",
        "message": "Usage is being metered. Payment integration coming soon."
    }))).into_response()
}
