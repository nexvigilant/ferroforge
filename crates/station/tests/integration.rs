use nexvigilant_station::auth::{ApiKeyGate, AuthResult};
use nexvigilant_station::config::{ConfigRegistry, HubConfig, ParamDef, ToolDef};
use nexvigilant_station::protocol::{JsonRpcRequest, INVALID_PARAMS, METHOD_NOT_FOUND};
use nexvigilant_station::router;
use nexvigilant_station::server;
use nexvigilant_station::telemetry::{self, StationTelemetry};
use serde_json::{json, Value};
use std::io::Write;
use tempfile::TempDir;

fn test_telemetry() -> StationTelemetry {
    StationTelemetry::new(None)
}

// --- Helper: build a test registry from inline configs ---

fn test_registry() -> ConfigRegistry {
    ConfigRegistry {
        station_root: "/tmp".into(),
        configs: vec![
            HubConfig {
                domain: "api.fda.gov".into(),
                url_pattern: Some("/drug/event*".into()),
                title: "openFDA FAERS".into(),
                description: Some("Test config".into()),
                proxy: None,
                private: false,
                copyright: None,
                tools: vec![
                    ToolDef {
                        name: "search-adverse-events".into(),
                        description: "Search FAERS".into(),
                        parameters: vec![ParamDef {
                            name: "drug_name".into(),
                            param_type: "string".into(),
                            description: Some("Drug name".into()),
                            required: true,
                        }],
                        stub_response: Some(r#"{"status":"ok","events":42}"#.into()),
                        proxy: None,
                        output_schema: None,
                        annotations: None,
                    },
                    ToolDef {
                        name: "get-drug-counts".into(),
                        description: "Get counts".into(),
                        parameters: vec![],
                        stub_response: None,
                        proxy: None,
                        output_schema: None,
                        annotations: None,
                    },
                ],
            },
            HubConfig {
                domain: "dailymed.nlm.nih.gov".into(),
                url_pattern: None,
                title: "DailyMed".into(),
                description: None,
                proxy: None,
                private: false,
                copyright: None,
                tools: vec![ToolDef {
                    name: "get-drug-label".into(),
                    description: "Get label".into(),
                    parameters: vec![],
                    stub_response: Some(r#"{"label":"test"}"#.into()),
                    proxy: None,
                    output_schema: None,
                    annotations: None,
                }],
            },
        ],
    }
}

fn make_request(id: Option<Value>, method: &str, params: Option<Value>) -> JsonRpcRequest {
    JsonRpcRequest {
        jsonrpc: "2.0".into(),
        id,
        method: method.into(),
        params,
    }
}

// =============================================
// Phase 0: Protocol Types (Preclinical)
// =============================================

#[test]
fn test_jsonrpc_request_deserialization() {
    let raw = r#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}"#;
    let req: JsonRpcRequest = serde_json::from_str(raw).expect("should parse");
    assert_eq!(req.method, "initialize");
    assert_eq!(req.id, Some(json!(1)));
}

#[test]
fn test_jsonrpc_request_without_params() {
    let raw = r#"{"jsonrpc":"2.0","id":2,"method":"tools/list"}"#;
    let req: JsonRpcRequest = serde_json::from_str(raw).expect("should parse");
    assert_eq!(req.method, "tools/list");
    assert!(req.params.is_none());
}

#[test]
fn test_jsonrpc_request_notification_no_id() {
    let raw = r#"{"jsonrpc":"2.0","method":"notifications/initialized"}"#;
    let req: JsonRpcRequest = serde_json::from_str(raw).expect("should parse");
    assert!(req.id.is_none());
}

// =============================================
// Phase 0: Config Registry
// =============================================

#[test]
fn test_registry_tool_count() {
    let reg = test_registry();
    // 3 config tools + 6 meta tools (chart_course, directory, capabilities, station_health, ring_health, forge_diagnose)
    assert_eq!(reg.tool_count(), 9);
}

#[test]
fn test_registry_tool_infos_includes_meta_tools() {
    let reg = test_registry();
    let infos = reg.tool_infos();
    // 3 config tools + 6 meta tools (chart_course + directory + capabilities + station_health + ring_health + forge_diagnose)
    assert_eq!(infos.len(), 9);
    assert!(infos.iter().any(|t| t.name == "nexvigilant_directory"));
    assert!(infos.iter().any(|t| t.name == "nexvigilant_capabilities"));
    assert!(infos.iter().any(|t| t.name == "nexvigilant_station_health"));
    assert!(infos.iter().any(|t| t.name == "nexvigilant_ring_health"));
}

#[test]
fn test_registry_tool_name_prefixing() {
    let reg = test_registry();
    let infos = reg.tool_infos();
    let names: Vec<&str> = infos.iter().map(|t| t.name.as_str()).collect();
    assert!(names.contains(&"api_fda_gov_search_adverse_events"));
    assert!(names.contains(&"api_fda_gov_get_drug_counts"));
    assert!(names.contains(&"dailymed_nlm_nih_gov_get_drug_label"));
}

#[test]
fn test_registry_tool_description_has_domain() {
    let reg = test_registry();
    let infos = reg.tool_infos();
    for info in &infos {
        assert!(
            info.description.starts_with('['),
            "description should start with [domain] or [NexVigilant]: {}",
            info.description
        );
    }
}

#[test]
fn test_registry_tool_schema_has_required() {
    let reg = test_registry();
    let infos = reg.tool_infos();
    let faers = infos.iter().find(|t| t.name.contains("search_adverse")).expect("should find FAERS tool");
    let required = faers.input_schema.get("required").expect("should have required");
    let arr = required.as_array().expect("required should be array");
    assert_eq!(arr.len(), 1);
    assert_eq!(arr[0], "drug_name");
}

#[test]
fn test_find_tool_by_prefixed_name() {
    let reg = test_registry();
    let result = reg.find_tool("api_fda_gov_search_adverse_events");
    assert!(result.is_some());
    let (config, tool) = result.expect("found");
    assert_eq!(config.domain, "api.fda.gov");
    assert_eq!(tool.name, "search-adverse-events");
}

#[test]
fn test_find_tool_unknown_returns_none() {
    let reg = test_registry();
    assert!(reg.find_tool("nonexistent_tool").is_none());
}

#[test]
fn test_find_tool_cross_domain() {
    let reg = test_registry();
    let result = reg.find_tool("dailymed_nlm_nih_gov_get_drug_label");
    assert!(result.is_some());
    let (config, _) = result.expect("found");
    assert_eq!(config.domain, "dailymed.nlm.nih.gov");
}

// =============================================
// Phase 0: Config Loading from Disk
// =============================================

#[test]
fn test_load_from_empty_dir() {
    let dir = TempDir::new().expect("tmpdir");
    let reg = ConfigRegistry::load_from_dir(dir.path()).expect("should load");
    assert_eq!(reg.configs.len(), 0);
    // 0 config tools + 6 meta tools
    assert_eq!(reg.tool_count(), 6);
}

#[test]
fn test_load_from_nonexistent_dir() {
    let reg = ConfigRegistry::load_from_dir(std::path::Path::new("/tmp/nonexistent_ctvp_test_dir"))
        .expect("should handle missing dir");
    assert_eq!(reg.configs.len(), 0);
}

#[test]
fn test_load_json_config() {
    let dir = TempDir::new().expect("tmpdir");
    let config_path = dir.path().join("test.json");
    let mut f = std::fs::File::create(&config_path).expect("create");
    write!(f, r#"{{"domain":"test.com","title":"Test","tools":[{{"name":"ping","description":"Ping"}}]}}"#).expect("write");

    let reg = ConfigRegistry::load_from_dir(dir.path()).expect("should load");
    assert_eq!(reg.configs.len(), 1);
    assert_eq!(reg.configs[0].domain, "test.com");
    // 1 config tool + 6 meta tools
    assert_eq!(reg.tool_count(), 7);
}

#[test]
fn test_load_ignores_non_config_files() {
    let dir = TempDir::new().expect("tmpdir");
    std::fs::write(dir.path().join("readme.md"), "# Not a config").expect("write");
    std::fs::write(dir.path().join("notes.txt"), "not a config").expect("write");

    let reg = ConfigRegistry::load_from_dir(dir.path()).expect("should load");
    assert_eq!(reg.configs.len(), 0);
}

// =============================================
// Phase 0: Router
// =============================================

#[test]
fn test_route_known_tool_with_stub() {
    let reg = test_registry();
    let result = router::route_tool_call(&reg, &test_telemetry(), None, &ApiKeyGate::new(None), None, "api_fda_gov_search_adverse_events", &json!({"drug_name": "aspirin"}), None);
    assert!(result.is_error.is_none());
    assert_eq!(result.content.len(), 1);
}

#[test]
fn test_route_known_tool_without_stub() {
    let reg = test_registry();
    let result = router::route_tool_call(&reg, &test_telemetry(), None, &ApiKeyGate::new(None), None, "api_fda_gov_get_drug_counts", &json!({"drug_name": "metformin"}), None);
    assert!(result.is_error.is_none());
    let text = match &result.content[0] {
        nexvigilant_station::protocol::ContentBlock::Text { text } => text,
    };
    assert!(text.contains("no proxy or stub") || text.contains("no_handler"));
}

#[test]
fn test_route_unknown_tool() {
    let reg = test_registry();
    let result = router::route_tool_call(&reg, &test_telemetry(), None, &ApiKeyGate::new(None), None, "nonexistent_tool", &json!({}), None);
    assert_eq!(result.is_error, Some(true));
}

#[test]
fn test_route_directory_meta_tool() {
    let reg = test_registry();
    let result = router::route_tool_call(&reg, &test_telemetry(), None, &ApiKeyGate::new(None), None, "nexvigilant_directory", &json!({}), None);
    assert!(result.is_error.is_none());
    let text = match &result.content[0] {
        nexvigilant_station::protocol::ContentBlock::Text { text } => text,
    };
    let parsed: Value = serde_json::from_str(text).expect("should be JSON");
    assert_eq!(parsed["station"], "NexVigilant Station");
    assert_eq!(parsed["total_domains"], 2);
    assert_eq!(parsed["total_tools"], 9);
}

#[test]
fn test_route_capabilities_search() {
    let reg = test_registry();
    let result = router::route_tool_call(&reg, &test_telemetry(), None, &ApiKeyGate::new(None), None, "nexvigilant_capabilities", &json!({"query": "adverse"}), None);
    assert!(result.is_error.is_none());
    let text = match &result.content[0] {
        nexvigilant_station::protocol::ContentBlock::Text { text } => text,
    };
    let parsed: Value = serde_json::from_str(text).expect("should be JSON");
    assert!(parsed["matches"].as_u64().expect("count") >= 1);
}

#[test]
fn test_route_capabilities_domain_filter() {
    let reg = test_registry();
    let result = router::route_tool_call(&reg, &test_telemetry(), None, &ApiKeyGate::new(None), None, "nexvigilant_capabilities", &json!({"domain": "dailymed"}), None);
    assert!(result.is_error.is_none());
    let text = match &result.content[0] {
        nexvigilant_station::protocol::ContentBlock::Text { text } => text,
    };
    let parsed: Value = serde_json::from_str(text).expect("should be JSON");
    assert_eq!(parsed["matches"], 1);
}

// =============================================
// Request ID Propagation
// =============================================

#[test]
fn test_route_injects_request_id_in_stub_response() {
    let reg = test_registry();
    let result = router::route_tool_call(
        &reg, &test_telemetry(), None, &ApiKeyGate::new(None), None,
        "api_fda_gov_search_adverse_events", &json!({"drug_name": "aspirin"}), None,
    );
    let text = match &result.content[0] {
        nexvigilant_station::protocol::ContentBlock::Text { text } => text,
    };
    let parsed: Value = serde_json::from_str(text).expect("stub should be JSON");
    let rid = parsed["_request_id"].as_str().expect("should have _request_id");
    // UUID v4 format: 8-4-4-4-12 hex chars
    assert_eq!(rid.len(), 36, "request_id should be UUID format");
    assert_eq!(rid.matches('-').count(), 4);
}

#[test]
fn test_route_injects_request_id_in_meta_tool() {
    let reg = test_registry();
    let result = router::route_tool_call(
        &reg, &test_telemetry(), None, &ApiKeyGate::new(None), None,
        "nexvigilant_directory", &json!({}), None,
    );
    let text = match &result.content[0] {
        nexvigilant_station::protocol::ContentBlock::Text { text } => text,
    };
    let parsed: Value = serde_json::from_str(text).expect("should be JSON");
    assert!(parsed["_request_id"].as_str().is_some(), "meta-tools should get request_id");
}

#[test]
fn test_route_request_id_recorded_in_telemetry() {
    let reg = test_registry();
    let telemetry = test_telemetry();
    let _ = router::route_tool_call(
        &reg, &telemetry, None, &ApiKeyGate::new(None), None,
        "api_fda_gov_search_adverse_events", &json!({"drug_name": "test"}), None,
    );
    let health = telemetry.health();
    assert!(!health.recent_calls.is_empty());
    let last = &health.recent_calls[0];
    assert!(last.request_id.is_some(), "telemetry should record request_id");
}

#[test]
fn test_route_unique_request_ids() {
    let reg = test_registry();
    let telemetry = test_telemetry();
    let _ = router::route_tool_call(
        &reg, &telemetry, None, &ApiKeyGate::new(None), None,
        "api_fda_gov_search_adverse_events", &json!({"drug_name": "a"}), None,
    );
    let _ = router::route_tool_call(
        &reg, &telemetry, None, &ApiKeyGate::new(None), None,
        "api_fda_gov_search_adverse_events", &json!({"drug_name": "b"}), None,
    );
    let health = telemetry.health();
    let ids: Vec<&str> = health.recent_calls.iter()
        .filter_map(|c| c.request_id.as_deref())
        .collect();
    assert_eq!(ids.len(), 2);
    assert_ne!(ids[0], ids[1], "each call should get a unique request_id");
}

// =============================================
// Phase 0: MCP Server Handler
// =============================================

#[test]
fn test_handle_initialize() {
    let reg = test_registry();
    let req = make_request(Some(json!(1)), "initialize", Some(json!({})));
    let resp = server::handle_request(&reg, &test_telemetry(), None, &ApiKeyGate::new(None), &req, None, None).expect("should respond");
    let result = resp.result.expect("should have result");
    assert_eq!(result["protocolVersion"], "2025-03-26");
    assert_eq!(result["serverInfo"]["name"], "nexvigilant-station");
    assert!(resp.error.is_none());
}

#[test]
fn test_handle_tools_list() {
    let reg = test_registry();
    let req = make_request(Some(json!(2)), "tools/list", None);
    let resp = server::handle_request(&reg, &test_telemetry(), None, &ApiKeyGate::new(None), &req, None, None).expect("should respond");
    let result = resp.result.expect("should have result");
    let tools = result["tools"].as_array().expect("tools array");
    // 3 config tools + 6 meta tools (chart_course, directory, capabilities, station_health, ring_health, forge_diagnose)
    assert_eq!(tools.len(), 9);
}

#[test]
fn test_handle_tools_call_with_stub() {
    let reg = test_registry();
    let req = make_request(
        Some(json!(3)),
        "tools/call",
        Some(json!({
            "name": "api_fda_gov_search_adverse_events",
            "arguments": {"drug_name": "aspirin"}
        })),
    );
    let resp = server::handle_request(&reg, &test_telemetry(), None, &ApiKeyGate::new(None), &req, None, None).expect("should respond");
    let result = resp.result.expect("should have result");
    let content = result["content"].as_array().expect("content");
    assert_eq!(content.len(), 1);
    assert!(content[0]["text"].as_str().expect("text").contains("ok"));
}

#[test]
fn test_handle_tools_call_missing_name() {
    let reg = test_registry();
    let req = make_request(Some(json!(4)), "tools/call", Some(json!({"arguments": {}})));
    let resp = server::handle_request(&reg, &test_telemetry(), None, &ApiKeyGate::new(None), &req, None, None).expect("should respond");
    let err = resp.error.expect("should have error");
    assert_eq!(err.code, INVALID_PARAMS);
}

#[test]
fn test_handle_ping() {
    let reg = test_registry();
    let req = make_request(Some(json!(5)), "ping", None);
    let resp = server::handle_request(&reg, &test_telemetry(), None, &ApiKeyGate::new(None), &req, None, None).expect("should respond");
    assert!(resp.result.is_some());
    assert!(resp.error.is_none());
}

#[test]
fn test_handle_unknown_method() {
    let reg = test_registry();
    let req = make_request(Some(json!(6)), "bogus/method", None);
    let resp = server::handle_request(&reg, &test_telemetry(), None, &ApiKeyGate::new(None), &req, None, None).expect("should respond");
    let err = resp.error.expect("should have error");
    assert_eq!(err.code, METHOD_NOT_FOUND);
}

#[test]
fn test_handle_notification_returns_none() {
    let reg = test_registry();
    let req = make_request(None, "notifications/initialized", None);
    let resp = server::handle_request(&reg, &test_telemetry(), None, &ApiKeyGate::new(None), &req, None, None);
    assert!(resp.is_none(), "notifications should return None");
}

// =============================================
// Phase 0: End-to-End JSON roundtrip
// =============================================

#[test]
fn test_e2e_json_roundtrip_initialize() {
    let raw = r#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}"#;
    let req: JsonRpcRequest = serde_json::from_str(raw).expect("parse");
    let reg = test_registry();
    let resp = server::handle_request(&reg, &test_telemetry(), None, &ApiKeyGate::new(None), &req, None, None).expect("respond");
    let json_str = serde_json::to_string(&resp).expect("serialize");
    let reparsed: Value = serde_json::from_str(&json_str).expect("reparse");
    assert_eq!(reparsed["jsonrpc"], "2.0");
    assert_eq!(reparsed["id"], 1);
    assert!(reparsed["result"]["capabilities"]["tools"].is_object());
}

#[test]
fn test_e2e_json_roundtrip_tools_call() {
    let raw = r#"{"jsonrpc":"2.0","id":99,"method":"tools/call","params":{"name":"dailymed_nlm_nih_gov_get_drug_label","arguments":{"drug_name":"metformin"}}}"#;
    let req: JsonRpcRequest = serde_json::from_str(raw).expect("parse");
    let reg = test_registry();
    let resp = server::handle_request(&reg, &test_telemetry(), None, &ApiKeyGate::new(None), &req, None, None).expect("respond");
    let json_str = serde_json::to_string(&resp).expect("serialize");
    let reparsed: Value = serde_json::from_str(&json_str).expect("reparse");
    assert_eq!(reparsed["id"], 99);
    assert!(reparsed["result"]["content"][0]["text"].is_string());
}

// =============================================
// Phase 2: Real Config Loading (Efficacy)
// =============================================

#[test]
fn test_load_real_configs_directory() {
    let configs_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("crates/")
        .parent()
        .expect("root")
        .join("configs");

    if !configs_dir.exists() {
        return; // Skip if not in workspace context
    }

    let reg = ConfigRegistry::load_from_dir(&configs_dir).expect("should load real configs");
    assert!(reg.configs.len() >= 10, "expected 10+ configs, got {}", reg.configs.len());
    assert!(reg.tool_count() >= 50, "expected 50+ tools, got {}", reg.tool_count());

    // Every tool should have a valid prefixed name
    for info in reg.tool_infos() {
        assert!(!info.name.is_empty(), "tool name should not be empty");
        assert!(!info.description.is_empty(), "tool description should not be empty");
        assert!(info.input_schema.get("type").is_some(), "schema should have type");
    }
}

#[test]
fn test_real_configs_all_tools_routable() {
    let configs_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("crates/")
        .parent()
        .expect("root")
        .join("configs");

    if !configs_dir.exists() {
        return;
    }

    let reg = ConfigRegistry::load_from_dir(&configs_dir).expect("load");
    let infos = reg.tool_infos();

    for info in &infos {
        // Skip meta-tools — they're handled directly, not via find_tool
        if info.name.starts_with("nexvigilant_") {
            continue;
        }
        let found = reg.find_tool(&info.name);
        assert!(
            found.is_some(),
            "tool '{}' listed but not routable via find_tool",
            info.name
        );
    }
}

// =============================================
// Phase 3: Rate Limiting
// =============================================

// =============================================
// Phase 4: API Key Authentication
// =============================================

#[test]
fn test_auth_dev_mode_allows_all() {
    // No keys → dev mode → all tools allowed
    let gate = ApiKeyGate::new(None);
    assert!(!gate.is_enabled());
    assert!(matches!(gate.check(None, "some_tool"), AuthResult::Allowed));
    assert!(matches!(gate.check(Some("Bearer invalid"), "some_tool"), AuthResult::Allowed));
}

#[test]
fn test_auth_meta_tools_always_free() {
    let gate = ApiKeyGate::new(Some(vec!["nv_test123".into()]));
    assert!(gate.is_enabled());
    assert!(matches!(gate.check(None, "nexvigilant_directory"), AuthResult::Allowed));
    assert!(matches!(gate.check(None, "nexvigilant_capabilities"), AuthResult::Allowed));
    assert!(matches!(gate.check(None, "nexvigilant_chart_course"), AuthResult::Allowed));
}

#[test]
fn test_auth_valid_key_allowed() {
    let gate = ApiKeyGate::new(Some(vec!["nv_abc123".into(), "nv_def456".into()]));
    assert!(matches!(gate.check(Some("Bearer nv_abc123"), "some_tool"), AuthResult::Allowed));
    assert!(matches!(gate.check(Some("Bearer nv_def456"), "some_tool"), AuthResult::Allowed));
}

#[test]
fn test_auth_invalid_key_rejected() {
    let gate = ApiKeyGate::new(Some(vec!["nv_abc123".into()]));
    assert!(matches!(gate.check(Some("Bearer nv_wrong"), "some_tool"), AuthResult::InvalidKey));
}

#[test]
fn test_auth_no_key_rejected() {
    let gate = ApiKeyGate::new(Some(vec!["nv_abc123".into()]));
    assert!(matches!(gate.check(None, "some_tool"), AuthResult::KeyRequired));
    assert!(matches!(gate.check(Some("Bearer "), "some_tool"), AuthResult::KeyRequired));
}

#[test]
fn test_auth_check_rpc_extracts_tool_name() {
    let gate = ApiKeyGate::new(Some(vec!["nv_abc123".into()]));

    // Meta-tool via RPC → allowed without key
    let params = json!({"name": "nexvigilant_directory", "arguments": {}});
    assert!(matches!(gate.check_rpc(None, Some(&params)), AuthResult::Allowed));

    // Domain tool via RPC → requires key
    let params = json!({"name": "api_fda_gov_search_adverse_events", "arguments": {}});
    assert!(matches!(gate.check_rpc(None, Some(&params)), AuthResult::KeyRequired));

    // Domain tool via RPC with valid key → allowed
    assert!(matches!(gate.check_rpc(Some("Bearer nv_abc123"), Some(&params)), AuthResult::Allowed));
}

// =============================================
// Phase 3: Rate Limiting
// =============================================

#[test]
fn test_rate_limit_meta_tools_never_limited() {
    let telemetry = test_telemetry();
    let check = telemetry.check_rate_limit("nexvigilant.meta");
    assert!(check.allowed);
    assert_eq!(check.limit, 0); // 0 = unlimited
}

#[test]
fn test_rate_limit_science_never_limited() {
    let telemetry = test_telemetry();
    let check = telemetry.check_rate_limit("science.nexvigilant.com");
    assert!(check.allowed);
}

#[test]
fn test_rate_limit_allows_under_threshold() {
    let telemetry = test_telemetry();
    // Record a few calls for api.fda.gov (limit: 30/min)
    for _ in 0..5 {
        telemetry.record(nexvigilant_station::telemetry::ToolCallRecord {
            timestamp: nexvigilant_station::telemetry::now_iso8601(),
            tool_name: "api_fda_gov_search_adverse_events".into(),
            domain: "api.fda.gov".into(),
            duration_ms: 100,
            status: "ok".into(),
            is_error: false,
            error_message: None,
            client_id: None,
            request_id: None,
        });
    }
    let check = telemetry.check_rate_limit("api.fda.gov");
    assert!(check.allowed);
    assert_eq!(check.current_count, 5);
    assert_eq!(check.limit, 30);
}

#[test]
fn test_rate_limit_blocks_over_threshold() {
    let telemetry = test_telemetry();
    // Flood api.fda.gov past its 30/min limit
    for _ in 0..31 {
        telemetry.record(nexvigilant_station::telemetry::ToolCallRecord {
            timestamp: nexvigilant_station::telemetry::now_iso8601(),
            tool_name: "api_fda_gov_search_adverse_events".into(),
            domain: "api.fda.gov".into(),
            duration_ms: 10,
            status: "ok".into(),
            is_error: false,
            error_message: None,
            client_id: None,
            request_id: None,
        });
    }
    let check = telemetry.check_rate_limit("api.fda.gov");
    assert!(!check.allowed, "should be rate limited after 31 calls");
    assert_eq!(check.current_count, 31);
    assert!(check.retry_after_secs > 0);
}

#[test]
fn test_rate_limit_response_in_router() {
    let reg = test_registry();
    let telemetry = test_telemetry();
    // Flood past limit
    for _ in 0..31 {
        telemetry.record(nexvigilant_station::telemetry::ToolCallRecord {
            timestamp: nexvigilant_station::telemetry::now_iso8601(),
            tool_name: "api_fda_gov_search_adverse_events".into(),
            domain: "api.fda.gov".into(),
            duration_ms: 10,
            status: "ok".into(),
            is_error: false,
            error_message: None,
            client_id: None,
            request_id: None,
        });
    }
    // This call should be rate-limited
    let result = router::route_tool_call(&reg, &telemetry, None, &ApiKeyGate::new(None), None, "api_fda_gov_search_adverse_events", &json!({"drug_name": "test"}), None);
    assert_eq!(result.is_error, Some(true));
    let text = match &result.content[0] {
        nexvigilant_station::protocol::ContentBlock::Text { text } => text,
    };
    assert!(text.contains("rate_limited"));
}

// =============================================
// Telemetry date formatting validation
// =============================================

#[test]
fn test_now_iso8601_format() {
    let ts = telemetry::now_iso8601();
    // Should match YYYY-MM-DDTHH:MM:SSZ
    assert_eq!(ts.len(), 20, "ISO 8601 timestamp should be 20 chars: {ts}");
    assert!(ts.ends_with('Z'), "Should end with Z: {ts}");
    assert_eq!(&ts[4..5], "-");
    assert_eq!(&ts[7..8], "-");
    assert_eq!(&ts[10..11], "T");
    assert_eq!(&ts[13..14], ":");
    assert_eq!(&ts[16..17], ":");

    // Year should be reasonable (2020-2099)
    let year: u32 = ts[0..4].parse().expect("year should parse");
    assert!(year >= 2020 && year <= 2099, "Year out of range: {year}");

    // Month 01-12
    let month: u32 = ts[5..7].parse().expect("month should parse");
    assert!((1..=12).contains(&month), "Month out of range: {month}");

    // Day 01-31
    let day: u32 = ts[8..10].parse().expect("day should parse");
    assert!((1..=31).contains(&day), "Day out of range: {day}");
}

// --- Chart Course Tests ---

fn real_registry() -> ConfigRegistry {
    let configs_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("crates/")
        .parent()
        .expect("root")
        .join("configs");
    ConfigRegistry::load_from_dir(&configs_dir).expect("should load real configs")
}

#[test]
fn test_chart_course_lists_all_six_courses() {
    let registry = real_registry();
    let result = nexvigilant_station::science::try_handle(
        "nexvigilant_chart_course",
        &json!({}),
        &registry,
    );
    let result = result.expect("chart_course should be handled");
    let text = match &result.content[0] {
        nexvigilant_station::protocol::ContentBlock::Text { text } => text,
    };
    let parsed: Value = serde_json::from_str(text).expect("should be valid JSON");
    let courses = parsed["courses"].as_array().expect("courses should be array");
    assert_eq!(courses.len(), 6, "Expected 6 courses, got {}", courses.len());

    let names: Vec<&str> = courses.iter().map(|c| c["course"].as_str().unwrap()).collect();
    assert!(names.contains(&"drug-safety-profile"));
    assert!(names.contains(&"signal-investigation"));
    assert!(names.contains(&"causality-assessment"));
    assert!(names.contains(&"benefit-risk-assessment"));
    assert!(names.contains(&"regulatory-intelligence"));
    assert!(names.contains(&"competitive-landscape"));
}

#[test]
fn test_chart_course_returns_steps_for_specific_course() {
    let registry = real_registry();
    let result = nexvigilant_station::science::try_handle(
        "nexvigilant_chart_course",
        &json!({"course": "causality-assessment"}),
        &registry,
    );
    let result = result.expect("chart_course should be handled");
    let text = match &result.content[0] {
        nexvigilant_station::protocol::ContentBlock::Text { text } => text,
    };
    let parsed: Value = serde_json::from_str(text).expect("should be valid JSON");
    assert_eq!(parsed["status"], "ok");
    assert_eq!(parsed["step_count"], 4);
    let steps = parsed["steps"].as_array().expect("steps should be array");
    assert_eq!(steps.len(), 4);
    assert_eq!(steps[0]["tool"], "api_fda_gov_search_adverse_events");
    assert_eq!(steps[3]["tool"], "pubmed_ncbi_nlm_nih_gov_search_case_reports");
}

#[test]
fn test_chart_course_unknown_returns_error() {
    let registry = real_registry();
    let result = nexvigilant_station::science::try_handle(
        "nexvigilant_chart_course",
        &json!({"course": "nonexistent-course"}),
        &registry,
    );
    let result = result.expect("chart_course should be handled");
    assert_eq!(result.is_error, Some(true));
    let text = match &result.content[0] {
        nexvigilant_station::protocol::ContentBlock::Text { text } => text,
    };
    let parsed: Value = serde_json::from_str(text).expect("should be valid JSON");
    assert_eq!(parsed["status"], "error");
}

#[test]
fn test_chart_course_all_tool_names_exist_in_registry() {
    let registry = real_registry();
    // List all courses
    let result = nexvigilant_station::science::try_handle(
        "nexvigilant_chart_course",
        &json!({}),
        &registry,
    )
    .expect("chart_course should be handled");
    let text = match &result.content[0] {
        nexvigilant_station::protocol::ContentBlock::Text { text } => text,
    };
    let parsed: Value = serde_json::from_str(text).expect("should be valid JSON");
    let courses = parsed["courses"].as_array().expect("courses should be array");

    // Collect all MCP tool names from the registry
    let registry_tools: Vec<String> = registry
        .configs
        .iter()
        .flat_map(|c| {
            let domain_prefix = c.domain.replace('.', "_");
            c.tools.iter().map(move |t| {
                format!("{}_{}", domain_prefix, t.name.replace('-', "_"))
            })
        })
        .collect();

    // Verify every tool referenced in every course exists in the registry
    for course in courses {
        let course_name = course["course"].as_str().unwrap();
        let tools = course["tools"].as_array().expect("tools should be array");
        for tool in tools {
            let tool_name = tool.as_str().unwrap();
            assert!(
                registry_tools.contains(&tool_name.to_string()),
                "Course '{}' references tool '{}' which does not exist in the registry. \
                 Available tools with similar prefix: {:?}",
                course_name,
                tool_name,
                registry_tools
                    .iter()
                    .filter(|t: &&String| t.starts_with(&tool_name[..tool_name.len().min(15)]))
                    .take(5)
                    .collect::<Vec<_>>()
            );
        }
    }
}

#[test]
fn test_station_health_includes_courses() {
    let registry = real_registry();
    let telemetry = StationTelemetry::new_local(None);
    let result = router::route_tool_call(
        &registry,
        &telemetry,
        None,
        &ApiKeyGate::new(None),
        None,
        "nexvigilant_station_health",
        &json!({}),
        None,
    );
    let text = match &result.content[0] {
        nexvigilant_station::protocol::ContentBlock::Text { text } => text,
    };
    let parsed: Value = serde_json::from_str(text).expect("valid JSON");
    assert_eq!(
        parsed["courses"].as_u64(),
        Some(6),
        "station_health should report 6 courses"
    );
}

#[test]
fn test_directory_includes_courses() {
    let registry = real_registry();
    let telemetry = StationTelemetry::new_local(None);
    let result = router::route_tool_call(
        &registry,
        &telemetry,
        None,
        &ApiKeyGate::new(None),
        None,
        "nexvigilant_directory",
        &json!({}),
        None,
    );
    let text = match &result.content[0] {
        nexvigilant_station::protocol::ContentBlock::Text { text } => text,
    };
    let parsed: Value = serde_json::from_str(text).expect("valid JSON");
    assert_eq!(parsed["total_courses"].as_u64(), Some(6));
    let courses = parsed["courses"].as_array().expect("courses array");
    assert_eq!(courses.len(), 6, "directory should list all 6 courses");
}

#[test]
fn test_course_count_matches_summaries() {
    let count = nexvigilant_station::science::course_count();
    let summaries = nexvigilant_station::science::course_summaries();
    assert_eq!(count, summaries.len(), "course_count() and course_summaries() must agree");
    assert!(count >= 6, "should have at least 6 courses, got {count}");
}

#[test]
fn test_capabilities_returns_matching_courses() {
    let registry = real_registry();
    let telemetry = StationTelemetry::new_local(None);
    let result = router::route_tool_call(
        &registry,
        &telemetry,
        None,
        &ApiKeyGate::new(None),
        None,
        "nexvigilant_capabilities",
        &json!({"query": "causality"}),
        None,
    );
    let text = match &result.content[0] {
        nexvigilant_station::protocol::ContentBlock::Text { text } => text,
    };
    let parsed: Value = serde_json::from_str(text).expect("valid JSON");
    let courses = parsed["matching_courses"].as_array().expect("matching_courses array");
    assert!(
        courses.iter().any(|c| c["course"].as_str() == Some("causality-assessment")),
        "searching 'causality' should match the causality-assessment course"
    );
}

#[test]
fn test_course_summaries_have_valid_data() {
    for (name, desc, steps) in nexvigilant_station::science::course_summaries() {
        assert!(!name.is_empty(), "course name must not be empty");
        assert!(!desc.is_empty(), "course description must not be empty");
        assert!(steps > 0, "course '{name}' must have at least 1 step");
    }
}

// =============================================
// Phase 5: Telemetry Health Engine
// =============================================

fn record_call(telemetry: &StationTelemetry, domain: &str, tool: &str, duration_ms: u64, is_error: bool) {
    telemetry.record(telemetry::ToolCallRecord {
        timestamp: telemetry::now_iso8601(),
        tool_name: tool.into(),
        domain: domain.into(),
        duration_ms,
        status: if is_error { "error" } else { "ok" }.into(),
        is_error,
        error_message: if is_error { Some("test error".into()) } else { None },
        client_id: None,
        request_id: None,
    });
}

#[test]
fn test_health_empty_ring() {
    let telemetry = StationTelemetry::new(None);
    let health = telemetry.health();
    assert_eq!(health.total_calls, 0);
    assert_eq!(health.total_errors, 0);
    assert_eq!(health.error_rate_pct, 0.0);
    assert_eq!(health.latency_p99_ms, 0);
    assert!(health.latency_slo_ok);
    assert_eq!(health.slo_status, "ok");
    assert_eq!(health.trend, "stable");
    assert!(health.degraded_domains.is_empty());
}

#[test]
fn test_health_counts_calls_and_errors() {
    let telemetry = StationTelemetry::new(None);
    record_call(&telemetry, "api.fda.gov", "search_adverse_events", 100, false);
    record_call(&telemetry, "api.fda.gov", "search_adverse_events", 200, false);
    record_call(&telemetry, "api.fda.gov", "get_drug_counts", 150, true);

    let health = telemetry.health();
    assert_eq!(health.total_calls, 3);
    assert_eq!(health.total_errors, 1);
    // 1/3 = 33.3%
    assert!((health.error_rate_pct - 33.33).abs() < 1.0);
}

#[test]
fn test_health_domain_aggregation() {
    let telemetry = StationTelemetry::new(None);
    record_call(&telemetry, "api.fda.gov", "search_adverse_events", 100, false);
    record_call(&telemetry, "api.fda.gov", "get_drug_counts", 200, false);
    record_call(&telemetry, "dailymed.nlm.nih.gov", "search_drugs", 300, false);

    let health = telemetry.health();
    assert_eq!(health.domains.len(), 2);

    let fda = health.domains.iter().find(|d| d.domain == "api.fda.gov").expect("fda domain");
    assert_eq!(fda.call_count, 2);
    assert_eq!(fda.error_count, 0);
    assert!((fda.avg_duration_ms - 150.0).abs() < 1.0);
}

#[test]
fn test_health_top_tools_ranking() {
    let telemetry = StationTelemetry::new(None);
    for _ in 0..5 {
        record_call(&telemetry, "api.fda.gov", "search_adverse_events", 100, false);
    }
    for _ in 0..3 {
        record_call(&telemetry, "api.fda.gov", "get_drug_counts", 100, false);
    }
    record_call(&telemetry, "api.fda.gov", "get_event_outcomes", 100, false);

    let health = telemetry.health();
    assert_eq!(health.top_tools[0].0, "search_adverse_events");
    assert_eq!(health.top_tools[0].1, 5);
    assert_eq!(health.top_tools[1].0, "get_drug_counts");
    assert_eq!(health.top_tools[1].1, 3);
}

#[test]
fn test_health_p99_latency() {
    let telemetry = StationTelemetry::new(None);
    // 90 fast calls + 10 slow calls → P99 should pick one of the slow ones
    for _ in 0..90 {
        record_call(&telemetry, "api.fda.gov", "fast_tool", 50, false);
    }
    for _ in 0..10 {
        record_call(&telemetry, "api.fda.gov", "slow_tool", 4000, false);
    }

    let health = telemetry.health();
    assert_eq!(health.total_calls, 100);
    assert_eq!(health.latency_p99_ms, 4000);
    assert!(health.latency_slo_ok); // 4000 < 5000 target
}

#[test]
fn test_health_p99_slo_breach() {
    let telemetry = StationTelemetry::new(None);
    // 90 fast + 10 over SLO threshold → P99 picks the slow ones
    for _ in 0..90 {
        record_call(&telemetry, "api.fda.gov", "fast_tool", 50, false);
    }
    for _ in 0..10 {
        record_call(&telemetry, "api.fda.gov", "slow_tool", 6000, false);
    }

    let health = telemetry.health();
    assert_eq!(health.latency_p99_ms, 6000);
    assert!(!health.latency_slo_ok);
    assert_eq!(health.slo_status, "critical"); // P99 breach → critical
}

#[test]
fn test_health_slo_warn_on_high_error_rate() {
    let telemetry = StationTelemetry::new(None);
    // 6% error rate: 6 errors out of 100 calls
    for _ in 0..94 {
        record_call(&telemetry, "api.fda.gov", "tool", 100, false);
    }
    for _ in 0..6 {
        record_call(&telemetry, "api.fda.gov", "tool", 100, true);
    }

    let health = telemetry.health();
    assert_eq!(health.slo_status, "warn");
}

#[test]
fn test_health_slo_critical_on_very_high_error_rate() {
    let telemetry = StationTelemetry::new(None);
    // 11% error rate
    for _ in 0..89 {
        record_call(&telemetry, "api.fda.gov", "tool", 100, false);
    }
    for _ in 0..11 {
        record_call(&telemetry, "api.fda.gov", "tool", 100, true);
    }

    let health = telemetry.health();
    assert_eq!(health.slo_status, "critical");
}

#[test]
fn test_health_degraded_domains() {
    let telemetry = StationTelemetry::new(None);
    // fda: 10 calls, 1 error (10% > 5% threshold, >= 5 sample)
    for _ in 0..9 {
        record_call(&telemetry, "api.fda.gov", "tool", 100, false);
    }
    record_call(&telemetry, "api.fda.gov", "tool", 100, true);

    // dailymed: 10 calls, 0 errors — healthy
    for _ in 0..10 {
        record_call(&telemetry, "dailymed.nlm.nih.gov", "tool", 100, false);
    }

    let health = telemetry.health();
    assert_eq!(health.degraded_domains.len(), 1);
    assert_eq!(health.degraded_domains[0], "api.fda.gov");
}

#[test]
fn test_health_degraded_ignores_low_sample() {
    let telemetry = StationTelemetry::new(None);
    // Only 3 calls with 1 error (33%) — but below 5-call minimum sample
    for _ in 0..2 {
        record_call(&telemetry, "api.fda.gov", "tool", 100, false);
    }
    record_call(&telemetry, "api.fda.gov", "tool", 100, true);

    let health = telemetry.health();
    assert!(health.degraded_domains.is_empty(), "should ignore low-sample domains");
}

#[test]
fn test_health_trend_stable_with_uniform_errors() {
    let telemetry = StationTelemetry::new(None);
    // Even distribution of errors across first and second half
    for i in 0..20 {
        record_call(&telemetry, "api.fda.gov", "tool", 100, i % 5 == 0);
    }

    let health = telemetry.health();
    assert_eq!(health.trend, "stable");
}

#[test]
fn test_health_trend_improving() {
    let telemetry = StationTelemetry::new(None);
    // First half: many errors
    for _ in 0..5 {
        record_call(&telemetry, "api.fda.gov", "tool", 100, true);
    }
    for _ in 0..5 {
        record_call(&telemetry, "api.fda.gov", "tool", 100, false);
    }
    // Second half: no errors
    for _ in 0..10 {
        record_call(&telemetry, "api.fda.gov", "tool", 100, false);
    }

    let health = telemetry.health();
    assert_eq!(health.trend, "improving");
}

#[test]
fn test_health_trend_degrading() {
    let telemetry = StationTelemetry::new(None);
    // First half: no errors
    for _ in 0..10 {
        record_call(&telemetry, "api.fda.gov", "tool", 100, false);
    }
    // Second half: many errors
    for _ in 0..5 {
        record_call(&telemetry, "api.fda.gov", "tool", 100, false);
    }
    for _ in 0..5 {
        record_call(&telemetry, "api.fda.gov", "tool", 100, true);
    }

    let health = telemetry.health();
    assert_eq!(health.trend, "degrading");
}

#[test]
fn test_health_trend_stable_insufficient_data() {
    let telemetry = StationTelemetry::new(None);
    // Only 5 calls — below the 10-call minimum for trend detection
    for _ in 0..5 {
        record_call(&telemetry, "api.fda.gov", "tool", 100, true);
    }

    let health = telemetry.health();
    assert_eq!(health.trend, "stable");
}

#[test]
fn test_health_recent_calls_limited() {
    let telemetry = StationTelemetry::new(None);
    for i in 0..50 {
        record_call(&telemetry, "api.fda.gov", &format!("tool_{i}"), 100, false);
    }

    let health = telemetry.health();
    assert_eq!(health.recent_calls.len(), 20, "recent_calls capped at 20");
    // Most recent should be first
    assert_eq!(health.recent_calls[0].tool_name, "tool_49");
}

#[test]
fn test_extract_domain_known_prefixes() {
    assert_eq!(telemetry::extract_domain("api_fda_gov_search_adverse_events"), "api.fda.gov");
    assert_eq!(telemetry::extract_domain("dailymed_nlm_nih_gov_get_drug_label"), "dailymed.nlm.nih.gov");
    assert_eq!(telemetry::extract_domain("clinicaltrials_gov_search_trials"), "clinicaltrials.gov");
}

#[test]
fn test_extract_domain_meta_tools() {
    assert_eq!(telemetry::extract_domain("nexvigilant_directory"), "nexvigilant.meta");
    assert_eq!(telemetry::extract_domain("nexvigilant_capabilities"), "nexvigilant.meta");
    assert_eq!(telemetry::extract_domain("nexvigilant_station_health"), "nexvigilant.meta");
    assert_eq!(telemetry::extract_domain("nexvigilant_chart_course"), "nexvigilant.meta");
}

#[test]
fn test_health_serializes_to_json() {
    let telemetry = StationTelemetry::new(None);
    record_call(&telemetry, "api.fda.gov", "tool", 100, false);

    let health = telemetry.health();
    let json = serde_json::to_value(&health).expect("should serialize");
    assert_eq!(json["station"], "NexVigilant Station");
    assert!(json["uptime_seconds"].is_u64());
    assert!(json["slo_status"].is_string());
    assert!(json["trend"].is_string());
    assert!(json["latency_p99_ms"].is_u64());
}
