use anyhow::Result;
use clap::{Parser, ValueEnum};
use std::path::PathBuf;
use tokio::sync::broadcast;
use tracing::{info, warn};

use nexvigilant_station::config::ConfigRegistry;
use nexvigilant_station::protocol::StationEvent;
use nexvigilant_station::{server, server_combined, server_http, server_sse};
use nexvigilant_station::telemetry::StationTelemetry;

#[derive(Clone, ValueEnum)]
enum Transport {
    /// JSON-RPC over stdin/stdout (default, for Claude Code)
    Stdio,
    /// Server-Sent Events (Highway — for mcp-remote clients)
    Sse,
    /// HTTP REST + JSON-RPC (Skyway — for any agent framework)
    Http,
    /// Combined SSE + HTTP on one port (for Cloud Run / NexVigilant domain)
    Combined,
}

#[derive(Parser)]
#[command(name = "nexvigilant-station")]
#[command(about = "NexVigilant Station — MCP server for PV agent traffic routing")]
struct Cli {
    /// Path to configs directory
    #[arg(short, long, default_value = "configs")]
    config_dir: PathBuf,

    /// Path to telemetry JSONL log file
    #[arg(long, default_value = "station-telemetry.jsonl")]
    telemetry_log: PathBuf,

    /// Transport layer: stdio (local), sse (mcp-remote), http (REST API)
    #[arg(short, long, value_enum, default_value = "stdio")]
    transport: Transport,

    /// Host to bind for SSE/HTTP transports
    #[arg(long, default_value = "0.0.0.0")]
    host: String,

    /// Port to bind for SSE/HTTP transports
    #[arg(short, long, default_value = "3040")]
    port: u16,

    /// Exclude configs marked as private (for public deployments)
    #[arg(long, default_value = "false")]
    exclude_private: bool,
}

fn main() -> Result<()> {
    // Panic handler — convert panics from silent crashes to diagnosable log entries.
    // Without this, a panic in any handler kills the process and Cloud Run sees
    // only "connection reset". With it, the panic location is logged before exit.
    let default_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let location = info.location().map(|l| format!("{}:{}:{}", l.file(), l.line(), l.column()));
        let payload = if let Some(s) = info.payload().downcast_ref::<&str>() {
            s.to_string()
        } else if let Some(s) = info.payload().downcast_ref::<String>() {
            s.clone()
        } else {
            "unknown panic payload".to_string()
        };
        // Use eprintln directly — tracing may not be initialized or may be poisoned
        eprintln!("STATION PANIC at {}: {}", location.as_deref().unwrap_or("unknown"), payload);
        default_hook(info);
    }));

    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .init();

    let cli = Cli::parse();

    info!(
        config_dir = %cli.config_dir.display(),
        "NexVigilant Station starting"
    );

    let registry = ConfigRegistry::load_from_dir_filtered(&cli.config_dir, cli.exclude_private)?;
    let telemetry = if matches!(cli.transport, Transport::Stdio) {
        StationTelemetry::new_local(Some(cli.telemetry_log))
    } else {
        StationTelemetry::new(Some(cli.telemetry_log))
    };

    // Validate course tool references against the registry
    let missing = nexvigilant_station::science::validate_courses(&registry);
    if !missing.is_empty() {
        for (course, tool) in &missing {
            warn!(course, tool, "Course references nonexistent tool");
        }
        anyhow::bail!(
            "Course validation failed: {} tool references do not resolve",
            missing.len()
        );
    }

    // Initialize persistent dispatch daemon for ~14x faster proxy calls.
    // The daemon keeps dispatch_daemon.py alive with pre-warmed nexcore pool.
    nexvigilant_station::router::init_dispatch_daemon(&registry.station_root);

    info!(
        configs = registry.configs.len(),
        tools = registry.tool_count(),
        courses = nexvigilant_station::science::course_count(),
        version = env!("CARGO_PKG_VERSION"),
        git_sha = env!("GIT_SHA"),
        "Station ready"
    );

    // Event broadcast channel — capacity 256, best-effort delivery
    let (event_tx, _) = broadcast::channel::<StationEvent>(256);

    match cli.transport {
        Transport::Stdio => {
            info!("Transport: stdio (Station)");
            server::run_stdio(registry, &telemetry)
        }
        Transport::Sse => {
            info!(host = %cli.host, port = cli.port, "Transport: SSE (Highway)");
            let rt = tokio::runtime::Runtime::new()?;
            rt.block_on(server_sse::run_sse(registry, telemetry, event_tx, &cli.host, cli.port))
        }
        Transport::Http => {
            info!(host = %cli.host, port = cli.port, "Transport: HTTP (Skyway)");
            let rt = tokio::runtime::Runtime::new()?;
            rt.block_on(server_http::run_http(registry, telemetry, event_tx, &cli.host, cli.port))
        }
        Transport::Combined => {
            info!(host = %cli.host, port = cli.port, "Transport: Combined (SSE + HTTP)");
            let rt = tokio::runtime::Runtime::new()?;
            rt.block_on(server_combined::run_combined(registry, telemetry, event_tx, &cli.host, cli.port))
        }
    }
}
