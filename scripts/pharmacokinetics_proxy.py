#!/usr/bin/env python3
"""
Pharmacokinetics Proxy — ADME computation atoms.

Pure math. Source: nv.shared.core.atoms.pk (UACA L1).
AUC, clearance, steady-state, half-life, Michaelis-Menten.
"""

import json
import math
import sys


def compute_auc(args: dict) -> dict:
    times = [float(x.strip()) for x in str(args.get("time_points", "")).split(",") if x.strip()]
    concs = [float(x.strip()) for x in str(args.get("concentrations", "")).split(",") if x.strip()]
    method = str(args.get("method", "linear")).lower()

    if len(times) != len(concs):
        return {"error": "time_points and concentrations must have same length"}
    if len(times) < 2:
        return {"error": "Need at least 2 data points"}

    auc = 0.0
    for i in range(len(times) - 1):
        dt = times[i + 1] - times[i]
        if dt < 0:
            return {"error": "Time points must be ascending"}
        c1, c2 = concs[i], concs[i + 1]
        if method == "log_linear" and c1 > 0 and c2 > 0 and c2 < c1:
            auc += (c1 - c2) * dt / math.log(c1 / c2)
        else:
            auc += (c1 + c2) / 2 * dt

    return {
        "auc": round(auc, 4),
        "method": method,
        "n_intervals": len(times) - 1,
        "time_range_h": round(times[-1] - times[0], 2),
        "unit": "concentration × hours",
    }


def compute_clearance(args: dict) -> dict:
    dose = float(args.get("dose", 0))
    auc = float(args.get("auc", 0))
    f = float(args.get("bioavailability", 1.0))

    if auc <= 0:
        return {"error": "AUC must be positive"}
    if dose <= 0:
        return {"error": "Dose must be positive"}

    cl = (f * dose) / auc
    return {
        "clearance_l_h": round(cl, 4),
        "clearance_ml_min": round(cl * 1000 / 60, 2),
        "dose": dose,
        "auc": auc,
        "bioavailability": f,
        "formula": "CL = (F × Dose) / AUC",
    }


def compute_steady_state(args: dict) -> dict:
    dose = float(args.get("dose", 0))
    cl = float(args.get("clearance_l_h", 0))
    tau = float(args.get("dosing_interval_h", 0))
    f = float(args.get("bioavailability", 1.0))

    if cl <= 0:
        return {"error": "Clearance must be positive"}
    if tau <= 0:
        return {"error": "Dosing interval must be positive"}

    css = (f * dose) / (cl * tau)

    # Estimate time to Css (need half-life — approximate from CL assuming Vd)
    # Without Vd, report as "provide half_life for time estimate"
    half_life = args.get("half_life_h")
    tss = round(4.5 * float(half_life), 1) if half_life else None

    result = {
        "css_avg": round(css, 4),
        "dose": dose,
        "clearance_l_h": cl,
        "dosing_interval_h": tau,
        "bioavailability": f,
        "formula": "Css = (F × Dose) / (CL × τ)",
        "safety_note": "Delayed toxicity may manifest only after Css is reached",
    }
    if tss is not None:
        result["time_to_steady_state_h"] = tss
    return result


def compute_half_life(args: dict) -> dict:
    cl = float(args.get("clearance_l_h", 0))
    vd = float(args.get("volume_of_distribution_l", 0))

    if cl <= 0:
        return {"error": "Clearance must be positive"}
    if vd <= 0:
        return {"error": "Volume of distribution must be positive"}

    ke = cl / vd
    t_half = 0.693 / ke

    return {
        "half_life_h": round(t_half, 2),
        "half_life_days": round(t_half / 24, 2) if t_half > 24 else None,
        "elimination_rate_constant": round(ke, 6),
        "time_to_steady_state_h": round(4.5 * t_half, 1),
        "time_to_elimination_h": round(5 * t_half, 1),
        "clearance_l_h": cl,
        "volume_of_distribution_l": vd,
        "formula": "t½ = (0.693 × Vd) / CL",
    }


def compute_michaelis_menten(args: dict) -> dict:
    vmax = float(args.get("vmax", 0))
    km = float(args.get("km", 0))
    conc = float(args.get("concentration", 0))

    if vmax <= 0:
        return {"error": "Vmax must be positive"}
    if km <= 0:
        return {"error": "Km must be positive"}
    if conc < 0:
        return {"error": "Concentration cannot be negative"}

    rate = (vmax * conc) / (km + conc)
    fraction = rate / vmax

    return {
        "rate": round(rate, 4),
        "fraction_of_vmax": round(fraction, 4),
        "is_saturated": fraction > 0.9,
        "vmax": vmax,
        "km": km,
        "concentration": conc,
        "formula": "Rate = (Vmax × [S]) / (Km + [S])",
        "interpretation": (
            "Near saturation — small dose increases cause disproportionate concentration rises"
            if fraction > 0.75
            else "Linear range — elimination proportional to concentration"
        ),
    }


HANDLERS = {
    "pk-auc": compute_auc,
    "pk-clearance": compute_clearance,
    "pk-steady-state": compute_steady_state,
    "pk-half-life": compute_half_life,
    "pk-michaelis-menten": compute_michaelis_menten,
    # Legacy aliases
    "compute-auc": compute_auc,
    "compute-clearance": compute_clearance,
    "compute-steady-state": compute_steady_state,
    "compute-half-life": compute_half_life,
    "compute-michaelis-menten": compute_michaelis_menten,
}


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        json.dump({"error": "No input"}, sys.stdout)
        return
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    tool = envelope.get("tool", "")
    args = envelope.get("args") or envelope.get("arguments") or {}

    for prefix in ("pharmacokinetics_nexvigilant_com_", "pk_nexvigilant_com_"):
        if tool.startswith(prefix):
            tool = tool[len(prefix):]
            break

    tool_normalized = tool.replace("_", "-")
    handler = HANDLERS.get(tool_normalized) or HANDLERS.get(tool)
    if not handler:
        json.dump({"error": f"Unknown tool: {tool}", "available": list(HANDLERS.keys())}, sys.stdout)
        return

    try:
        json.dump(handler(args), sys.stdout, default=str)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
