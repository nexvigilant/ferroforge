//! DataFrame — Rust-native handler for NexVigilant Station.
//!
//! Routes `dataframe_nexvigilant_com_*` tool calls to `nexcore-dataframe`.

use nexcore_dataframe::prelude::*;
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("dataframe_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "create" => handle_create(args),
        "describe" => handle_describe(args),
        "filter" => handle_filter(args),
        "group-by" => handle_group_by(args),
        "sort" => handle_sort(args),
        "select" => handle_select(args),
        "join" => handle_join(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (dataframe)");

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

fn round6(v: f64) -> f64 {
    (v * 1_000_000.0).round() / 1_000_000.0
}

// ---------------------------------------------------------------------------
// DataFrame construction from JSON columns object
// ---------------------------------------------------------------------------

/// Build a DataFrame from `{"col1": [v1, v2, ...], "col2": [...]}`.
fn build_df(columns_val: &Value) -> Result<DataFrame, String> {
    let obj = columns_val
        .as_object()
        .ok_or_else(|| "columns must be a JSON object".to_string())?;

    if obj.is_empty() {
        return Ok(DataFrame::empty());
    }

    let mut cols: Vec<Column> = Vec::with_capacity(obj.len());

    for (name, arr_val) in obj {
        let arr = arr_val
            .as_array()
            .ok_or_else(|| format!("column '{name}' must be an array"))?;

        // Infer type from first non-null element
        let first_non_null = arr.iter().find(|v| !v.is_null());
        let col = match first_non_null {
            Some(Value::Bool(_)) => {
                let data: Vec<Option<bool>> = arr
                    .iter()
                    .map(|v| if v.is_null() { None } else { v.as_bool() })
                    .collect();
                Column::new_bool(name, data)
            }
            Some(Value::Number(n)) if n.is_f64() && n.as_i64().is_none() => {
                let data: Vec<Option<f64>> = arr
                    .iter()
                    .map(|v| if v.is_null() { None } else { v.as_f64() })
                    .collect();
                Column::new_f64(name, data)
            }
            Some(Value::Number(_)) => {
                let data: Vec<Option<i64>> = arr
                    .iter()
                    .map(|v| if v.is_null() { None } else { v.as_i64() })
                    .collect();
                Column::new_i64(name, data)
            }
            Some(Value::String(_)) | None => {
                let data: Vec<Option<String>> = arr
                    .iter()
                    .map(|v| {
                        if v.is_null() {
                            None
                        } else {
                            v.as_str().map(|s| s.to_string())
                        }
                    })
                    .collect();
                Column::new_string(name, data)
            }
            _ => {
                // Fallback: stringify everything
                let data: Vec<Option<String>> = arr
                    .iter()
                    .map(|v| {
                        if v.is_null() {
                            None
                        } else {
                            Some(v.to_string())
                        }
                    })
                    .collect();
                Column::new_string(name, data)
            }
        };
        cols.push(col);
    }

    DataFrame::new(cols).map_err(|e| format!("{e}"))
}

/// Serialize a DataFrame back to `{"col1": [...], "col2": [...]}`.
fn df_to_json(df: &DataFrame) -> Value {
    let mut map = serde_json::Map::new();
    for col in df.columns() {
        let values: Vec<Value> = (0..col.len())
            .map(|i| scalar_to_json(&col.get(i).unwrap_or(Scalar::Null)))
            .collect();
        map.insert(col.name().to_string(), Value::Array(values));
    }
    Value::Object(map)
}

fn scalar_to_json(s: &Scalar) -> Value {
    match s {
        Scalar::Null => Value::Null,
        Scalar::Bool(b) => json!(b),
        Scalar::Int64(n) => json!(n),
        Scalar::UInt64(n) => json!(n),
        Scalar::Float64(f) => json!(f),
        Scalar::String(s) => json!(s),
        _ => Value::Null,
    }
}

// ---------------------------------------------------------------------------
// Tool handlers
// ---------------------------------------------------------------------------

fn handle_create(args: &Value) -> Value {
    let columns_val = match args.get("columns") {
        Some(v) => v,
        None => return err("missing required parameter: columns"),
    };
    match build_df(columns_val) {
        Ok(df) => ok(json!({
            "columns": df.column_names(),
            "height": df.height(),
            "width": df.width(),
            "schema": df.schema().fields().iter()
                .map(|(n, dt)| json!({"name": n, "dtype": format!("{dt:?}")}))
                .collect::<Vec<_>>(),
        })),
        Err(e) => err(&e),
    }
}

fn handle_describe(args: &Value) -> Value {
    let columns_val = match args.get("columns") {
        Some(v) => v,
        None => return err("missing required parameter: columns"),
    };
    let col_name = match args.get("column").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing required parameter: column"),
    };

    let df = match build_df(columns_val) {
        Ok(d) => d,
        Err(e) => return err(&e),
    };

    let col = match df.column(col_name) {
        Ok(c) => c,
        Err(e) => return err(&format!("{e}")),
    };

    ok(json!({
        "column": col_name,
        "dtype": format!("{:?}", col.dtype()),
        "count": col.len(),
        "non_null": col.non_null_count(),
        "null_count": col.null_count(),
        "mean": round6(col.mean().as_f64().unwrap_or(f64::NAN)),
        "std_dev": round6(col.std_dev().as_f64().unwrap_or(f64::NAN)),
        "min": scalar_to_json(&col.min()),
        "max": scalar_to_json(&col.max()),
        "median": scalar_to_json(&col.median()),
        "n_unique": col.n_unique(),
    }))
}

fn handle_filter(args: &Value) -> Value {
    let columns_val = match args.get("columns") {
        Some(v) => v,
        None => return err("missing required parameter: columns"),
    };
    let col_name = match args.get("column").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing required parameter: column"),
    };
    let operator = match args.get("operator").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing required parameter: operator"),
    };
    let value_str = match args.get("value").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing required parameter: value"),
    };

    let df = match build_df(columns_val) {
        Ok(d) => d,
        Err(e) => return err(&e),
    };

    let compare_val = parse_scalar(value_str);

    let filtered = match df.filter_by(col_name, |cell| {
        match operator {
            "eq" => scalar_cmp(cell, &compare_val) == std::cmp::Ordering::Equal,
            "neq" => scalar_cmp(cell, &compare_val) != std::cmp::Ordering::Equal,
            "gt" => scalar_cmp(cell, &compare_val) == std::cmp::Ordering::Greater,
            "gte" => !matches!(scalar_cmp(cell, &compare_val), std::cmp::Ordering::Less),
            "lt" => scalar_cmp(cell, &compare_val) == std::cmp::Ordering::Less,
            "lte" => !matches!(scalar_cmp(cell, &compare_val), std::cmp::Ordering::Greater),
            "contains" => {
                cell.as_str()
                    .is_some_and(|s| s.contains(value_str))
            }
            _ => false,
        }
    }) {
        Ok(d) => d,
        Err(e) => return err(&format!("{e}")),
    };

    ok(json!({
        "columns": df_to_json(&filtered),
        "height": filtered.height(),
        "original_height": df.height(),
    }))
}

