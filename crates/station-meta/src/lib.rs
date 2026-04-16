//! # station-meta
//!
//! One MCP tool instead of ~2,964. The meta-tool accepts a `mode` discriminant
//! plus routing fields, and delegates to either **discovery** (semantic search
//! over local config JSON) or **execution** (JSON-RPC proxy to the existing
//! Cloud Run endpoint at `mcp.nexvigilant.com`).
//!
//! ## Why this exists
//!
//! The Claude Code prompt advertises every deferred tool by name. 2,964 Station
//! tool names cost ~80–100k tokens at session start — pure `WasteClass::HeatLoss`
//! in `nexcore-energy` vocabulary. This crate collapses that surface to **one
//! advertised tool**: `station(mode, ...)`.
//!
//! ## Conservation
//!
//! - `∂` (boundary): tool advertisement moves from prompt → on-demand call.
//! - `ς` (state): no state mutation in discovery; execute is stateless proxy.
//! - `∃` (existence): tools remain reachable — via `discover` then `execute`.

#![forbid(unsafe_code)]
#![deny(clippy::unwrap_used)]
#![deny(clippy::expect_used)]
#![deny(clippy::panic)]
#![warn(missing_docs)]

pub mod discover;
pub mod execute;
pub mod mcp_naming;
pub mod meta;

/// HTTP transport for [`StationClient`] — feature-gated on `http`.
#[cfg(feature = "http")]
pub mod http_client;

pub use discover::{
    ConfigIndex, IdfRanker, JaccardRanker, Ranker, ToolCandidate, discover, discover_with,
};
pub use execute::{ExecutionRequest, ExecutionResult, StationClient, execute};
pub use mcp_naming::build_mcp_tool_name;
pub use meta::{MetaRequest, MetaResponse, dispatch};

#[cfg(feature = "http")]
pub use http_client::{DEFAULT_BASE_URL as HTTP_DEFAULT_BASE_URL, DEFAULT_TIMEOUT as HTTP_DEFAULT_TIMEOUT, HttpStationClient};

/// Default Station Cloud Run endpoint.
pub const DEFAULT_STATION_URL: &str = "https://mcp.nexvigilant.com";

/// Default number of tool candidates returned by discovery.
pub const DEFAULT_DISCOVER_LIMIT: usize = 5;
