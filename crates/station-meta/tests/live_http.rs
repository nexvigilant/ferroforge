//! Live integration test for `HttpStationClient` — exercises the real
//! https://mcp.nexvigilant.com/rpc endpoint.
//!
//! Gated behind `STATION_META_LIVE=1` to avoid CI flakes when the network
//! or Cloud Run is unavailable. Run with:
//!
//! ```bash
//! STATION_META_LIVE=1 cargo test -p station-meta --features http \
//!     --test live_http -- --nocapture
//! ```

#![cfg(feature = "http")]

use station_meta::{ExecutionRequest, HttpStationClient, StationClient};

fn gated() -> bool {
    std::env::var("STATION_META_LIVE").as_deref() == Ok("1")
}

#[test]
fn faers_search_adverse_events_returns_real_data() {
    if !gated() {
        eprintln!("skip — set STATION_META_LIVE=1 to run");
        return;
    }
    let client = HttpStationClient::default_prod();
    let req = ExecutionRequest {
        config: "api.fda.gov".to_string(),
        tool: "search-adverse-events".to_string(),
        params: serde_json::json!({"drug_name": "metformin", "limit": 1}),
    };
    let out = client.call(&req).expect("transport ok");
    assert!(
        out.is_ok(),
        "expected ok status, got error: {:?}",
        out.error
    );
    let result = out.result.expect("result payload");
    // Shape-level assertions — not asserting specific counts because FAERS data
    // changes across quarterly updates.
    let count = result.get("count").and_then(|v| v.as_u64()).unwrap_or(0);
    assert!(count >= 1, "expected at least 1 result, got {count}");
    let total = result
        .get("total_matching")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    assert!(
        total > 100_000,
        "metformin should have >100k FAERS reports, got {total}"
    );
    eprintln!(
        "LIVE: count={count}, total_matching={total}, status={:?}",
        result.get("status")
    );
}

#[test]
fn tool_name_underscore_form_also_works() {
    // Station accepts both dashed and underscored tool names (my earlier
    // stdio smoke test proved it). HttpStationClient normalises to underscored
    // MCP form internally, so both inputs must reach the same endpoint.
    if !gated() {
        return;
    }
    let client = HttpStationClient::default_prod();
    let req = ExecutionRequest {
        config: "api.fda.gov".to_string(),
        tool: "search_adverse_events".to_string(),
        params: serde_json::json!({"drug_name": "aspirin", "limit": 1}),
    };
    let out = client.call(&req).expect("transport ok");
    assert!(out.is_ok(), "underscored tool name must also work");
}

#[test]
fn unknown_tool_returns_error_not_panic() {
    if !gated() {
        return;
    }
    let client = HttpStationClient::default_prod();
    let req = ExecutionRequest {
        config: "api.fda.gov".to_string(),
        tool: "nonexistent_tool_xyz".to_string(),
        params: serde_json::json!({}),
    };
    let out = client.call(&req).expect("transport ok");
    // The real Station may return an error envelope OR an isError result;
    // either way the client must surface it as ExecutionResult::error, not
    // panic or silently succeed.
    assert!(
        !out.is_ok(),
        "expected error for unknown tool, got ok: {:?}",
        out.result
    );
}