fn handle_group_by(args: &Value) -> Value {
    let columns_val = match args.get("columns") {
        Some(v) => v,
        None => return err("missing required parameter: columns"),
    };
    let group_cols: Vec<&str> = match args.get("group_cols").and_then(|v| v.as_array()) {
        Some(arr) => arr.iter().filter_map(|v| v.as_str()).collect(),
        None => return err("missing required parameter: group_cols"),
    };
    let agg_defs = match args.get("aggs").and_then(|v| v.as_array()) {
        Some(arr) => arr,
        None => return err("missing required parameter: aggs"),
    };

    let df = match build_df(columns_val) {
        Ok(d) => d,
        Err(e) => return err(&e),
    };

    // Parse agg definitions
    let mut aggs: Vec<Agg> = Vec::new();
    for def in agg_defs {
        let agg_type = match def.get("type").and_then(|v| v.as_str()) {
            Some(t) => t,
            None => return err("each agg needs a 'type' field"),
        };
        let col = def.get("column").and_then(|v| v.as_str()).unwrap_or("");
        let agg = match agg_type {
            "sum" => Agg::Sum(col.to_string()),
            "mean" => Agg::Mean(col.to_string()),
            "min" => Agg::Min(col.to_string()),
            "max" => Agg::Max(col.to_string()),
            "count" => Agg::Count,
            "first" => Agg::First(col.to_string()),
            "last" => Agg::Last(col.to_string()),
            "n_unique" => Agg::NUnique(col.to_string()),
            other => return err(&format!("unknown agg type: {other}")),
        };
        aggs.push(agg);
    }

    let grouped = match df.group_by(&group_cols) {
        Ok(g) => g,
        Err(e) => return err(&format!("{e}")),
    };

    let result_df = match grouped.agg(&aggs) {
        Ok(d) => d,
        Err(e) => return err(&format!("{e}")),
    };

    ok(json!({
        "columns": df_to_json(&result_df),
        "height": result_df.height(),
        "n_groups": result_df.height(),
    }))
}

