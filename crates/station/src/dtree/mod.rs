//! Decision Tree — Rust-native handler for NexVigilant Station.
//!
//! Routes `dtree_nexvigilant_com_*` tool calls to `nexcore-dtree`.

use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("dtree_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "train" => handle_train(args),
        "predict" => handle_predict(args),
        "feature-importance" => handle_importance(args),
        "prune" => handle_prune(args),
        "info" => handle_info(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (dtree)");

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

fn to_features(arr: &[Value]) -> Vec<nexcore_dtree::types::Feature> {
    arr.iter()
        .map(|v| nexcore_dtree::types::Feature::Continuous(v.as_f64().unwrap_or(0.0)))
        .collect()
}

fn handle_train(args: &Value) -> Value {
    use nexcore_dtree::types::{Feature, TreeConfig};
    use nexcore_dtree::train::fit;

    let features = match args.get("features").and_then(|f| f.as_array()) {
        Some(f) => f,
        None => return json!({"status": "error", "message": "Missing: features (2D array)"}),
    };
    let labels = match args.get("labels").and_then(|l| l.as_array()) {
        Some(l) => l,
        None => return json!({"status": "error", "message": "Missing: labels (array)"}),
    };

    let feature_matrix: Vec<Vec<Feature>> = features
        .iter()
        .map(|row| {
            row.as_array()
                .map(|r| r.iter().map(|v| Feature::Continuous(v.as_f64().unwrap_or(0.0))).collect())
                .unwrap_or_default()
        })
        .collect();

    let label_vec: Vec<String> = labels
        .iter()
        .map(|v| v.as_str().unwrap_or("unknown").to_string())
        .collect();

    if feature_matrix.is_empty() || label_vec.is_empty() {
        return json!({"status": "error", "message": "Empty features or labels"});
    }
    if feature_matrix.len() != label_vec.len() {
        return json!({"status": "error", "message": "Features and labels length mismatch"});
    }

    let max_depth = args.get("max_depth").and_then(|v| v.as_u64()).map(|v| v as usize);
    let min_samples = args.get("min_samples_split").and_then(|v| v.as_u64()).unwrap_or(2) as usize;

    let config = TreeConfig {
        max_depth,
        min_samples_split: min_samples,
        ..TreeConfig::default()
    };

    match fit(&feature_matrix, &label_vec, config) {
        Ok(tree) => {
            let stats = tree.stats();
            let tree_json = serde_json::to_string(&tree).unwrap_or_default();
            json!({
                "status": "ok",
                "tree_json": tree_json,
                "depth": stats.as_ref().map(|s| s.depth).unwrap_or(0),
                "n_leaves": stats.as_ref().map(|s| s.n_leaves).unwrap_or(0),
                "n_nodes": stats.as_ref().map(|s| s.n_nodes).unwrap_or(0)
            })
        }
        Err(e) => json!({"status": "error", "message": format!("{e}")}),
    }
}

fn handle_predict(args: &Value) -> Value {
    use nexcore_dtree::predict::predict;

    let tree_json = match args.get("tree_json").and_then(|v| v.as_str()) {
        Some(j) => j,
        None => return json!({"status": "error", "message": "Missing: tree_json"}),
    };
    let features = match args.get("features").and_then(|f| f.as_array()) {
        Some(f) => to_features(f),
        None => return json!({"status": "error", "message": "Missing: features"}),
    };

    let tree: nexcore_dtree::node::DecisionTree = match serde_json::from_str(tree_json) {
        Ok(t) => t,
        Err(e) => return json!({"status": "error", "message": format!("Invalid tree_json: {e}")}),
    };

    match predict(&tree, &features) {
        Ok(result) => json!({
            "status": "ok",
            "prediction": result.prediction,
            "confidence": result.confidence.value()
        }),
        Err(e) => json!({"status": "error", "message": format!("{e}")}),
    }
}

fn handle_importance(args: &Value) -> Value {
    use nexcore_dtree::importance::feature_importance;

    let tree_json = match args.get("tree_json").and_then(|v| v.as_str()) {
        Some(j) => j,
        None => return json!({"status": "error", "message": "Missing: tree_json"}),
    };

    let tree: nexcore_dtree::node::DecisionTree = match serde_json::from_str(tree_json) {
        Ok(t) => t,
        Err(e) => return json!({"status": "error", "message": format!("Invalid tree_json: {e}")}),
    };

    let importances = feature_importance(&tree);
    let imp_json: Vec<Value> = importances
        .iter()
        .map(|fi| json!({"index": fi.index, "name": fi.name, "importance": fi.importance}))
        .collect();

    json!({"status": "ok", "importances": imp_json})
}

fn handle_prune(args: &Value) -> Value {
    use nexcore_dtree::prune::cost_complexity_prune;

    let tree_json = match args.get("tree_json").and_then(|v| v.as_str()) {
        Some(j) => j,
        None => return json!({"status": "error", "message": "Missing: tree_json"}),
    };
    let alpha = args.get("alpha").and_then(|v| v.as_f64()).unwrap_or(0.01);

    let mut tree: nexcore_dtree::node::DecisionTree = match serde_json::from_str(tree_json) {
        Ok(t) => t,
        Err(e) => return json!({"status": "error", "message": format!("Invalid tree_json: {e}")}),
    };

    let before = tree.stats().map(|s| s.n_nodes).unwrap_or(0);
    cost_complexity_prune(&mut tree, alpha);
    let after = tree.stats().map(|s| s.n_nodes).unwrap_or(0);
    let pruned_json = serde_json::to_string(&tree).unwrap_or_default();

    json!({
        "status": "ok",
        "tree_json": pruned_json,
        "depth": tree.stats().map(|s| s.depth).unwrap_or(0),
        "n_leaves": tree.stats().map(|s| s.n_leaves).unwrap_or(0),
        "nodes_removed": before.saturating_sub(after)
    })
}

fn handle_info(args: &Value) -> Value {
    let tree_json = match args.get("tree_json").and_then(|v| v.as_str()) {
        Some(j) => j,
        None => return json!({"status": "error", "message": "Missing: tree_json"}),
    };

    let tree: nexcore_dtree::node::DecisionTree = match serde_json::from_str(tree_json) {
        Ok(t) => t,
        Err(e) => return json!({"status": "error", "message": format!("Invalid tree_json: {e}")}),
    };

    let stats = tree.stats();
    json!({
        "status": "ok",
        "depth": stats.as_ref().map(|s| s.depth).unwrap_or(0),
        "n_leaves": stats.as_ref().map(|s| s.n_leaves).unwrap_or(0),
        "n_nodes": stats.as_ref().map(|s| s.n_nodes).unwrap_or(0),
        "feature_names": tree.feature_names()
    })
}
