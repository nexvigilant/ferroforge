use anyhow::Result;
use clap::{Parser, ValueEnum};
use std::path::PathBuf;
use tokio::sync::broadcast;
use tracing::info;

use nexvigilant_station::config::ConfigRegistry;
use nexvigilant_station::protocol::StationEvent;
use nexvigilant_station::{server, server_http, server_sse};
use nexvigilant_station::telemetry::StationTelemetry;

#[derive(Clone, ValueEnum)]
enum Transport {
    /// JSON-RPC over stdin/stdout (default, for Claude Code)
    Stdio,
    /// Server-Sent Events (Highway — for mcp-remote clients)
    Sse,
    /// HTTP REST + JSON-RPC (Skyway — for any agent framework)
    Http,
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
}

fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .init();

    let cli = Cli::parse();

    info!(
        config_dir = %cli.config_dir.display(),
        "NexVigilant Station starting"
    );

    let registry = ConfigRegistry::load_from_dir(&cli.config_dir)?;
    let telemetry = StationTelemetry::new(Some(cli.telemetry_log));

    info!(
        configs = registry.configs.len(),
        tools = registry.tool_count(),
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
    }
}
