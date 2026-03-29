//! Energy — Token budget management via ATP/ADP biochemistry.
//!
//! Rust-native Station handler calling nexcore-energy directly.

use crate::protocol::{ContentBlock, ToolCallResult};
use serde_json::{Value, json};

/// Try to handle an energy.nexvigilant.com tool call.
pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("energy_nexvigilant_com_")?;
    let result = match bare {
        "compute-energy-charge" => handle_compute_ec(args),
        "classify-regime" => handle_classify_regime(args),
        "recommend-strategy" => handle_recommend_strategy(args),
        "analyze-waste" => handle_analyze_waste(args),
        "temporal-metrics" => handle_temporal_metrics(args),
        "classify-waste" => handle_classify_waste(args),
        _ => return None,
    };
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

fn pool_from_args(args: &Value) -> Option<nexcore_energy::TokenPool> {
    let t_atp = args.get("t_atp")?.as_u64()?;
    let t_adp = args.get("t_adp")?.as_u64()?;
    let t_amp = args.get("t_amp")?.as_u64()?;
    Some(nexcore_energy::TokenPool {
        t_atp,
        t_adp,
        t_amp,
    })
}

fn handle_compute_ec(args: &Value) -> Value {
    let Some(pool) = pool_from_args(args) else {
        return json!({ "status": "error", "message": "Required: t_atp, t_adp, t_amp (integers)" });
    };
    let ec = pool.energy_charge();
    let regime = pool.regime();
    let op = nexcore_energy::Operation::builder("station_query").cost(1000).value(1.0).build();
    let strategy = nexcore_energy::decide(&pool, &op);
    json!({
        "status": "ok",
        "energy_charge": (ec * 10000.0).round() / 10000.0,
        "regime": format!("{regime:?}"),
        "regime_label": regime.label(),
        "strategy": format!("{strategy:?}"),
        "strategy_label": strategy.label(),
        "allows_expensive": regime.allows_expensive(),
        "total_tokens": pool.total(),
    })
}

fn handle_classify_regime(args: &Value) -> Value {
    let Some(ec) = args.get("energy_charge").and_then(|v| v.as_f64()) else {
        return json!({ "status": "error", "message": "Required: energy_charge (number 0-1)" });
    };
    let regime = nexcore_energy::Regime::from_ec(ec);
    json!({
        "status": "ok",
        "regime": format!("{regime:?}"),
        "label": regime.label(),
        "allows_expensive": regime.allows_expensive(),
    })
}

fn handle_recommend_strategy(args: &Value) -> Value {
    let Some(pool) = pool_from_args(args) else {
        return json!({ "status": "error", "message": "Required: t_atp, t_adp, t_amp (integers)" });
    };
    let coupling = args.get("coupling_ratio").and_then(|v| v.as_f64()).unwrap_or(1.0);
    let op = nexcore_energy::Operation::builder("station_query")
        .cost(1000)
        .value(coupling * 1000.0)
        .build();
    let strategy = nexcore_energy::decide(&pool, &op);
    let system = nexcore_energy::EnergySystem::for_strategy(strategy);
    json!({
        "status": "ok",
        "energy_charge": (pool.energy_charge() * 10000.0).round() / 10000.0,
        "regime": format!("{:?}", pool.regime()),
        "strategy": format!("{strategy:?}"),
        "strategy_label": strategy.label(),
        "cost_multiplier": strategy.cost_multiplier(),
        "energy_system": format!("{system}"),
        "yield_per_unit": system.yield_per_unit(),
    })
}

fn handle_analyze_waste(args: &Value) -> Value {
    let Some(pool) = pool_from_args(args) else {
        return json!({ "status": "error", "message": "Required: t_atp, t_adp, t_amp (integers)" });
    };
    let avg_cost = args.get("avg_cost_per_op").and_then(|v| v.as_u64()).unwrap_or(1000);
    json!({
        "status": "ok",
        "waste_ratio": (pool.waste_ratio() * 10000.0).round() / 10000.0,
        "burn_rate": (pool.burn_rate() * 10000.0).round() / 10000.0,
        "lifespan_efficiency": (pool.lifespan_efficiency() * 10000.0).round() / 10000.0,
        "estimated_remaining_ops": pool.estimated_remaining_ops(avg_cost),
        "total_tokens": pool.total(),
        "t_atp": pool.t_atp,
        "t_adp": pool.t_adp,
        "t_amp": pool.t_amp,
    })
}

fn handle_temporal_metrics(args: &Value) -> Value {
    let Some(pool) = pool_from_args(args) else {
        return json!({ "status": "error", "message": "Required: t_atp, t_adp, t_amp (integers)" });
    };
    let total_value = args.get("total_value").and_then(|v| v.as_f64()).unwrap_or(1.0);
    json!({
        "status": "ok",
        "metabolic_age": (pool.metabolic_age() * 10000.0).round() / 10000.0,
        "chronological_age": (pool.chronological_age() * 10000.0).round() / 10000.0,
        "age_gap": (pool.age_gap() * 10000.0).round() / 10000.0,
        "lifespan_efficiency": (pool.lifespan_efficiency() * 10000.0).round() / 10000.0,
        "coupling_efficiency": (pool.coupling_efficiency(total_value) * 10000.0).round() / 10000.0,
        "energy_charge": (pool.energy_charge() * 10000.0).round() / 10000.0,
    })
}

fn handle_classify_waste(args: &Value) -> Value {
    let Some(waste_str) = args.get("waste_type").and_then(|v| v.as_str()) else {
        return json!({ "status": "error", "message": "Required: waste_type (string)" });
    };
    let waste = match waste_str {
        "futile_cycling" => nexcore_energy::WasteClass::FutileCycling,
        "uncoupled" => nexcore_energy::WasteClass::Uncoupled,
        "heat_loss" => nexcore_energy::WasteClass::HeatLoss,
        "substrate_cycling" => nexcore_energy::WasteClass::SubstrateCycling,
        "retry" => nexcore_energy::WasteClass::Retry,
        _ => return json!({
            "status": "error",
            "message": "Unknown waste_type. Valid: futile_cycling, uncoupled, heat_loss, substrate_cycling, retry"
        }),
    };
    json!({
        "status": "ok",
        "waste_class": format!("{waste:?}"),
        "label": waste.label(),
        "prevention": waste.prevention(),
    })
}
