//! Shared helpers for the Station MCP tool-name contract.
//!
//! Station advertises each tool with a flat MCP name derived from its config
//! domain + tool name. Both transports (local router and HTTP) must produce
//! identical names or they address different tools. This module is the
//! single source of truth.
//!
//! Naming rule (verified against live configs 2026-04-16):
//!
//! ```text
//! mcp_name = replace(domain, '.' -> '_', '-' -> '_')
//!          + '_'
//!          + replace(tool,   '-' -> '_')
//! ```
//!
//! Examples:
//! - `api.fda.gov` + `search-adverse-events` → `api_fda_gov_search_adverse_events`
//! - `openfda.nexvigilant.com` + `openfda-drug-events` → `openfda_nexvigilant_com_openfda_drug_events`
//! - `api_fda_gov` + `search_adverse_events` → `api_fda_gov_search_adverse_events` (idempotent)

/// Build the flat MCP tool name Station uses for dispatch.
///
/// Accepts the domain (with dots) and tool name (with dashes or underscores).
/// Produces the canonical underscored form Station advertises in `tools/list`.
#[must_use]
pub fn build_mcp_tool_name(config_domain: &str, tool: &str) -> String {
    format!(
        "{}_{}",
        config_domain.replace('.', "_").replace('-', "_"),
        tool.replace('-', "_")
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn flattens_dotted_domain_and_dashed_tool() {
        assert_eq!(
            build_mcp_tool_name("api.fda.gov", "search-adverse-events"),
            "api_fda_gov_search_adverse_events"
        );
    }

    #[test]
    fn handles_subdomain_with_multiple_dots() {
        assert_eq!(
            build_mcp_tool_name("openfda.nexvigilant.com", "openfda-drug-events"),
            "openfda_nexvigilant_com_openfda_drug_events"
        );
    }

    #[test]
    fn idempotent_on_already_underscored_inputs() {
        assert_eq!(
            build_mcp_tool_name("api_fda_gov", "search_adverse_events"),
            "api_fda_gov_search_adverse_events"
        );
    }

    #[test]
    fn handles_domain_with_dashes() {
        // Some configs use hyphenated domain names (e.g. fda-accessdata.com).
        assert_eq!(
            build_mcp_tool_name("fda-accessdata.com", "search"),
            "fda_accessdata_com_search"
        );
    }

    #[test]
    fn empty_domain_produces_leading_underscore() {
        // Edge case: not valid input but shouldn't panic.
        assert_eq!(build_mcp_tool_name("", "tool"), "_tool");
    }
}
