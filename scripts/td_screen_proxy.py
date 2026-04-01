#!/usr/bin/env python3
"""
Tardive Dyskinesia Pre-Screening Tool

Risk model based on two-curve irreversibility equation:
  ∝(t) = (1 - R(t)) × H(t)

Where:
  R(t) = R₀ · e^(-0.693·t / t_half)    — recovery capacity decay
  H(t) = t^nH / (K^nH + t^nH)          — receptor supersensitivity (Hill)

Primitive sentence:
  ∝(TD) = ∅(→⁻¹) emerges when decay(recovery) × hill(supersensitivity) > ∂(R_crit)

Built 2026-03-31. Matthew Campion & Vigil.
"""

import json
import math
import sys

# ── Risk Factor Weights ──────────────────────────────────────────────────────

# Drug class modifiers (relative receptor damage rate)
DRUG_CLASS = {
    "typical_high_potency": {
        "k_modifier": 1.5,
        "examples": ["haloperidol", "fluphenazine", "pimozide", "trifluoperazine"],
        "description": "High-potency typical antipsychotics — highest TD risk",
    },
    "typical_low_potency": {
        "k_modifier": 1.2,
        "examples": ["chlorpromazine", "thioridazine"],
        "description": "Low-potency typical antipsychotics — high TD risk",
    },
    "atypical": {
        "k_modifier": 0.6,
        "examples": ["risperidone", "olanzapine", "quetiapine", "aripiprazole", "clozapine"],
        "description": "Atypical antipsychotics — lower but non-zero TD risk",
    },
    "dopaminergic": {
        "k_modifier": 0.8,
        "examples": ["levodopa", "carbidopa-levodopa", "pramipexole", "ropinirole"],
        "description": "Dopaminergic agents — peak-dose dyskinesia risk",
    },
    "antiemetic": {
        "k_modifier": 0.9,
        "examples": ["metoclopramide", "prochlorperazine"],
        "description": "Dopamine-blocking antiemetics — underrecognized TD risk",
    },
    "other": {
        "k_modifier": 0.5,
        "examples": [],
        "description": "Other medications — low but possible TD risk",
    },
}

# Age vulnerability multiplier
def _age_multiplier(age):
    """Older patients cross the irreversibility threshold faster."""
    if age < 40:
        return 0.7
    elif age < 55:
        return 1.0
    elif age < 65:
        return 1.3
    elif age < 75:
        return 1.6
    else:
        return 2.0


# Prior episode multiplier — each episode weakens recovery
def _prior_episode_modifier(episodes):
    """Each prior reversible episode lowers the recovery floor."""
    return 1.0 + (episodes * 0.25)


# ── The Two-Curve Model ─────────────────────────────────────────────────────

# Base parameters (calibrated from literature)
BASE_HALF_LIFE = 18.0      # months — recovery capacity half-life
HILL_K_HALF = 12.0         # months — Hill half-saturation
HILL_N = 2.5               # Hill coefficient (strong positive cooperativity)
R_CRIT = 0.25              # Critical recovery threshold