fn handle_sort(args: &Value) -> Value {
    let columns_val = match args.get("columns") {
        Some(v) => v,
        None => return err("missing required parameter: columns"),
    };
    let by = match args.get("by").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing required parameter: by"),
    };
    let descending = args.get("descending").and_then(|v| v.as_bool()).unwrap_or(false);
    let limit = args.get("limit").and_then(|v| v.as_u64()).map(|n| n as usize);

    let df = match build_df(columns_val) {
        Ok(d) => d,
        Err(e) => return err(&e),
    };

    let sorted = match df.sort(by, descending) {
        Ok(d) => d,
        Err(e) => return err(&format!("{e}")),
    };

    let result = match limit {
        Some(n) => sorted.head(n),
        None => sorted,
    };

    ok(json!({
        "columns": df_to_json(&result),
        "height": result.height(),
    }))
}

fn handle_select(args: &Value) -> Value {
    let columns_val = match args.get("columns") {
        Some(v) => v,
        None => return err("missing required parameter: columns"),
    };
    let keep: Option<Vec<&str>> = args
        .get("keep")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|v| v.as_str()).collect());
    let drop_cols: Option<Vec<&str>> = args
        .get("drop")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|v| v.as_str()).collect());

    if keep.is_none() && drop_cols.is_none() {
        return err("provide either 'keep' or 'drop' parameter");
    }
    if keep.is_some() && drop_cols.is_some() {
        return err("provide either 'keep' or 'drop', not both");
    }

    let df = match build_df(columns_val) {
        Ok(d) => d,
        Err(e) => return err(&e),
    };

    let result = if let Some(names) = keep {
        match df.select(&names) {
            Ok(d) => d,
            Err(e) => return err(&format!("{e}")),
        }
    } else if let Some(names) = drop_cols {
        df.drop_columns(&names)
    } else {
        df
    };

    ok(json!({
        "columns": df_to_json(&result),
        "height": result.height(),
        "width": result.width(),
    }))
}

fn handle_join(args: &Value) -> Value {
    let left_val = match args.get("left") {
        Some(v) => v,
        None => return err("missing required parameter: left"),
    };
    let right_val = match args.get("right") {
        Some(v) => v,
        None => return err("missing required parameter: right"),
    };
    let on_cols: Vec<&str> = match args.get("on").and_then(|v| v.as_array()) {
        Some(arr) => arr.iter().filter_map(|v| v.as_str()).collect(),
        None => return err("missing required parameter: on"),
    };
    let how_str = args
        .get("how")
        .and_then(|v| v.as_str())
        .unwrap_or("inner");

    let how = match how_str {
        "inner" => nexcore_dataframe::prelude::JoinType::Inner,
        "left" => nexcore_dataframe::prelude::JoinType::Left,
        "right" => nexcore_dataframe::prelude::JoinType::Right,
        "outer" => nexcore_dataframe::prelude::JoinType::Outer,
        "semi" => nexcore_dataframe::prelude::JoinType::Semi,
        "anti" => nexcore_dataframe::prelude::JoinType::Anti,
        other => return err(&format!("unknown join type: {other}. Use: inner, left, right, outer, semi, anti")),
    };

    let left_df = match build_df(left_val) {
        Ok(d) => d,
        Err(e) => return err(&format!("left: {e}")),
    };
    let right_df = match build_df(right_val) {
        Ok(d) => d,
        Err(e) => return err(&format!("right: {e}")),
    };

    let on_refs: Vec<&str> = on_cols.to_vec();
    let result = match left_df.join(&right_df, &on_refs, how) {
        Ok(d) => d,
        Err(e) => return err(&format!("{e}")),
    };

    ok(json!({
        "columns": df_to_json(&result),
        "height": result.height(),
        "width": result.width(),
    }))
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn parse_scalar(s: &str) -> Scalar {
    if let Ok(n) = s.parse::<i64>() {
        return Scalar::Int64(n);
    }
    if let Ok(f) = s.parse::<f64>() {
        return Scalar::Float64(f);
    }
    if s.eq_ignore_ascii_case("true") {
        return Scalar::Bool(true);
    }
    if s.eq_ignore_ascii_case("false") {
        return Scalar::Bool(false);
    }
    Scalar::String(s.to_string())
}

fn scalar_cmp(a: &Scalar, b: &Scalar) -> std::cmp::Ordering {
    a.compare(b)
}
