//! Statistics computation tools — CI, p-value, z-test, Bayesian.

use serde_json::{Value, json};

pub fn handle(bare_name: &str, args: &Value) -> Option<Value> {
    match bare_name {
        "confidence-interval" => Some(confidence_interval(args)),
        "p-value" => Some(p_value(args)),
        "z-test" => Some(z_test(args)),
        "bayesian-update" => Some(bayesian_update(args)),
        "sample-size" => Some(sample_size(args)),
        _ => None,
    }
}

fn get_f64(args: &Value, key: &str) -> Option<f64> {
    args.get(key).and_then(|v| v.as_f64())
}

fn err(msg: &str) -> Value {
    json!({"status": "error", "message": msg})
}

fn erfc(x: f64) -> f64 {
    let t = 1.0 / (1.0 + 0.3275911 * x.abs());
    let poly = t * (0.254829592 + t * (-0.284496736
        + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))));
    let result = poly * (-x * x).exp();
    if x >= 0.0 { result } else { 2.0 - result }
}

fn norm_cdf(x: f64) -> f64 {
    0.5 * erfc(-x / std::f64::consts::SQRT_2)
}

/// Confidence interval for a proportion or mean.
fn confidence_interval(args: &Value) -> Value {
    let ci_type = args.get("type").and_then(|v| v.as_str()).unwrap_or("proportion");
    let confidence = get_f64(args, "confidence").unwrap_or(0.95);
    let z = z_for_confidence(confidence);

    match ci_type {
        "proportion" => {
            let x = match get_f64(args, "successes") {
                Some(v) => v,
                None => return err("Missing 'successes'"),
            };
            let n = match get_f64(args, "n") {
                Some(v) if v > 0.0 => v,
                _ => return err("Missing or non-positive 'n'"),
            };
            let p = x / n;

            // Wilson score interval
            let z2 = z * z;
            let denom = 1.0 + z2 / n;
            let center = (p + z2 / (2.0 * n)) / denom;
            let margin = z * (p * (1.0 - p) / n + z2 / (4.0 * n * n)).sqrt() / denom;

            json!({
                "status": "ok",
                "method": "wilson_score",
                "proportion": p,
                "ci_lower": center - margin,
                "ci_upper": center + margin,
                "confidence": confidence,
                "n": n,
                "successes": x,
            })
        }
        "mean" => {
            let mean = match get_f64(args, "mean") {
                Some(v) => v,
                None => return err("Missing 'mean'"),
            };
            let sd = match get_f64(args, "sd") {
                Some(v) if v >= 0.0 => v,
                _ => return err("Missing or negative 'sd'"),
            };
            let n = match get_f64(args, "n") {
                Some(v) if v > 0.0 => v,
                _ => return err("Missing or non-positive 'n'"),
            };

            let se = sd / n.sqrt();
            let margin = z * se;

            json!({
                "status": "ok",
                "method": "normal_approximation",
                "mean": mean,
                "ci_lower": mean - margin,
                "ci_upper": mean + margin,
                "se": se,
                "confidence": confidence,
                "n": n,
            })
        }
        _ => err(&format!("Unknown CI type: {ci_type}. Use 'proportion' or 'mean'")),
    }
}

/// Two-sided p-value from a test statistic.
fn p_value(args: &Value) -> Value {
    let stat = match get_f64(args, "statistic") {
        Some(v) => v,
        None => return err("Missing 'statistic'"),
    };
    let test_type = args.get("test").and_then(|v| v.as_str()).unwrap_or("z");
    let sided = args.get("sided").and_then(|v| v.as_str()).unwrap_or("two");

    let p = match test_type {
        "z" => {
            let two_sided = 2.0 * (1.0 - norm_cdf(stat.abs()));
            if sided == "one" { two_sided / 2.0 } else { two_sided }
        }
        "chi2" => {
            let df = args.get("df").and_then(|v| v.as_u64()).unwrap_or(1) as usize;
            chi_square_p(stat, df)
        }
        _ => return err(&format!("Unknown test type: {test_type}")),
    };

    json!({
        "status": "ok",
        "method": "p_value",
        "statistic": stat,
        "test": test_type,
        "sided": sided,
        "p_value": p,
        "significant_0_05": p < 0.05,
        "significant_0_01": p < 0.01,
        "significant_0_001": p < 0.001,
    })
}

fn chi_square_p(x: f64, df: usize) -> f64 {
    if x <= 0.0 || df == 0 { return 1.0; }
    let k = df as f64;
    let z = ((x / k).powf(1.0 / 3.0) - (1.0 - 2.0 / (9.0 * k))) / (2.0 / (9.0 * k)).sqrt();
    0.5 * erfc(z / std::f64::consts::SQRT_2)
}

