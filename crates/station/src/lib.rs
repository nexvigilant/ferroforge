/// Headers that disable response buffering for SSE streams.
/// Cloud Run and reverse proxies (nginx) buffer by default, which
/// prevents SSE events from streaming incrementally to the client.
pub const SSE_STREAM_HEADERS: [(&str, &str); 2] = [
    ("X-Accel-Buffering", "no"),
    ("Cache-Control", "no-cache, no-transform"),
];

pub mod auth;
pub mod compute;
pub mod config;
pub mod benefit_risk;
pub mod crystalbook;
pub mod metering;
pub mod pricing;
pub mod protocol;
pub mod rate_limit;
pub mod router;
pub mod science;
pub mod server;
pub mod server_combined;
pub mod server_http;
pub mod server_sse;
pub mod server_streamable;
pub mod telemetry;
pub mod usage_store;

/// Shutdown signal — resolves on SIGTERM (Cloud Run) or CTRL+C (local dev).
///
/// Cloud Run sends SIGTERM with a 10s grace period. This handler lets axum
/// finish in-flight requests before the process exits, instead of force-killing.
pub async fn shutdown_signal() {
    use tracing::info;

    let ctrl_c = tokio::signal::ctrl_c();

    #[cfg(unix)]
    {
        let mut sigterm = tokio::signal::unix::signal(
            tokio::signal::unix::SignalKind::terminate(),
        )
        .expect("failed to install SIGTERM handler");

        tokio::select! {
            _ = ctrl_c => info!("CTRL+C received, shutting down"),
            _ = sigterm.recv() => info!("SIGTERM received, shutting down"),
        }
    }

    #[cfg(not(unix))]
    {
        ctrl_c.await.expect("failed to listen for CTRL+C");
        info!("CTRL+C received, shutting down");
    }
}
