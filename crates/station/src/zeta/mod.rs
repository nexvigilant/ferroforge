//! Zeta — Riemann zeta function computation.
//! Routes `zeta_nexvigilant_com_*`. Delegates to `nexcore-zeta`.

use nexcore_zeta::{zeta, zeros, statistics, riemann_siegel};
use stem_complex::Complex;
use serde_json::{Value, json};
use tracing::info;
use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("zeta_nexvigilant_com_")?.replace('_', "-");
    let result = match bare.as_str() {
        "evaluate" => handle_evaluate(args),
        "find-zeros" => handle_find_zeros(args),
        "verify-rh" => handle_verify_rh(args),
        "z-function" => handle_z_function(args),
        "gue-comparison" => handle_gue_comparison(args),
        _ => return None,
    };
    info!(tool = tool_name, "Handled natively (zeta)");
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
    let mut o = v;
    if let Some(m) = o.as_object_mut() { m.insert("status".into(), json!("ok")); }
    o
}
fn err(msg: &str) -> Value { json!({ "status": "error", "error": msg }) }
fn r6(v: f64) -> f64 { (v * 1_000_000.0).round() / 1_000_000.0 }

fn get_f64(a: &Value, k: &str) -> Option<f64> { a.get(k).and_then(|v| v.as_f64()) }

fn handle_evaluate(args: &Value) -> Value {
    let sigma = match get_f64(args, "sigma") { Some(v) => v, None => return err("missing: sigma") };
    let t = match get_f64(args, "t") { Some(v) => v, None => return err("missing: t") };

    let s = Complex::new(sigma, t);
    match zeta::zeta(s) {
        Ok(result) => {
            let mag = (result.re * result.re + result.im * result.im).sqrt();
            ok(json!({
                "real": r6(result.re),
                "imag": r6(result.im),
                "magnitude": r6(mag),
                "input": { "sigma": sigma, "t": t },
            }))
        }
        Err(e) => err(&format!("{e}")),
    }
}

fn handle_find_zeros(args: &Value) -> Value {
    let t_low = match get_f64(args, "t_low") { Some(v) => v, None => return err("missing: t_low") };
    let t_high = match get_f64(args, "t_high") { Some(v) => v, None => return err("missing: t_high") };
    let step = get_f64(args, "step").unwrap_or(0.5);

    match zeros::find_zeros_bracket(t_low, t_high, step) {
        Ok(found) => {
            let zero_list: Vec<Value> = found.iter().map(|z| json!({
                "ordinal": z.ordinal,
                "t": r6(z.t),
                "z_value": r6(z.z_value),
                "on_critical_line": z.on_critical_line,
            })).collect();
            let count = zero_list.len();
            ok(json!({ "zeros": zero_list, "count": count }))
        }
        Err(e) => err(&format!("{e}")),
    }
}

fn handle_verify_rh(args: &Value) -> Value {
    let height = match get_f64(args, "height") { Some(v) => v, None => return err("missing: height") };
    let step = get_f64(args, "step").unwrap_or(0.1);

    match zeros::verify_rh_to_height(height, step) {
        Ok(v) => ok(json!({
            "rh_holds": v.all_on_critical_line,
            "zeros_found": v.found_zeros,
            "zeros_expected": r6(v.expected_zeros),
            "height": v.height,
        })),
        Err(e) => err(&format!("{e}")),
    }
}

fn handle_z_function(args: &Value) -> Value {
    let t = match get_f64(args, "t") { Some(v) => v, None => return err("missing: t") };

    match riemann_siegel::riemann_siegel_z(t) {
        Ok(z) => {
            let theta = riemann_siegel::riemann_siegel_theta(t);
            ok(json!({
                "z_value": r6(z),
                "theta": r6(theta),
                "t": t,
            }))
        }
        Err(e) => err(&format!("{e}")),
    }
}

fn handle_gue_comparison(args: &Value) -> Value {
    let t_low = match get_f64(args, "t_low") { Some(v) => v, None => return err("missing: t_low") };
    let t_high = match get_f64(args, "t_high") { Some(v) => v, None => return err("missing: t_high") };

    let found = match zeros::find_zeros_bracket(t_low, t_high, 0.5) {
        Ok(z) => z,
        Err(e) => return err(&format!("Zero finding failed: {e}")),
    };

    if found.len() < 3 {
        return err("Need at least 3 zeros for GUE comparison. Widen the range.");
    }

    match statistics::compare_to_gue(&found) {
        Ok(cmp) => ok(json!({
            "zeros_analyzed": found.len(),
            "n_spacings": cmp.n_spacings,
            "mean_spacing": r6(cmp.mean_spacing),
            "variance": r6(cmp.variance),
            "gue_predicted_variance": r6(cmp.gue_predicted_variance),
            "pair_correlation_mae": r6(cmp.pair_correlation_mae),
        })),
        Err(e) => err(&format!("{e}")),
    }
}
