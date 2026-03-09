//! NexVigilant Compute Engine — Rust-native computation tools.
//!
//! Pure functions: no network, no state, no side effects.
//! Every tool takes JSON arguments, returns JSON results.
//!
//! Domains:
//!   - `epidemiology` — RR, OR, AR, NNH, AF, PAF, IR, prevalence, KM, SMR, MH
//!   - `signals`      — PRR, ROR, IC, EBGM, disproportionality table
//!   - `causality`    — Naranjo, WHO-UMC
//!   - `statistics`   — CI, p-value, z-test, chi-square
//!   - `pharmacology` — PK (AUC, clearance, half-life, Michaelis-Menten, steady state)
//!   - `chemistry`    — Hill, Arrhenius, decay, equilibrium, saturation, threshold
//!   - `vigilance`    — safety margin d(s), risk score, harm types A-H, ToV level mapping

pub mod causality;
pub mod chemistry;
pub mod epidemiology;
pub mod pharmacology;
pub mod signals;
pub mod statistics;
pub mod vigilance;

use serde_json::Value;
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

/// Try to handle a tool call as a native computation.
/// Returns `Some(ToolCallResult)` if handled, `None` to fall through.
pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    // Each domain registers its prefix.
    // Tool names arrive as: compute_nexvigilant_com_<bare_name>
    let bare = tool_name
        .strip_prefix("compute_nexvigilant_com_")?
        .replace('_', "-");

    let result = epidemiology::handle(&bare, args)
        .or_else(|| signals::handle(&bare, args))
        .or_else(|| causality::handle(&bare, args))
        .or_else(|| statistics::handle(&bare, args))
        .or_else(|| pharmacology::handle(&bare, args))
        .or_else(|| chemistry::handle(&bare, args))
        .or_else(|| vigilance::handle(&bare, args))?;

    info!(tool = tool_name, "Handled natively (compute engine)");

    Some(ToolCallResult {
        content: vec![ContentBlock::Text {
            text: serde_json::to_string_pretty(&result).unwrap_or_default(),
        }],
        is_error: if result.get("status").and_then(|s| s.as_str()) == Some("error") {
            Some(true)
        } else {
            None
        },
    })
}
