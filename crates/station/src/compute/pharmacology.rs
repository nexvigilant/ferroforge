//! Pharmacokinetics computation tools — AUC, clearance, half-life, steady state.

use std::f64::consts::LN_2;
use serde_json::{Value, json};

pub fn handle(bare_name: &str, args: &Value) -> Option<Value> {
    match bare_name {
        "pk-auc" => Some(pk_auc(args)),
        "pk-clearance" => Some(pk_clearance(args)),
        "pk-half-life" => Some(pk_half_life(args)),
        "pk-steady-state" => Some(pk_steady_state(args)),
        "pk-michaelis-menten" => Some(pk_michaelis_menten(args)),
        "pk-volume-distribution" => Some(pk_vd(args)),
        "pk-bioavailability" => Some(pk_bioavailability(args)),
        "pk-dose-adjustment" => Some(pk_dose_adjustment(args)),
        _ => None,
    }
}

fn get_f64(args: &Value, key: &str) -> Option<f64> {
    args.get(key).and_then(|v| v.as_f64())
}

fn err(msg: &str) -> Value {
    json!({"status": "error", "message": msg})
}

/// AUC by trapezoidal rule from concentration-time data.
fn pk_auc(args: &Value) -> Value {
    let points = match args.get("points").and_then(|v| v.as_array()) {
        Some(a) if a.len() >= 2 => a,
        _ => return err("Need at least 2 concentration-time points"),
    };

    let mut data: Vec<(f64, f64)> = points
        .iter()
        .filter_map(|v| {
            let t = v.get("time").and_then(|x| x.as_f64())?;
            let c = v.get("concentration").and_then(|x| x.as_f64())?;
            Some((t, c))
        })
        .collect();
    data.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));

    if data.len() < 2 {
        return err("Need at least 2 valid data points");
    }

    let mut auc = 0.0_f64;
    for i in 1..data.len() {
        let dt = data[i].0 - data[i - 1].0;
        let avg_c = (data[i].1 + data[i - 1].1) / 2.0;
        auc += dt * avg_c;
    }

    // AUC extrapolation to infinity (if ke provided)
    let auc_inf = if let Some(ke) = get_f64(args, "ke") {
        let c_last = data.last().map(|(_, c)| *c).unwrap_or(0.0);
        if ke > 0.0 { auc + c_last / ke } else { auc }
    } else {
        auc
    };

    let cmax = data.iter().map(|(_, c)| *c).fold(0.0_f64, f64::max);
    let tmax = data.iter().max_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal))
        .map(|(t, _)| *t).unwrap_or(0.0);

    json!({
        "status": "ok",
        "method": "trapezoidal_auc",
        "auc_0_t": auc,
        "auc_0_inf": auc_inf,
        "cmax": cmax,
        "tmax": tmax,
        "data_points": data.len(),
        "unit": "concentration × time"
    })
}

/// CL = Dose / AUC
fn pk_clearance(args: &Value) -> Value {
    let dose = match get_f64(args, "dose") {
        Some(v) if v > 0.0 => v,
        _ => return err("Missing or non-positive 'dose'"),
    };
    let auc = match get_f64(args, "auc") {
        Some(v) if v > 0.0 => v,
        _ => return err("Missing or non-positive 'auc'"),
    };
    let bioavailability = get_f64(args, "bioavailability").unwrap_or(1.0);

    let cl = (dose * bioavailability) / auc;

    json!({
        "status": "ok",
        "method": "clearance",
        "clearance": cl,
        "dose": dose,
        "auc": auc,
        "bioavailability": bioavailability,
        "unit": "volume/time"
    })
}

/// t½ = 0.693 / ke
fn pk_half_life(args: &Value) -> Value {
    // Can compute from ke or from two concentration points
    if let Some(ke) = get_f64(args, "ke") {
        if ke <= 0.0 { return err("ke must be positive"); }
        let t_half = LN_2 / ke;
        return json!({
            "status": "ok",
            "method": "half_life_from_ke",
            "half_life": t_half,
            "ke": ke,
            "unit": "same as ke time unit"
        });
    }

    // From two points: ke = ln(C1/C2) / (t2-t1)
    let c1 = match get_f64(args, "c1") { Some(v) if v > 0.0 => v, _ => return err("Missing 'c1' or 'ke'") };
    let c2 = match get_f64(args, "c2") { Some(v) if v > 0.0 => v, _ => return err("Missing 'c2'") };
    let t1 = match get_f64(args, "t1") { Some(v) => v, None => return err("Missing 't1'") };
    let t2 = match get_f64(args, "t2") { Some(v) => v, None => return err("Missing 't2'") };

    let dt = t2 - t1;
    if dt <= 0.0 { return err("t2 must be greater than t1"); }

    let ke = (c1 / c2).ln() / dt;
    let t_half = LN_2 / ke;

    json!({
        "status": "ok",
        "method": "half_life_from_concentrations",
        "half_life": t_half,
        "ke": ke,
        "c1": c1, "c2": c2, "t1": t1, "t2": t2
    })
}

