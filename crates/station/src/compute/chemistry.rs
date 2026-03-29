//! Chemistry computation tools — Hill, Arrhenius, decay, equilibrium, thermodynamics.

use std::f64::consts::{LN_2, LN_10};
use serde_json::{Value, json};

pub fn handle(bare_name: &str, args: &Value) -> Option<Value> {
    match bare_name {
        "hill-equation" => Some(hill(args)),
        "arrhenius" => Some(arrhenius(args)),
        "decay" => Some(decay(args)),
        "equilibrium" => Some(equilibrium(args)),
        "henderson-hasselbalch" => Some(henderson_hasselbalch(args)),
        "michaelis-menten-enzyme" => Some(michaelis_menten(args)),
        "gibbs-free-energy" => Some(gibbs(args)),
        "beer-lambert" => Some(beer_lambert(args)),
        "binding-affinity" => Some(binding_affinity(args)),
        "dose-response" => Some(dose_response(args)),
        _ => None,
    }
}

fn get_f64(args: &Value, key: &str) -> Option<f64> {
    args.get(key).and_then(|v| v.as_f64())
}

fn err(msg: &str) -> Value {
    json!({"status": "error", "message": msg})
}

/// Hill equation: Y = [L]^n / (Kd^n + [L]^n)
fn hill(args: &Value) -> Value {
    let ligand = match get_f64(args, "ligand") { Some(v) => v, None => return err("Missing 'ligand' concentration") };
    let kd = match get_f64(args, "kd") { Some(v) if v > 0.0 => v, _ => return err("Missing or non-positive 'kd'") };
    let n = get_f64(args, "n").unwrap_or(1.0);

    let y = ligand.powf(n) / (kd.powf(n) + ligand.powf(n));

    let cooperativity = if n > 1.0 { "positive (sigmoidal)" }
        else if n < 1.0 { "negative" }
        else { "none (hyperbolic)" };

    // EC50 = Kd for Hill
    let ec50 = kd;
    let ec90 = kd * 9.0_f64.powf(1.0 / n);

    json!({
        "status": "ok",
        "method": "hill_equation",
        "fractional_occupancy": y,
        "percent_occupancy": y * 100.0,
        "ligand": ligand,
        "kd": kd,
        "hill_coefficient": n,
        "cooperativity": cooperativity,
        "ec50": ec50,
        "ec90": ec90,
    })
}

/// Arrhenius: k = A × exp(-Ea / RT)
fn arrhenius(args: &Value) -> Value {
    let ea = match get_f64(args, "activation_energy") { Some(v) => v, None => return err("Missing 'activation_energy' (J/mol)") };
    let temp = match get_f64(args, "temperature") { Some(v) if v > 0.0 => v, _ => return err("Missing or non-positive 'temperature' (K)") };
    let a = get_f64(args, "pre_exponential").unwrap_or(1.0e13); // typical A factor

    let r = 8.314; // J/(mol·K)
    let k = a * (-ea / (r * temp)).exp();

    // Q10 (rate change per 10K)
    let k_plus10 = a * (-ea / (r * (temp + 10.0))).exp();
    let q10 = if k > 0.0 { k_plus10 / k } else { 0.0 };

    json!({
        "status": "ok",
        "method": "arrhenius",
        "rate_constant": k,
        "activation_energy_kj": ea / 1000.0,
        "temperature_k": temp,
        "temperature_c": temp - 273.15,
        "pre_exponential": a,
        "q10": q10,
        "interpretation": format!("Rate increases {:.1}× per 10°C rise", q10)
    })
}

/// Exponential decay: N(t) = N0 × exp(-λt)
fn decay(args: &Value) -> Value {
    let n0 = match get_f64(args, "initial") { Some(v) => v, None => return err("Missing 'initial' value") };
    let t = match get_f64(args, "time") { Some(v) => v, None => return err("Missing 'time'") };

    // Accept either half_life or decay_constant
    let lambda = if let Some(hl) = get_f64(args, "half_life") {
        if hl <= 0.0 { return err("Half-life must be positive"); }
        LN_2 / hl
    } else if let Some(l) = get_f64(args, "decay_constant") {
        if l <= 0.0 { return err("Decay constant must be positive"); }
        l
    } else {
        return err("Need either 'half_life' or 'decay_constant'");
    };

    let remaining = n0 * (-lambda * t).exp();
    let fraction_remaining = remaining / n0;
    let half_life = LN_2 / lambda;

    json!({
        "status": "ok",
        "method": "exponential_decay",
        "remaining": remaining,
        "initial": n0,
        "fraction_remaining": fraction_remaining,
        "percent_remaining": fraction_remaining * 100.0,
        "time": t,
        "half_life": half_life,
        "decay_constant": lambda,
        "time_to_10pct": LN_10 / lambda,
        "time_to_1pct": 4.60517 / lambda,
    })
}

