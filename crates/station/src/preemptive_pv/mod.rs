//! Preemptive Pharmacovigilance — three-tier signal detection.
//!
//! Delegates to nexcore-preemptive-pv.

use nexcore_preemptive_pv::{gibbs, intervention, noise, reactive, GibbsParams, NoiseParams, ReportingCounts};
use serde_json::{Value, json};
use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("preemptive_pv_nexvigilant_com_")?.replace('_', "-");
    let result = match bare.as_str() {
        "reactive" => handle_reactive(args),
        "gibbs" => handle_gibbs(args),
        "noise" => handle_noise(args),
        "evaluate" => handle_evaluate(args),
        "intervention" => handle_intervention(args),
        "required-strength" => handle_required_strength(args),
        "omega-table" => handle_omega_table(),
        _ => return None,
    };
    Some(ToolCallResult {
        content: vec![ContentBlock::Text { text: serde_json::to_string_pretty(&result).unwrap_or_default() }],
        is_error: if result.get("status").and_then(|s| s.as_str()) == Some("error") { Some(true) } else { None },
    })
}

fn err(msg: &str) -> Value { json!({"status": "error", "message": msg}) }
fn gf(v: &Value, k: &str) -> Option<f64> { v.get(k).and_then(|v| v.as_f64()) }

fn handle_reactive(args: &Value) -> Value {
    let (a, b, c, d) = match (gf(args,"a"), gf(args,"b"), gf(args,"c"), gf(args,"d")) {
        (Some(a),Some(b),Some(c),Some(d)) => (a,b,c,d),
        _ => return err("Missing a, b, c, d"),
    };
    let counts = ReportingCounts::new(a, b, c, d);
    let threshold = gf(args, "threshold").unwrap_or(2.0);
    let strength = reactive::signal_strength(&counts);
    let detected = reactive::is_signal(&counts, threshold);
    json!({"status":"ok","tier":"reactive","signal_strength":strength,"threshold":threshold,"signal_detected":detected,"N":counts.total()})
}

fn handle_gibbs(args: &Value) -> Value {
    let dh = match gf(args, "delta_h_mechanism") { Some(v) => v, None => return err("Missing delta_h_mechanism") };
    let te = match gf(args, "t_exposure") { Some(v) => v, None => return err("Missing t_exposure") };
    let ds = match gf(args, "delta_s_information") { Some(v) => v, None => return err("Missing delta_s_information") };
    let params = GibbsParams::new(dh, te, ds);
    let dg = gibbs::delta_g(&params);
    let fav = gibbs::is_favorable(&params);
    let fs = gibbs::feasibility_score(&params);
    json!({"status":"ok","delta_g":dg,"favorable":fav,"feasibility_score":fs,"inputs":{"delta_h_mechanism":dh,"t_exposure":te,"delta_s_information":ds}})
}

fn handle_noise(args: &Value) -> Value {
    let rs = match gf(args, "r_stimulated") { Some(v) => v, None => return err("Missing r_stimulated") };
    let rb = match gf(args, "r_baseline") { Some(v) => v, None => return err("Missing r_baseline") };
    let k = gf(args, "k").unwrap_or(1.0);
    let params = NoiseParams::with_k(rs, rb, k);
    let e = noise::eta(&params);
    let ret = noise::signal_retention(&params);
    let org = noise::is_organic(&params);
    json!({"status":"ok","eta":e,"signal_retention":ret,"is_organic":org})
}

fn handle_evaluate(args: &Value) -> Value {
    let (a, b, c, d) = match (gf(args,"a"), gf(args,"b"), gf(args,"c"), gf(args,"d")) {
        (Some(a),Some(b),Some(c),Some(d)) => (a,b,c,d),
        _ => return err("Missing a, b, c, d"),
    };
    let counts = ReportingCounts::new(a, b, c, d);
    let dh = gf(args, "delta_h_mechanism").unwrap_or(5.0);
    let te = gf(args, "t_exposure").unwrap_or(1000.0);
    let ds = gf(args, "delta_s_information").unwrap_or(1.0);
    let gp = GibbsParams::new(dh, te, ds);
    let strength = reactive::signal_strength(&counts);
    let reactive_det = reactive::is_signal_default(&counts);
    let dg = gibbs::delta_g(&gp);
    let fav = gibbs::is_favorable(&gp);
    let tier = if fav && reactive_det { "preemptive" } else if reactive_det { "reactive" } else { "none" };
    json!({"status":"ok","reactive":{"signal_strength":strength,"detected":reactive_det},"preemptive":{"delta_g":dg,"favorable":fav},"tier":tier})
}

fn handle_intervention(args: &Value) -> Value {
    let vm = match gf(args, "signal_strength") { Some(v) => v, None => return err("Missing signal_strength") };
    let inh = match gf(args, "intervention_strength") { Some(v) => v, None => return err("Missing intervention_strength") };
    let km = gf(args, "k_m").unwrap_or(1.0);
    let ki = gf(args, "k_i").unwrap_or(1.0);
    let sub = gf(args, "substrate").unwrap_or(1.0);
    let inhibited = intervention::inhibited_rate(vm, sub, inh, km, ki);
    let uninhibited = intervention::uninhibited_rate(vm, sub, km);
    let reduction = if uninhibited > 0.0 { 1.0 - (inhibited / uninhibited) } else { 0.0 };
    json!({"status":"ok","uninhibited_rate":uninhibited,"inhibited_rate":inhibited,"reduction_fraction":reduction,"effective":reduction > 0.3})
}

fn handle_required_strength(args: &Value) -> Value {
    let vm = match gf(args, "signal_strength") { Some(v) => v, None => return err("Missing signal_strength") };
    let target = gf(args, "target_reduction").unwrap_or(0.5);
    let km = gf(args, "k_m").unwrap_or(1.0);
    let ki = gf(args, "k_i").unwrap_or(1.0);
    let sub = gf(args, "substrate").unwrap_or(1.0);
    let req = intervention::required_intervention_strength(vm, sub, target, km, ki);
    let achievable = req.is_some_and(|v| v.is_finite() && v > 0.0);
    json!({"status":"ok","required_strength":req,"target_reduction":target,"achievable":achievable})
}

fn handle_omega_table() -> Value {
    json!({"status":"ok","tiers":[
        {"seriousness":"NonSerious","score":0.2},
        {"seriousness":"Hospitalization","score":0.4},
        {"seriousness":"Disability","score":0.6},
        {"seriousness":"LifeThreatening","score":0.8},
        {"seriousness":"Fatal","score":1.0}
    ]})
}
