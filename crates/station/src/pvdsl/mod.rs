//! PVDSL — Rust-native handler for NexVigilant Station.
//!
//! Routes `pvdsl_nexvigilant_com_*` tool calls to `nexcore-pvdsl`.

use nexcore_pvdsl::lexer::Lexer;
use nexcore_pvdsl::parser::Parser;
use nexcore_pvdsl::engine::PvdslEngine;
use nexcore_pvdsl::runtime::RuntimeValue;
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

/// Try to handle a PVDSL tool call. Returns `None` to fall through.
pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("pvdsl_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "compile" => handle_compile(args),
        "evaluate" => handle_evaluate(args),
        "functions" => handle_functions(),
        "parse" => handle_parse(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (pvdsl)");

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

fn runtime_to_json(rv: &RuntimeValue) -> Value {
    match rv {
        RuntimeValue::Number(n) => json!(n),
        RuntimeValue::String(s) => json!(s),
        RuntimeValue::Boolean(b) => json!(b),
        RuntimeValue::List(items) => {
            let arr: Vec<Value> = items.iter().map(runtime_to_json).collect();
            json!(arr)
        }
        RuntimeValue::Dict(map) => {
            let obj: serde_json::Map<String, Value> = map
                .iter()
                .map(|(k, v)| (k.clone(), runtime_to_json(v)))
                .collect();
            Value::Object(obj)
        }
        RuntimeValue::Null => Value::Null,
    }
}

fn ok(v: Value) -> Value {
    let mut obj = v;
    if let Some(map) = obj.as_object_mut() {
        map.insert("status".into(), json!("ok"));
    }
    obj
}

fn err(msg: &str) -> Value {
    json!({ "status": "error", "error": msg })
}

fn handle_compile(args: &Value) -> Value {
    let source = match args.get("source").and_then(|s| s.as_str()) {
        Some(s) => s,
        None => return err("Missing required parameter: source"),
    };

    let engine = PvdslEngine::new();
    match engine.compile(source) {
        Ok(program) => {
            let instructions: Vec<Value> = program
                .instructions
                .iter()
                .enumerate()
                .map(|(i, op)| json!({ "index": i, "opcode": format!("{op:?}") }))
                .collect();

            ok(json!({
                "source": source,
                "instruction_count": instructions.len(),
                "instructions": instructions,
            }))
        }
        Err(e) => err(&format!("Compilation failed: {e}")),
    }
}

fn handle_evaluate(args: &Value) -> Value {
    let source = match args.get("source").and_then(|s| s.as_str()) {
        Some(s) => s,
        None => return err("Missing required parameter: source"),
    };

    let mut engine = PvdslEngine::new();

    // Bind variables if provided
    if let Some(vars) = args.get("variables").and_then(|v| v.as_object()) {
        for (key, val) in vars {
            let rv = if let Some(n) = val.as_f64() {
                RuntimeValue::Number(n)
            } else if let Some(s) = val.as_str() {
                RuntimeValue::String(s.to_string())
            } else if let Some(b) = val.as_bool() {
                RuntimeValue::Boolean(b)
            } else {
                continue;
            };
            engine.set_variable(key, rv);
        }
    }

    match engine.eval(source) {
        Ok(Some(value)) => {
            let (result_json, type_name) = match &value {
                RuntimeValue::Number(n) => (json!(n), "number"),
                RuntimeValue::String(s) => (json!(s), "string"),
                RuntimeValue::Boolean(b) => (json!(b), "boolean"),
                RuntimeValue::List(items) => {
                    let arr: Vec<Value> = items.iter().map(runtime_to_json).collect();
                    (json!(arr), "list")
                }
                RuntimeValue::Dict(map) => {
                    let obj: serde_json::Map<String, Value> = map
                        .iter()
                        .map(|(k, v)| (k.clone(), runtime_to_json(v)))
                        .collect();
                    (Value::Object(obj), "dict")
                }
                RuntimeValue::Null => (Value::Null, "null"),
            };
            ok(json!({
                "source": source,
                "result": result_json,
                "result_type": type_name,
            }))
        }
        Ok(None) => ok(json!({
            "source": source,
            "result": null,
            "result_type": "none",
        })),
        Err(e) => err(&format!("Evaluation failed: {e}")),
    }
}

fn handle_functions() -> Value {
    let namespaces = json!({
        "signal": {
            "description": "Signal detection algorithms",
            "functions": ["prr", "ror", "ic", "ebgm", "chi_square", "fisher", "sprt", "maxsprt", "cusum", "mgps"]
        },
        "causality": {
            "description": "Causality assessment methods",
            "functions": ["naranjo", "who_umc", "rucam"]
        },
        "meddra": {
            "description": "Medical coding and string similarity",
            "functions": ["levenshtein", "similarity"]
        },
        "risk": {
            "description": "Risk analytics",
            "functions": ["sar", "es", "monte_carlo"]
        },
        "date": {
            "description": "Date operations",
            "functions": ["now", "diff_days"]
        },
        "classify": {
            "description": "Classification algorithms",
            "functions": ["hartwig_siegel"]
        },
        "math": {
            "description": "Mathematical functions",
            "functions": ["abs", "sqrt", "pow", "log", "ln", "exp", "min", "max", "floor", "ceil", "round"]
        },
        "chem": {
            "description": "Chemistry-based capability assessment",
            "functions": ["arrhenius", "michaelis", "hill", "henderson", "halflife", "sqi"]
        }
    });

    let total = 10 + 3 + 2 + 3 + 2 + 1 + 11 + 6; // 38 functions

    ok(json!({
        "crate": "nexcore-pvdsl",
        "language": "PVDSL — Pharmacovigilance Domain-Specific Language",
        "namespace_count": 8,
        "total_functions": total,
        "namespaces": namespaces,
        "usage": "Call evaluate with source like: return signal::prr(10, 90, 100, 9800)",
    }))
}

fn handle_parse(args: &Value) -> Value {
    let source = match args.get("source").and_then(|s| s.as_str()) {
        Some(s) => s,
        None => return err("Missing required parameter: source"),
    };

    let mut lexer = Lexer::new(source);
    let tokens = lexer.tokenize();
    let mut parser = Parser::new(tokens);

    match parser.parse() {
        Ok(program) => {
            let statements: Vec<Value> = program
                .statements
                .iter()
                .map(|stmt| json!(format!("{stmt:?}")))
                .collect();

            ok(json!({
                "source": source,
                "statement_count": statements.len(),
                "ast": {
                    "statements": statements,
                    "metadata": {
                        "has_functions": program.metadata.has_functions,
                    }
                },
            }))
        }
        Err(e) => err(&format!("Parse failed: {e}")),
    }
}