/// Keq = [products] / [reactants]
fn equilibrium(args: &Value) -> Value {
    let products = match args.get("products").and_then(|v| v.as_array()) {
        Some(a) if !a.is_empty() => a,
        _ => return err("Missing 'products' array of concentrations"),
    };
    let reactants = match args.get("reactants").and_then(|v| v.as_array()) {
        Some(a) if !a.is_empty() => a,
        _ => return err("Missing 'reactants' array of concentrations"),
    };

    let prod_product: f64 = products.iter().filter_map(|v| v.as_f64()).product();
    let react_product: f64 = reactants.iter().filter_map(|v| v.as_f64()).product();

    if react_product == 0.0 {
        return err("Reactant product is zero");
    }

    let keq = prod_product / react_product;
    let delta_g = if let Some(temp) = get_f64(args, "temperature") {
        if temp > 0.0 { Some(-8.314 * temp * keq.ln()) } else { None }
    } else {
        None
    };

    json!({
        "status": "ok",
        "method": "equilibrium_constant",
        "keq": keq,
        "ln_keq": keq.ln(),
        "log10_keq": keq.log10(),
        "delta_g_j_mol": delta_g,
        "direction": if keq > 1.0 { "products_favored" }
            else if keq < 1.0 { "reactants_favored" }
            else { "at_equilibrium" }
    })
}

/// pH = pKa + log([A-]/[HA])
fn henderson_hasselbalch(args: &Value) -> Value {
    let pka = match get_f64(args, "pka") { Some(v) => v, None => return err("Missing 'pka'") };

    // Either compute pH from ratio, or ratio from pH
    if let Some(ratio) = get_f64(args, "conjugate_base_to_acid_ratio") {
        if ratio <= 0.0 { return err("Ratio must be positive"); }
        let ph = pka + ratio.log10();
        return json!({
            "status": "ok",
            "method": "henderson_hasselbalch",
            "mode": "ph_from_ratio",
            "ph": ph,
            "pka": pka,
            "ratio": ratio,
            "percent_ionized": ratio / (1.0 + ratio) * 100.0,
        });
    }

    if let Some(ph) = get_f64(args, "ph") {
        let ratio = 10.0_f64.powf(ph - pka);
        let pct_ionized = ratio / (1.0 + ratio) * 100.0;
        return json!({
            "status": "ok",
            "method": "henderson_hasselbalch",
            "mode": "ratio_from_ph",
            "ph": ph,
            "pka": pka,
            "ratio": ratio,
            "percent_ionized": pct_ionized,
            "percent_unionized": 100.0 - pct_ionized,
        });
    }

    err("Need either 'ph' or 'conjugate_base_to_acid_ratio'")
}

/// v = Vmax × [S] / (Km + [S]) — enzyme kinetics
fn michaelis_menten(args: &Value) -> Value {
    let vmax = match get_f64(args, "vmax") { Some(v) if v > 0.0 => v, _ => return err("Missing 'vmax'") };
    let km = match get_f64(args, "km") { Some(v) if v > 0.0 => v, _ => return err("Missing 'km'") };
    let substrate = match get_f64(args, "substrate") { Some(v) => v, None => return err("Missing 'substrate'") };

    let v = vmax * substrate / (km + substrate);

    // Inhibitor effects
    let (v_inhibited, inhibition_type) = if let Some(ki) = get_f64(args, "ki") {
        let inhibitor = get_f64(args, "inhibitor").unwrap_or(0.0);
        let itype = args.get("inhibition_type").and_then(|v| v.as_str()).unwrap_or("competitive");
        match itype {
            "competitive" => {
                let km_app = km * (1.0 + inhibitor / ki);
                (vmax * substrate / (km_app + substrate), "competitive")
            }
            "uncompetitive" => {
                let factor = 1.0 + inhibitor / ki;
                (vmax * substrate / (km + factor * substrate) / factor, "uncompetitive")
            }
            "noncompetitive" => {
                let factor = 1.0 + inhibitor / ki;
                (vmax / factor * substrate / (km + substrate), "noncompetitive")
            }
            _ => (v, "none"),
        }
    } else {
        (v, "none")
    };

    json!({
        "status": "ok",
        "method": "michaelis_menten_enzyme",
        "velocity": v,
        "velocity_inhibited": v_inhibited,
        "vmax": vmax,
        "km": km,
        "substrate": substrate,
        "fraction_vmax": v / vmax,
        "inhibition_type": inhibition_type,
    })
}

