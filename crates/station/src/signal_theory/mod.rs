//! Signal Theory — Universal Signal Detection Framework.
//! Delegates to nexcore-signal-theory.

use nexcore_signal_theory::prelude::*;
use serde_json::{Value, json};
use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("signal_theory_nexvigilant_com_")?.replace('_', "-");
    let result = match bare.as_str() {
        "get-axioms" => axioms(),
        "get-theorems" => theorems(),
        "detect" => detect(args),
        "decision-matrix" => decision_matrix(args),
        "conservation-check" => conservation_check(args),
        "pipeline" => pipeline(args),
        "cascade" => cascade(args),
        "parallel" => parallel(args),
        _ => return None,
    };
    Some(ToolCallResult {
        content: vec![ContentBlock::Text { text: serde_json::to_string_pretty(&result).unwrap_or_default() }],
        is_error: if result.get("status").and_then(|s| s.as_str()) == Some("error") { Some(true) } else { None },
    })
}

fn err(msg: &str) -> Value { json!({"status": "error", "message": msg}) }
fn gf(v: &Value, k: &str) -> Option<f64> { v.get(k).and_then(|v| v.as_f64()) }
fn gu(v: &Value, k: &str) -> Option<u64> { v.get(k).and_then(|v| v.as_u64()) }
fn gs<'a>(v: &'a Value, k: &str) -> Option<&'a str> { v.get(k).and_then(|v| v.as_str()) }

fn axioms() -> Value {
    let data: [(&str, &str, &str, &str); 6] = [
        ("A1","Data Generation","ν",<A1DataGeneration<1000> as Axiom>::statement()),
        ("A2","Noise Dominance","∅",<A2NoiseDominance as Axiom>::statement()),
        ("A3","Signal Existence","∃",<A3SignalExistence as Axiom>::statement()),
        ("A4","Boundary Requirement","∂",<A4BoundaryRequirement as Axiom>::statement()),
        ("A5","Disproportionality","κ",<A5Disproportionality as Axiom>::statement()),
        ("A6","Causal Inference","→",<A6CausalInference as Axiom>::statement()),
    ];
    json!({"status":"ok","axiom_count":6,"thesis":"All detection is boundary drawing","axioms":data.iter().map(|(id,n,p,s)|json!({"id":id,"name":n,"primitive":p,"statement":s})).collect::<Vec<_>>()})
}

fn theorems() -> Value {
    let reg = TheoremRegistry::build();
    json!({"status":"ok","theorem_count":reg.theorems.len(),"theorems":reg.theorems.iter().map(|t|json!({"id":t.id,"name":t.name,"statement":t.statement,"prerequisites":t.prerequisites})).collect::<Vec<_>>()})
}

fn detect(args: &Value) -> Value {
    let obs = match gf(args, "observed") { Some(v) => v, None => return err("Missing observed") };
    let exp = match gf(args, "expected") { Some(v) => v, None => return err("Missing expected") };
    let thr = gf(args, "threshold").unwrap_or(2.0);
    let bnd = FixedBoundary::above(thr, "detection");
    let ratio = Ratio::from_counts(obs, exp);
    let (rv, det, str_lvl) = match ratio {
        Some(r) => (Some(r.0), bnd.evaluate(r.0), SignalStrengthLevel::from_ratio(r.0)),
        None => (None, false, SignalStrengthLevel::None),
    };
    let diff = Difference::from_counts(obs, exp);
    json!({"status":"ok","observed":obs,"expected":exp,"threshold":thr,"ratio":rv,"difference":diff.0,"detected":det,"strength":format!("{:?}",str_lvl)})
}

fn decision_matrix(args: &Value) -> Value {
    let (h,m,fa,cr) = (gu(args,"hits").unwrap_or(0), gu(args,"misses").unwrap_or(0), gu(args,"false_alarms").unwrap_or(0), gu(args,"correct_rejections").unwrap_or(0));
    let dm = DecisionMatrix::new(h,m,fa,cr);
    let dp = DPrime::from_matrix(&dm);
    let bias = ResponseBias::from_matrix(&dm);
    json!({"status":"ok","matrix":{"hits":h,"misses":m,"false_alarms":fa,"correct_rejections":cr,"total":dm.total()},"metrics":{"sensitivity":dm.sensitivity(),"specificity":dm.specificity(),"ppv":dm.ppv(),"npv":dm.npv(),"accuracy":dm.accuracy(),"f1_score":dm.f1_score(),"mcc":dm.mcc()},"sdt":{"d_prime":dp.0,"level":dp.level(),"bias":bias.0,"bias_description":bias.description()}})
}

