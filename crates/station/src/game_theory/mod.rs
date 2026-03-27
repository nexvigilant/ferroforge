//! Game Theory — Rust-native handler for NexVigilant Station.
//!
//! Routes `game-theory_nexvigilant_com_*` tool calls. Pure math, no crate deps.

use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

const EPS: f64 = 1.0e-9;

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("game-theory_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "nash-2x2" => handle_nash_2x2(args),
        "payoff-matrix" => handle_payoff_matrix(args),
        "nash-solve" => handle_nash_solve(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (game-theory)");

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

fn to_2x2(arr: &Value) -> Option<[[f64; 2]; 2]> {
    let rows = arr.as_array()?;
    if rows.len() != 2 { return None; }
    let r0 = rows[0].as_array()?;
    let r1 = rows[1].as_array()?;
    if r0.len() != 2 || r1.len() != 2 { return None; }
    Some([
        [r0[0].as_f64()?, r0[1].as_f64()?],
        [r1[0].as_f64()?, r1[1].as_f64()?],
    ])
}

fn handle_nash_2x2(args: &Value) -> Value {
    let row = match args.get("row_payoffs").and_then(|v| to_2x2(v)) {
        Some(m) => m,
        None => return err("row_payoffs must be a 2x2 matrix [[a,b],[c,d]]"),
    };
    let col = match args.get("col_payoffs").and_then(|v| to_2x2(v)) {
        Some(m) => m,
        None => return err("col_payoffs must be a 2x2 matrix [[e,f],[g,h]]"),
    };

    // Pure strategy equilibria
    let mut pure = Vec::new();
    for i in 0..2 {
        for j in 0..2 {
            let row_best = row[i][j] + EPS >= row[1 - i][j];
            let col_best = col[i][j] + EPS >= col[i][1 - j];
            if row_best && col_best {
                pure.push(json!({
                    "row_strategy": if i == 0 { "R1" } else { "R2" },
                    "col_strategy": if j == 0 { "C1" } else { "C2" },
                    "payoffs": { "row": row[i][j], "col": col[i][j] }
                }));
            }
        }
    }

    // Mixed strategy
    let (a, b, c, d) = (row[0][0], row[0][1], row[1][0], row[1][1]);
    let (e, _f, g, h) = (col[0][0], col[0][1], col[1][0], col[1][1]);

    let denom_row = a - b - c + d;
    let denom_col = e - col[0][1] - g + h;

    let mut mixed = None;
    let mut warnings = Vec::new();

    if denom_row.abs() < EPS {
        warnings.push("Row denominator near zero; mixed strategy may be undefined");
    }
    if denom_col.abs() < EPS {
        warnings.push("Column denominator near zero; mixed strategy may be undefined");
    }

    if denom_row.abs() >= EPS && denom_col.abs() >= EPS {
        let q = (d - b) / denom_row;
        let p = (h - g) / denom_col;

        if (-EPS..=1.0 + EPS).contains(&p) && (-EPS..=1.0 + EPS).contains(&q) {
            let pc = p.clamp(0.0, 1.0);
            let qc = q.clamp(0.0, 1.0);
            mixed = Some(json!({
                "row_plays_R1_prob": pc, "col_plays_C1_prob": qc,
                "expected_payoff": {
                    "row": a * qc + b * (1.0 - qc),
                    "col": e * pc + g * (1.0 - pc),
                }
            }));
        }
    }

    ok(json!({
        "pure_equilibria": pure, "mixed_equilibrium": mixed, "warnings": warnings,
    }))
}

fn flat_to_matrix(values: &[f64], rows: usize, cols: usize) -> Option<Vec<Vec<f64>>> {
    if rows == 0 || cols == 0 || values.len() != rows * cols { return None; }
    Some(values.chunks(cols).map(|c| c.to_vec()).collect())
}

fn handle_payoff_matrix(args: &Value) -> Value {
    let values: Vec<f64> = match args.get("values").and_then(|v| v.as_array()) {
        Some(arr) => arr.iter().filter_map(|v| v.as_f64()).collect(),
        None => return err("missing 'values' array"),
    };
    let rows = args.get("rows").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
    let cols = args.get("cols").and_then(|v| v.as_u64()).unwrap_or(0) as usize;

    let matrix = match flat_to_matrix(&values, rows, cols) {
        Some(m) => m,
        None => return err(&format!("values length {} != rows({}) × cols({})", values.len(), rows, cols)),
    };

    // Best responses per row and column
    let row_best: Vec<_> = matrix.iter().enumerate().map(|(r, row)| {
        let max = row.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let cols: Vec<usize> = row.iter().enumerate().filter(|&(_, v)| (*v - max).abs() < EPS).map(|(c, _)| c).collect();
        json!({ "row": r, "best_columns": cols, "max_payoff": max })
    }).collect();

    let col_best: Vec<_> = (0..cols).map(|c| {
        let col_vals: Vec<f64> = (0..rows).map(|r| matrix[r][c]).collect();
        let max = col_vals.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let best_rows: Vec<usize> = col_vals.iter().enumerate().filter(|&(_, v)| (*v - max).abs() < EPS).map(|(r, _)| r).collect();
        json!({ "column": c, "best_rows": best_rows, "max_payoff": max })
    }).collect();

    // Minimax: row player maximizes minimum payoff
    let row_mins: Vec<f64> = matrix.iter().map(|row| row.iter().cloned().fold(f64::INFINITY, f64::min)).collect();
    let minimax = row_mins.iter().cloned().fold(f64::NEG_INFINITY, f64::max);

    ok(json!({
        "matrix": matrix, "rows": rows, "cols": cols,
        "row_best_responses": row_best, "col_best_responses": col_best,
        "minimax_value": minimax,
    }))
}

fn handle_nash_solve(args: &Value) -> Value {
    let row_vals: Vec<f64> = match args.get("row_values").and_then(|v| v.as_array()) {
        Some(arr) => arr.iter().filter_map(|v| v.as_f64()).collect(),
        None => return err("missing 'row_values'"),
    };
    let col_vals: Vec<f64> = match args.get("col_values").and_then(|v| v.as_array()) {
        Some(arr) => arr.iter().filter_map(|v| v.as_f64()).collect(),
        None => return err("missing 'col_values'"),
    };
    let rows = args.get("rows").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
    let cols = args.get("cols").and_then(|v| v.as_u64()).unwrap_or(0) as usize;

    let row_matrix = match flat_to_matrix(&row_vals, rows, cols) {
        Some(m) => m,
        None => return err("row_values length mismatch"),
    };
    let col_matrix = match flat_to_matrix(&col_vals, rows, cols) {
        Some(m) => m,
        None => return err("col_values length mismatch"),
    };

    // Find pure Nash equilibria
    let mut equilibria = Vec::new();
    for r in 0..rows {
        for c in 0..cols {
            // Check if r is best response to c
            let row_best = (0..rows).all(|r2| row_matrix[r][c] + EPS >= row_matrix[r2][c]);
            // Check if c is best response to r
            let col_best = (0..cols).all(|c2| col_matrix[r][c] + EPS >= col_matrix[r][c2]);
            if row_best && col_best {
                equilibria.push(json!({
                    "row": r, "col": c,
                    "row_payoff": row_matrix[r][c], "col_payoff": col_matrix[r][c],
                }));
            }
        }
    }

    // Dominant strategies
    let row_dominant = (0..rows).find(|&r| {
        (0..rows).filter(|&r2| r2 != r).all(|r2| {
            (0..cols).all(|c| row_matrix[r][c] + EPS >= row_matrix[r2][c])
        })
    });
    let col_dominant = (0..cols).find(|&c| {
        (0..cols).filter(|&c2| c2 != c).all(|c2| {
            (0..rows).all(|r| col_matrix[r][c] + EPS >= col_matrix[r][c2])
        })
    });

    ok(json!({
        "rows": rows, "cols": cols,
        "pure_equilibria": equilibria,
        "row_dominant_strategy": row_dominant,
        "col_dominant_strategy": col_dominant,
        "equilibrium_count": equilibria.len(),
    }))
}