def compute_risk(duration_months, drug_class, age, dose_ratio=1.0, prior_episodes=0):
    """
    Compute tardive dyskinesia irreversibility score.

    Returns ∝(t) between 0.0 (fully reversible) and 1.0 (fully irreversible).
    """
    # Get drug class modifier
    drug_info = DRUG_CLASS.get(drug_class, DRUG_CLASS["other"])
    k_mod = drug_info["k_modifier"]

    # Age vulnerability
    age_mod = _age_multiplier(age)

    # Prior episode modifier
    ep_mod = _prior_episode_modifier(prior_episodes)

    # Effective exposure (adjusted for all risk factors)
    effective_duration = duration_months * k_mod * age_mod * dose_ratio * ep_mod

    # Recovery capacity: R(t) = e^(-0.693 * t_eff / t_half)
    decay_constant = 0.693 / BASE_HALF_LIFE
    r_t = math.exp(-decay_constant * effective_duration)

    # Receptor supersensitivity: H(t) = t^nH / (K^nH + t^nH)
    if effective_duration <= 0:
        h_t = 0.0
    else:
        t_n = effective_duration ** HILL_N
        k_n = HILL_K_HALF ** HILL_N
        h_t = t_n / (k_n + t_n)

    # Irreversibility score: ∝(t) = (1 - R(t)) × H(t)
    alpha_t = (1.0 - r_t) * h_t

    # Risk category
    if alpha_t < 0.10:
        category = "LOW"
        recommendation = "Continue monitoring. Standard clinical assessment at regular intervals."
    elif alpha_t < 0.25:
        category = "MODERATE"
        recommendation = "Increase monitoring frequency. Consider AIMS assessment every 3 months. Evaluate dose reduction if clinically feasible."
    elif alpha_t < 0.50:
        category = "HIGH"
        recommendation = "Urgent review recommended. Consider switching to lower-risk agent. Perform AIMS immediately. The boundary between reversible and irreversible is near."
    elif alpha_t < 0.75:
        category = "VERY_HIGH"
        recommendation = "Recovery capacity critically low. Strong consideration for drug discontinuation or switch. Tardive dyskinesia may already be developing. Specialist referral recommended."
    else:
        category = "CRITICAL"
        recommendation = "Irreversibility likely. If dyskinesia symptoms present, they may be permanent. Immediate specialist evaluation. Consider VMAT2 inhibitor (valbenazine, deutetrabenazine) for symptom management."

    # Recovery window
    if r_t > R_CRIT:
        recovery_window = "OPEN — recovery capacity {:.0f}% (above critical threshold {:.0f}%)".format(
            r_t * 100, R_CRIT * 100
        )
    else:
        recovery_window = "CLOSING — recovery capacity {:.0f}% (at or below critical threshold {:.0f}%)".format(
            r_t * 100, R_CRIT * 100
        )

    return {
        "irreversibility_score": round(alpha_t, 4),
        "risk_category": category,
        "recovery_capacity": round(r_t, 4),
        "receptor_supersensitivity": round(h_t, 4),
        "effective_exposure_months": round(effective_duration, 1),
        "recovery_window": recovery_window,
        "recommendation": recommendation,
        "risk_factors": {
            "drug_class": drug_class,
            "drug_modifier": k_mod,
            "age": age,
            "age_modifier": age_mod,
            "dose_ratio": dose_ratio,
            "prior_episodes": prior_episodes,
            "prior_episode_modifier": ep_mod,
        },
        "model": {
            "equation": "∝(t) = (1 - R₀·e^(-0.693·t_eff/t½)) × (t_eff^nH / (K^nH + t_eff^nH))",
            "recovery_half_life_months": BASE_HALF_LIFE,
            "hill_k_half_months": HILL_K_HALF,
            "hill_coefficient": HILL_N,
            "critical_threshold": R_CRIT,
            "primitive_definition": "∝(TD) = ∅(→⁻¹) at ∂(R(t) < R_crit) — irreversibility is the void of the inverse arrow",
        },
        "disclaimer": (
            "This is a computational risk estimation model, not a clinical diagnosis. "
            "Risk scores are derived from population-level pharmacological models and "
            "should be interpreted by a qualified healthcare professional in the context "
            "of individual patient factors. Always perform clinical assessment (AIMS) "
            "for definitive evaluation."
        ),
    }


def screen(args):
    """Pre-screen a patient for TD risk."""
    duration = args.get("duration_months", 0)
    drug_class = args.get("drug_class", "other")
    age = args.get("age", 50)
    dose_ratio = args.get("dose_ratio", 1.0)
    prior_episodes = args.get("prior_episodes", 0)

    if duration < 0:
        return {"error": "duration_months must be >= 0", "status": "error"}
    if age < 0 or age > 120:
        return {"error": "age must be between 0 and 120", "status": "error"}

    result = compute_risk(duration, drug_class, age, dose_ratio, prior_episodes)
    return {**result, "status": "ok"}


def drug_classes(_args):
    """List available drug classes with risk modifiers."""
    classes = []
    for key, info in DRUG_CLASS.items():
        classes.append({
            "class": key,
            "modifier": info["k_modifier"],
            "description": info["description"],
            "examples": info["examples"],
        })
    # Sort by modifier descending (highest risk first)
    classes.sort(key=lambda x: x["modifier"], reverse=True)
    return {"drug_classes": classes, "status": "ok"}


def trajectory(args):
    """Project risk trajectory over time for a given patient profile."""
    drug_class = args.get("drug_class", "other")
    age = args.get("age", 50)
    dose_ratio = args.get("dose_ratio", 1.0)
    prior_episodes = args.get("prior_episodes", 0)
    max_months = args.get("max_months", 60)

    points = []
    boundary_crossed_at = None

    for month in [0, 1, 3, 6, 9, 12, 18, 24, 36, 48, 60]:
        if month > max_months:
            break
        result = compute_risk(month, drug_class, age, dose_ratio, prior_episodes)
        point = {
            "month": month,
            "irreversibility": result["irreversibility_score"],
            "recovery_capacity": result["recovery_capacity"],
            "supersensitivity": result["receptor_supersensitivity"],
            "category": result["risk_category"],
        }
        points.append(point)

        if boundary_crossed_at is None and result["recovery_capacity"] < R_CRIT:
            boundary_crossed_at = month

    return {
        "trajectory": points,
        "boundary_crossing_month": boundary_crossed_at,
        "boundary_meaning": (
            f"Recovery capacity drops below {R_CRIT*100:.0f}% at month {boundary_crossed_at}. "
            "After this point, motor control recovery becomes unlikely even with drug withdrawal."
        ) if boundary_crossed_at else (
            f"Recovery capacity stays above {R_CRIT*100:.0f}% within the projected window. "
            "The boundary has not been crossed."
        ),
        "status": "ok",
    }


TOOLS = {
    "screen": screen,
    "drug-classes": drug_classes,
    "trajectory": trajectory,
}


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"error": "No input", "status": "error"}))
        return

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON", "status": "error"}))
        return

    tool = envelope.get("tool", "")
    arguments = envelope.get("arguments", {})

    handler = TOOLS.get(tool)
    if handler:
        result = handler(arguments)
    else:
        result = {"error": f"Unknown tool: {tool}", "status": "error"}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