/// ΔG = ΔH - TΔS
fn gibbs(args: &Value) -> Value {
    let dh = match get_f64(args, "delta_h") { Some(v) => v, None => return err("Missing 'delta_h' (enthalpy, J/mol)") };
    let ds = match get_f64(args, "delta_s") { Some(v) => v, None => return err("Missing 'delta_s' (entropy, J/(mol·K))") };
    let temp = match get_f64(args, "temperature") { Some(v) if v > 0.0 => v, _ => return err("Missing or non-positive 'temperature' (K)") };

    let dg = dh - temp * ds;
    let keq = (-dg / (8.314 * temp)).exp();

    json!({
        "status": "ok",
        "method": "gibbs_free_energy",
        "delta_g": dg,
        "delta_g_kj": dg / 1000.0,
        "delta_h": dh,
        "delta_s": ds,
        "temperature": temp,
        "keq": keq,
        "spontaneous": dg < 0.0,
        "interpretation": if dg < 0.0 { "Spontaneous (exergonic)" }
            else if dg > 0.0 { "Non-spontaneous (endergonic)" }
            else { "At equilibrium" }
    })
}

/// A = ε × c × l (Beer-Lambert law)
fn beer_lambert(args: &Value) -> Value {
    // Compute whichever variable is missing from the other three
    let epsilon = get_f64(args, "molar_absorptivity");
    let conc = get_f64(args, "concentration");
    let path = get_f64(args, "path_length").unwrap_or(1.0); // cm, default cuvette
    let absorbance = get_f64(args, "absorbance");

    match (epsilon, conc, absorbance) {
        (Some(e), Some(c), _) => {
            let a = e * c * path;
            let transmittance = 10.0_f64.powf(-a);
            json!({
                "status": "ok",
                "method": "beer_lambert",
                "mode": "absorbance_from_concentration",
                "absorbance": a,
                "transmittance": transmittance,
                "percent_transmittance": transmittance * 100.0,
                "molar_absorptivity": e,
                "concentration": c,
                "path_length": path,
            })
        }
        (Some(e), None, Some(a)) => {
            if e * path == 0.0 { return err("Cannot solve: ε×l = 0"); }
            let c = a / (e * path);
            json!({
                "status": "ok",
                "method": "beer_lambert",
                "mode": "concentration_from_absorbance",
                "concentration": c,
                "absorbance": a,
                "molar_absorptivity": e,
                "path_length": path,
            })
        }
        (None, Some(c), Some(a)) => {
            if c * path == 0.0 { return err("Cannot solve: c×l = 0"); }
            let e = a / (c * path);
            json!({
                "status": "ok",
                "method": "beer_lambert",
                "mode": "absorptivity_from_data",
                "molar_absorptivity": e,
                "absorbance": a,
                "concentration": c,
                "path_length": path,
            })
        }
        _ => err("Need at least 2 of: 'molar_absorptivity', 'concentration', 'absorbance'"),
    }
}

/// Kd = [P][L] / [PL] — binding affinity
fn binding_affinity(args: &Value) -> Value {
    let kd = match get_f64(args, "kd") { Some(v) if v > 0.0 => v, _ => return err("Missing or non-positive 'kd' (M)") };
    let ligand = get_f64(args, "ligand_total");

    let pki = -kd.log10();

    let mut result = json!({
        "status": "ok",
        "method": "binding_affinity",
        "kd": kd,
        "kd_nm": kd * 1e9,
        "kd_um": kd * 1e6,
        "ka": 1.0 / kd,
        "pki": pki,
        "affinity": if kd < 1e-9 { "very_high (sub-nM)" }
            else if kd < 1e-6 { "high (nM)" }
            else if kd < 1e-3 { "moderate (μM)" }
            else { "low (mM+)" },
        "delta_g_binding": 8.314 * 298.15 * kd.ln(), // at 25°C
    });

    if let Some(lt) = ligand {
        let occupancy = lt / (kd + lt);
        if let Some(obj) = result.as_object_mut() {
            obj.insert("fractional_occupancy".into(), json!(occupancy));
            obj.insert("percent_bound".into(), json!(occupancy * 100.0));
        }
    }

    result
}

/// Four-parameter logistic dose-response: Y = Bottom + (Top-Bottom) / (1 + (EC50/X)^n)
fn dose_response(args: &Value) -> Value {
    let dose = match get_f64(args, "dose") { Some(v) => v, None => return err("Missing 'dose'") };
    let ec50 = match get_f64(args, "ec50") { Some(v) if v > 0.0 => v, _ => return err("Missing or non-positive 'ec50'") };
    let bottom = get_f64(args, "bottom").unwrap_or(0.0);
    let top = get_f64(args, "top").unwrap_or(100.0);
    let n = get_f64(args, "hill_slope").unwrap_or(1.0);

    let response = bottom + (top - bottom) / (1.0 + (ec50 / dose).powf(n));

    json!({
        "status": "ok",
        "method": "four_parameter_logistic",
        "response": response,
        "dose": dose,
        "ec50": ec50,
        "hill_slope": n,
        "bottom": bottom,
        "top": top,
        "fraction_max": (response - bottom) / (top - bottom),
    })
}
