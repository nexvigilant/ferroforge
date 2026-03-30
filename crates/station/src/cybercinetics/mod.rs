//! Cybercinetics — Rust-native handler for NexVigilant Station.
//! Routes `cybercinetics_nexvigilant_com_*` to `nexcore-cybercinetics`.

use nexcore_cybercinetics::{BindingRegistry, Controller, HookBinding, Verdict};
use serde_json::{Value, json};
use tracing::info;
use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("cybercinetics_nexvigilant_com_")?.replace('_', "-");
    let result = match bare.as_str() {
        "controller-tick" => handle_controller_tick(args),
        "registry-status" => handle_registry_status(args),
        "decay-all" => handle_decay_all(args),
        _ => return None,
    };
    info!(tool = tool_name, "Handled natively (cybercinetics)");
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

fn ok(mut v: Value) -> Value {
    if let Some(m) = v.as_object_mut() {
        m.insert("status".into(), json!("ok"));
    }
    v
}

fn err(msg: &str) -> Value {
    json!({ "status": "error", "error": msg })
}

fn handle_controller_tick(args: &Value) -> Value {
    let nu_rate = match args.get("nu_rate").and_then(|v| v.as_f64()) {
        Some(v) => v,
        None => return err("missing required: nu_rate (number)"),
    };
    let nu_floor = match args.get("nu_floor").and_then(|v| v.as_f64()) {
        Some(v) => v,
        None => return err("missing required: nu_floor (number)"),
    };
    let rho_ceiling = args
        .get("rho_ceiling")
        .and_then(|v| v.as_u64())
        .unwrap_or(3) as u8;
    let f_min = args.get("f_min").and_then(|v| v.as_f64()).unwrap_or(0.80);
    let rho_depth = args
        .get("rho_depth")
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as u8;

    let mut ctrl: Controller<String> =
        Controller::new("tick".to_string(), nu_rate, nu_floor, rho_ceiling, f_min);

    for _ in 0..rho_depth {
        ctrl.observe();
    }

    if let Some(links) = args.get("causal_links").and_then(|v| v.as_array()) {
        for link in links {
            let cause = link
                .get("cause")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown");
            let effect = link
                .get("effect")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown");
            let fidelity = link.get("fidelity").and_then(|v| v.as_f64()).unwrap_or(1.0);
            ctrl.arrow.push(cause, effect, fidelity);
        }
    }

    let verdict = ctrl.tick();

    ok(json!({
        "verdict": verdict.to_string(),
        "stable": verdict == Verdict::Stable,
        "nu": {
            "rate": ctrl.nu.rate,
            "floor": ctrl.nu.floor,
            "health_ratio": ctrl.nu.health_ratio(),
            "decayed": ctrl.nu.is_decayed(),
        },
        "rho": {
            "depth": ctrl.rho.depth,
            "ceiling": ctrl.rho.ceiling,
            "saturated": ctrl.rho.is_saturated(),
        },
        "arrow": {
            "hops": ctrl.arrow.len(),
            "f_total": ctrl.arrow.f_total(),
            "f_min": f_min,
            "below_threshold": !ctrl.arrow.is_empty() && ctrl.arrow.f_total() < f_min,
            "weakest": ctrl.arrow.weakest().map(|w| json!({
                "cause": w.cause,
                "effect": w.effect,
                "fidelity": w.fidelity,
            })),
        },
        "primitive_grounding": "\u{2202}(\u{2192}(\u{03bd}, \u{03c2}, \u{03c1}))",
    }))
}

fn handle_registry_status(args: &Value) -> Value {
    let bindings = match args.get("bindings").and_then(|v| v.as_array()) {
        Some(b) => b,
        None => return err("missing required: bindings (array)"),
    };
    let threshold = args
        .get("degraded_threshold")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.80);

    let ctrl: Controller<String> =
        Controller::new("registry".to_string(), 1.0, 0.1, 3, 0.80);
    let mut reg = BindingRegistry::new(ctrl);

    for b in bindings {
        let hook = b.get("hook").and_then(|v| v.as_str()).unwrap_or("unknown");
        let event = b.get("event").and_then(|v| v.as_str()).unwrap_or("unknown");
        let fidelity = b.get("fidelity").and_then(|v| v.as_f64()).unwrap_or(1.0);
        let mut binding = HookBinding::new(hook, "station", event);
        if fidelity < 1.0 {
            binding.fidelity = fidelity.clamp(0.0, 1.0);
        }
        reg.register(binding);
    }

    let degraded: Vec<_> = reg
        .degraded_bindings(threshold)
        .iter()
        .map(|b| {
            json!({
                "hook": b.hook,
                "event": b.event,
                "fidelity": b.fidelity,
            })
        })
        .collect();

    ok(json!({
        "total_bindings": reg.bindings.len(),
        "aggregate_fidelity": reg.aggregate_fidelity(),
        "degraded_count": degraded.len(),
        "degraded_threshold": threshold,
        "degraded_bindings": degraded,
    }))
}

fn handle_decay_all(args: &Value) -> Value {
    let bindings = match args.get("bindings").and_then(|v| v.as_array()) {
        Some(b) => b,
        None => return err("missing required: bindings (array)"),
    };
    let factor = match args.get("factor").and_then(|v| v.as_f64()) {
        Some(f) => f,
        None => return err("missing required: factor (number)"),
    };
    let floor = match args.get("floor").and_then(|v| v.as_f64()) {
        Some(f) => f,
        None => return err("missing required: floor (number)"),
    };

    let ctrl: Controller<String> =
        Controller::new("decay".to_string(), 1.0, 0.1, 3, 0.80);
    let mut reg = BindingRegistry::new(ctrl);

    for b in bindings {
        let hook = b.get("hook").and_then(|v| v.as_str()).unwrap_or("unknown");
        let event = b.get("event").and_then(|v| v.as_str()).unwrap_or("unknown");
        let fidelity = b.get("fidelity").and_then(|v| v.as_f64()).unwrap_or(1.0);
        let mut binding = HookBinding::new(hook, "station", event);
        binding.fidelity = fidelity.clamp(0.0, 1.0);
        reg.register(binding);
    }

    let count = reg.decay_all(factor, floor);

    let after: Vec<_> = reg
        .bindings
        .iter()
        .map(|b| {
            json!({
                "hook": b.hook,
                "event": b.event,
                "fidelity": b.fidelity,
            })
        })
        .collect();

    ok(json!({
        "degraded_count": count,
        "bindings_after": after,
    }))
}
