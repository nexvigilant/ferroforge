use nexvigilant_station::config::{ConfigRegistry, HubConfig, ParamDef, ToolDef};
use nexvigilant_station::protocol::{JsonRpcRequest, INVALID_PARAMS, METHOD_NOT_FOUND};
use nexvigilant_station::router;
use nexvigilant_station::server;
use serde_json::{json, Value};
use std::io::Write;
use tempfile::TempDir;

// --- Helper: build a test registry from inline configs ---

fn test_registry() -> ConfigRegistry {
    ConfigRegistry {
        configs: vec![
            HubConfig {
                domain: "api.fda.gov".into(),
                url_pattern: Some("/drug/event*".into()),
                title: "openFDA FAERS".into(),
                description: Some("Test config".into()),
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
                    },
                    ToolDef {
                        name: "get-drug-counts".into(),
                        description: "Get counts".into(),
                        parameters: vec![],
                        stub_response: None,
                    },
                ],
            },
            HubConfig {
                domain: "dailymed.nlm.nih.gov".into(),
                url_pattern: None,
                title: "DailyMed".into(),
                description: None,
                tools: vec![ToolDef {
                    name: "get-drug-label".into(),
                    description: "Get label".into(),
                    parameters: vec![],
                    stub_response: Some(r#"{"label":"test"}"#.into()),
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
    assert_eq!(reg.tool_count(), 3);
}

#[test]
fn test_registry_tool_infos_count() {
    let reg = test_registry();
    let infos = reg.tool_infos();
    assert_eq!(infos.len(), 3);
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
        assert!(info.description.starts_with('['), "description should start with [domain]: {}", info.description);
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
    assert_eq!(reg.tool_count(), 0);
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
    assert_eq!(reg.tool_count(), 1);
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
    let result = router::route_tool_call(&reg, "api_fda_gov_search_adverse_events", &json!({"drug_name": "aspirin"}));
    assert!(result.is_error.is_none());
    assert_eq!(result.content.len(), 1);
}

#[test]
fn test_route_known_tool_without_stub() {
    let reg = test_registry();
    let result = router::route_tool_call(&reg, "api_fda_gov_get_drug_counts", &json!({"drug_name": "metformin"}));
    assert!(result.is_error.is_none());
    let text = match &result.content[0] {
        nexvigilant_station::protocol::ContentBlock::Text { text } => text,
    };
    assert!(text.contains("registered but has no implementation"));
}

#[test]
fn test_route_unknown_tool() {
    let reg = test_registry();
    let result = router::route_tool_call(&reg, "nonexistent_tool", &json!({}));
    assert_eq!(result.is_error, Some(true));
}

// =============================================
// Phase 0: MCP Server Handler
// =============================================

#[test]
fn test_handle_initialize() {
    let reg = test_registry();
    let req = make_request(Some(json!(1)), "initialize", Some(json!({})));
    let resp = server::handle_request(&reg, &req).expect("should respond");
    let result = resp.result.expect("should have result");
    assert_eq!(result["protocolVersion"], "2024-11-05");
    assert_eq!(result["serverInfo"]["name"], "nexvigilant-station");
    assert!(resp.error.is_none());
}

#[test]
fn test_handle_tools_list() {
    let reg = test_registry();
    let req = make_request(Some(json!(2)), "tools/list", None);
    let resp = server::handle_request(&reg, &req).expect("should respond");
    let result = resp.result.expect("should have result");
    let tools = result["tools"].as_array().expect("tools array");
    assert_eq!(tools.len(), 3);
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
    let resp = server::handle_request(&reg, &req).expect("should respond");
    let result = resp.result.expect("should have result");
    let content = result["content"].as_array().expect("content");
    assert_eq!(content.len(), 1);
    assert!(content[0]["text"].as_str().expect("text").contains("ok"));
}

#[test]
fn test_handle_tools_call_missing_name() {
    let reg = test_registry();
    let req = make_request(Some(json!(4)), "tools/call", Some(json!({"arguments": {}})));
    let resp = server::handle_request(&reg, &req).expect("should respond");
    let err = resp.error.expect("should have error");
    assert_eq!(err.code, INVALID_PARAMS);
}

#[test]
fn test_handle_ping() {
    let reg = test_registry();
    let req = make_request(Some(json!(5)), "ping", None);
    let resp = server::handle_request(&reg, &req).expect("should respond");
    assert!(resp.result.is_some());
    assert!(resp.error.is_none());
}

#[test]
fn test_handle_unknown_method() {
    let reg = test_registry();
    let req = make_request(Some(json!(6)), "bogus/method", None);
    let resp = server::handle_request(&reg, &req).expect("should respond");
    let err = resp.error.expect("should have error");
    assert_eq!(err.code, METHOD_NOT_FOUND);
}

#[test]
fn test_handle_notification_returns_none() {
    let reg = test_registry();
    let req = make_request(None, "notifications/initialized", None);
    let resp = server::handle_request(&reg, &req);
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
    let resp = server::handle_request(&reg, &req).expect("respond");
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
    let resp = server::handle_request(&reg, &req).expect("respond");
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
        let found = reg.find_tool(&info.name);
        assert!(
            found.is_some(),
            "tool '{}' listed but not routable via find_tool",
            info.name
        );
    }
}