/// Css = (F × Dose) / (CL × τ) or Css = Dose / (Vd × ke × τ)
fn pk_steady_state(args: &Value) -> Value {
    let dose = match get_f64(args, "dose") { Some(v) => v, None => return err("Missing 'dose'") };
    let interval = match get_f64(args, "interval") { Some(v) if v > 0.0 => v, _ => return err("Missing or non-positive 'interval' (dosing interval)") };
    let bioavailability = get_f64(args, "bioavailability").unwrap_or(1.0);

    if let (Some(cl), Some(vd)) = (get_f64(args, "clearance"), get_f64(args, "vd")) {
        if cl <= 0.0 { return err("Clearance must be positive"); }
        let css_avg = (bioavailability * dose) / (cl * interval);
        let ke = cl / vd;
        let t_half = LN_2 / ke;
        let time_to_ss = 4.0 * t_half; // ~94% of Css

        return json!({
            "status": "ok",
            "method": "steady_state",
            "css_average": css_avg,
            "ke": ke,
            "half_life": t_half,
            "time_to_steady_state": time_to_ss,
            "doses_to_steady_state": (time_to_ss / interval).ceil(),
            "accumulation_factor": 1.0 / (1.0 - (-ke * interval).exp()),
        });
    }

    if let Some(ke) = get_f64(args, "ke") {
        if ke <= 0.0 { return err("ke must be positive"); }
        let vd = get_f64(args, "vd").unwrap_or(1.0);
        let css_avg = (bioavailability * dose) / (vd * ke * interval);
        let t_half = LN_2 / ke;

        return json!({
            "status": "ok",
            "method": "steady_state",
            "css_average": css_avg,
            "ke": ke,
            "half_life": t_half,
            "time_to_steady_state": 4.0 * t_half,
            "accumulation_factor": 1.0 / (1.0 - (-ke * interval).exp()),
        });
    }

    err("Need either 'clearance'+'vd' or 'ke' to compute steady state")
}

/// Michaelis-Menten: v = Vmax × [S] / (Km + [S])
fn pk_michaelis_menten(args: &Value) -> Value {
    let vmax = match get_f64(args, "vmax") { Some(v) if v > 0.0 => v, _ => return err("Missing or non-positive 'vmax'") };
    let km = match get_f64(args, "km") { Some(v) if v > 0.0 => v, _ => return err("Missing or non-positive 'km'") };
    let substrate = match get_f64(args, "substrate") { Some(v) => v, None => return err("Missing 'substrate' concentration") };

    let v = vmax * substrate / (km + substrate);
    let fraction_vmax = v / vmax;

    json!({
        "status": "ok",
        "method": "michaelis_menten",
        "velocity": v,
        "vmax": vmax,
        "km": km,
        "substrate": substrate,
        "fraction_of_vmax": fraction_vmax,
        "kinetics": if substrate < 0.1 * km { "first_order" }
            else if substrate > 10.0 * km { "zero_order (saturated)" }
            else { "mixed_order" }
    })
}

/// Vd = Dose / C0 (volume of distribution)
fn pk_vd(args: &Value) -> Value {
    let dose = match get_f64(args, "dose") { Some(v) if v > 0.0 => v, _ => return err("Missing or non-positive 'dose'") };
    let c0 = match get_f64(args, "c0") { Some(v) if v > 0.0 => v, _ => return err("Missing or non-positive 'c0' (initial concentration)") };
    let bioavailability = get_f64(args, "bioavailability").unwrap_or(1.0);

    let vd = (dose * bioavailability) / c0;

    let interpretation = if vd < 0.1 {
        "Highly plasma-bound (stays in blood)"
    } else if vd < 0.7 {
        "Distributes to extracellular fluid"
    } else if vd < 1.0 {
        "Distributes to total body water"
    } else {
        "Extensive tissue binding (Vd > body weight)"
    };

    json!({
        "status": "ok",
        "method": "volume_of_distribution",
        "vd": vd,
        "vd_per_kg": vd, // assumes dose/c0 in per-kg units
        "dose": dose,
        "c0": c0,
        "interpretation": interpretation,
    })
}

/// Bioavailability: F = AUC_oral / AUC_iv × (Dose_iv / Dose_oral)
fn pk_bioavailability(args: &Value) -> Value {
    let auc_oral = match get_f64(args, "auc_oral") { Some(v) if v > 0.0 => v, _ => return err("Missing 'auc_oral'") };
    let auc_iv = match get_f64(args, "auc_iv") { Some(v) if v > 0.0 => v, _ => return err("Missing 'auc_iv'") };
    let dose_oral = get_f64(args, "dose_oral").unwrap_or(1.0);
    let dose_iv = get_f64(args, "dose_iv").unwrap_or(1.0);

    let f = (auc_oral / auc_iv) * (dose_iv / dose_oral);

    json!({
        "status": "ok",
        "method": "bioavailability",
        "f": f,
        "f_percent": f * 100.0,
        "auc_oral": auc_oral,
        "auc_iv": auc_iv,
        "classification": if f >= 0.8 { "high" }
            else if f >= 0.2 { "moderate" }
            else { "low" }
    })
}

/// Dose adjustment for renal/hepatic impairment.
fn pk_dose_adjustment(args: &Value) -> Value {
    let normal_dose = match get_f64(args, "normal_dose") { Some(v) if v > 0.0 => v, _ => return err("Missing 'normal_dose'") };
    let normal_cl = match get_f64(args, "normal_clearance") { Some(v) if v > 0.0 => v, _ => return err("Missing 'normal_clearance'") };
    let impaired_cl = match get_f64(args, "impaired_clearance") { Some(v) if v > 0.0 => v, _ => return err("Missing 'impaired_clearance'") };

    let ratio = impaired_cl / normal_cl;
    let adjusted_dose = normal_dose * ratio;

    json!({
        "status": "ok",
        "method": "dose_adjustment",
        "adjusted_dose": adjusted_dose,
        "normal_dose": normal_dose,
        "clearance_ratio": ratio,
        "reduction_percent": (1.0 - ratio) * 100.0,
        "recommendation": if ratio >= 0.9 { "No adjustment needed" }
            else if ratio >= 0.5 { "Reduce dose proportionally" }
            else { "Significant dose reduction or extended interval recommended" }
    })
}