/// Z-test for comparing two proportions.
fn z_test(args: &Value) -> Value {
    let x1 = match get_f64(args, "x1") { Some(v) => v, None => return err("Missing 'x1'") };
    let n1 = match get_f64(args, "n1") { Some(v) if v > 0.0 => v, _ => return err("Missing 'n1'") };
    let x2 = match get_f64(args, "x2") { Some(v) => v, None => return err("Missing 'x2'") };
    let n2 = match get_f64(args, "n2") { Some(v) if v > 0.0 => v, _ => return err("Missing 'n2'") };

    let p1 = x1 / n1;
    let p2 = x2 / n2;
    let p_pooled = (x1 + x2) / (n1 + n2);
    let se = (p_pooled * (1.0 - p_pooled) * (1.0 / n1 + 1.0 / n2)).sqrt();

    if se == 0.0 {
        return err("Standard error is zero");
    }

    let z = (p1 - p2) / se;
    let p = 2.0 * (1.0 - norm_cdf(z.abs()));

    json!({
        "status": "ok",
        "method": "z_test_two_proportions",
        "z_statistic": z,
        "p_value": p,
        "p1": p1,
        "p2": p2,
        "difference": p1 - p2,
        "pooled_proportion": p_pooled,
        "se": se,
        "significant_0_05": p < 0.05,
    })
}

/// Bayesian update: Beta-Binomial conjugate prior.
fn bayesian_update(args: &Value) -> Value {
    let prior_alpha = get_f64(args, "prior_alpha").unwrap_or(1.0);
    let prior_beta = get_f64(args, "prior_beta").unwrap_or(1.0);
    let successes = get_f64(args, "successes").unwrap_or(0.0);
    let failures = get_f64(args, "failures").unwrap_or(0.0);

    let post_alpha = prior_alpha + successes;
    let post_beta = prior_beta + failures;
    let post_mean = post_alpha / (post_alpha + post_beta);
    let post_var = (post_alpha * post_beta)
        / ((post_alpha + post_beta).powi(2) * (post_alpha + post_beta + 1.0));

    // Credible interval (Beta quantile approximation)
    let ci_lower = beta_quantile(0.025, post_alpha, post_beta);
    let ci_upper = beta_quantile(0.975, post_alpha, post_beta);

    json!({
        "status": "ok",
        "method": "bayesian_beta_binomial",
        "prior": {"alpha": prior_alpha, "beta": prior_beta},
        "data": {"successes": successes, "failures": failures},
        "posterior": {
            "alpha": post_alpha,
            "beta": post_beta,
            "mean": post_mean,
            "variance": post_var,
            "sd": post_var.sqrt(),
            "ci_95_lower": ci_lower,
            "ci_95_upper": ci_upper,
        }
    })
}

/// Beta quantile approximation via normal approx to logit-normal.
fn beta_quantile(p: f64, alpha: f64, beta: f64) -> f64 {
    let mean = alpha / (alpha + beta);
    let var = (alpha * beta) / ((alpha + beta).powi(2) * (alpha + beta + 1.0));
    let sd = var.sqrt();
    let z = z_for_p(p);
    (mean + z * sd).clamp(0.0, 1.0)
}

fn z_for_p(p: f64) -> f64 {
    // Rational approximation (same as in epidemiology.rs)
    if p <= 0.0 { return f64::NEG_INFINITY; }
    if p >= 1.0 { return f64::INFINITY; }
    let a = [-3.969683028665376e+01, 2.209460984245205e+02,
        -2.759285104469687e+02, 1.383577518672690e+02,
        -3.066479806614716e+01, 2.506628277459239e+00];
    let b = [-5.447609879822406e+01, 1.615858368580409e+02,
        -1.556989798598866e+02, 6.680131188771972e+01,
        -1.328068155288572e+01];
    let c = [-7.784894002430293e-03, -3.223964580411365e-01,
        -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00];
    let d = [7.784695709041462e-03, 3.224671290700398e-01,
        2.445134137142996e+00, 3.754408661907416e+00];
    let pl = 0.02425;
    if p < pl {
        let q = (-2.0 * p.ln()).sqrt();
        (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
        ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)
    } else if p <= 1.0 - pl {
        let q = p - 0.5;
        let r = q * q;
        (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q /
        (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1.0)
    } else {
        let q = (-2.0 * (1.0 - p).ln()).sqrt();
        -((((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
        ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0))
    }
}

fn z_for_confidence(c: f64) -> f64 {
    z_for_p(1.0 - (1.0 - c) / 2.0)
}

/// Sample size calculation for desired margin of error.
fn sample_size(args: &Value) -> Value {
    let margin = match get_f64(args, "margin_of_error") {
        Some(v) if v > 0.0 => v,
        _ => return err("Missing or non-positive 'margin_of_error'"),
    };
    let confidence = get_f64(args, "confidence").unwrap_or(0.95);
    let p = get_f64(args, "proportion").unwrap_or(0.5); // conservative default

    let z = z_for_confidence(confidence);
    let n = (z * z * p * (1.0 - p)) / (margin * margin);

    json!({
        "status": "ok",
        "method": "sample_size",
        "n": n.ceil(),
        "margin_of_error": margin,
        "confidence": confidence,
        "assumed_proportion": p,
    })
}