fn conservation_check(args: &Value) -> Value {
    let (h,m,fa,cr) = (gu(args,"hits").unwrap_or(0), gu(args,"misses").unwrap_or(0), gu(args,"false_alarms").unwrap_or(0), gu(args,"correct_rejections").unwrap_or(0));
    let dm = DecisionMatrix::new(h,m,fa,cr);
    let mut report = ConservationReport::new();
    let et = gu(args, "expected_total").unwrap_or(h+m+fa+cr);
    report.add("L1", L1TotalCountConservation.verify(&dm, et));
    if let Some(mdp) = gf(args, "max_dprime") {
        report.add("L4", L4InformationConservation.verify(DPrime::from_matrix(&dm).0, mdp));
    }
    json!({"status":"ok","all_satisfied":report.all_satisfied(),"laws_checked":report.results.len(),"violations":report.violations().iter().map(|(id,msg)|json!({"law":id,"violation":msg})).collect::<Vec<_>>()})
}

fn pipeline(args: &Value) -> Value {
    let value = match gf(args, "value") { Some(v) => v, None => return err("Missing value") };
    let label = gs(args, "label").unwrap_or("pipeline");
    let stages = match args.get("stages").and_then(|v| v.as_array()) { Some(s) => s, None => return err("Missing stages") };
    let mut results = Vec::new();
    let mut all_passed = true;
    let mut first_fail: Option<String> = None;
    for (i, s) in stages.iter().enumerate() {
        let name = gs(s,"name").unwrap_or("unnamed");
        let thr = gf(s,"threshold").unwrap_or(0.0);
        let passed = FixedBoundary::above(thr, "d").evaluate(value);
        if !passed && first_fail.is_none() { first_fail = Some(name.to_string()); all_passed = false; }
        results.push(json!({"stage":i+1,"name":name,"threshold":thr,"passed":passed}));
    }
    json!({"status":"ok","label":label,"value":value,"all_passed":all_passed,"first_failure":first_fail,"stages":results,"verdict":if all_passed {"SIGNAL_DETECTED"} else {"NOT_DETECTED"}})
}

fn cascade(args: &Value) -> Value {
    let value = match gf(args, "value") { Some(v) => v, None => return err("Missing value") };
    let thresholds: Vec<f64> = args.get("thresholds").and_then(|v|v.as_array()).map(|a|a.iter().filter_map(|v|v.as_f64()).collect()).unwrap_or_default();
    let labels: Vec<&str> = args.get("labels").and_then(|v|v.as_array()).map(|a|a.iter().filter_map(|v|v.as_str()).collect()).unwrap_or_default();
    if thresholds.len() != labels.len() { return err("thresholds and labels must match"); }
    let mut highest: Option<usize> = None;
    let levels: Vec<_> = thresholds.iter().zip(labels.iter()).enumerate().map(|(i,(t,l))| {
        let exc = FixedBoundary::above(*t, "c").evaluate(value);
        if exc { highest = Some(i); }
        json!({"level":i+1,"label":l,"threshold":t,"exceeded":exc})
    }).collect();
    json!({"status":"ok","value":value,"levels":levels,"highest_level":highest.map(|l|l+1),"highest_label":highest.and_then(|l|labels.get(l)),"verdict":if highest.is_some(){"SIGNAL_DETECTED"}else{"NOT_DETECTED"}})
}

fn parallel(args: &Value) -> Value {
    let value = match gf(args, "value") { Some(v) => v, None => return err("Missing value") };
    let t1 = gf(args,"threshold_1").unwrap_or(2.0);
    let t2 = gf(args,"threshold_2").unwrap_or(2.0);
    let mode = gs(args,"mode").unwrap_or("both");
    let d1 = FixedBoundary::above(t1,"d1").evaluate(value);
    let d2 = FixedBoundary::above(t2,"d2").evaluate(value);
    let combined = if mode == "either" { d1 || d2 } else { d1 && d2 };
    json!({"status":"ok","value":value,"mode":mode,"detector_1":{"threshold":t1,"detected":d1},"detector_2":{"threshold":t2,"detected":d2},"combined":combined,"verdict":if combined{"SIGNAL_DETECTED"}else{"NOT_DETECTED"}})
}
