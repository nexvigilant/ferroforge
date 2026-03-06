use anyhow::Result;
use clap::Parser;
use std::path::PathBuf;
use tracing::info;

use nexvigilant_station::config::ConfigRegistry;
use nexvigilant_station::server;

#[derive(Parser)]
#[command(name = "nexvigilant-station")]
#[command(about = "NexVigilant Station — MCP server hub for agent traffic routing")]
struct Cli {
    /// Path to configs directory
    #[arg(short, long, default_value = "configs")]
    config_dir: PathBuf,
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

    info!(
        configs = registry.configs.len(),
        tools = registry.tool_count(),
        "Station ready — entering MCP stdio loop"
    );

    server::run_stdio(registry)
}
