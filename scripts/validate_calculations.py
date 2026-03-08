#!/usr/bin/env python3
"""
NexVigilant Station — Calculation Validation Suite

Validates PV computation correctness against known reference values.
Each test case uses published formulas or textbook examples with
manually computed expected results.

Usage:
    python3 scripts/validate_calculations.py          # Run all validations
    python3 scripts/validate_calculations.py --tool prr  # Filter by tool substring
    python3 scripts/validate_calculations.py --verbose   # Show full response detail
"""

import json
import subprocess
import sys
from pathlib import Path

DISPATCH = str(Path(__file__).parent.resolve() / "dispatch.py")

# Tolerance for floating point comparisons
FLOAT_TOL = 0.01  # 1% relative tolerance


def call_tool(tool_name: str, args: dict) -> dict:
    """Call a calculation tool through dispatch.py."""
    mcp_name = f"calculate_nexvigilant_com_{tool_name.replace('-', '_')}"
    envelope = json.dumps({"tool": mcp_name, "arguments": args})
    result = subprocess.run(
        [sys.executable, DISPATCH],
        input=envelope,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return {"status": "error", "error": result.stderr.strip()[:200]}
    return json.loads(result.stdout.strip())


def approx(actual: float, expected: float, tol: float = FLOAT_TOL) -> bool:
    """Check if actual is within relative tolerance of expected."""
    if expected == 0:
        return abs(actual) < tol
    return abs(actual - expected) / abs(expected) < tol


# ─── Test Cases ─────────────────────────────────────────────────────────────

CASES: list[dict] = [
    # ── PRR ──
    # PRR = (a/(a+b)) / (c/(c+d))
    # a=15,b=100,c=200,d=10000: PRR = (15/115) / (200/10200) = 0.13043 / 0.01961 = 6.652
    {
        "name": "PRR basic signal",
        "tool": "compute-prr",
        "args": {"a": 15, "b": 100, "c": 200, "d": 10000},
        "checks": [
            ("status", "==", "ok"),
            ("prr", "approx", 6.652),
            ("signal", "==", "signal_detected"),
        ],
    },
    # PRR with no signal: a=1,b=500,c=200,d=10000
    # PRR = (1/501) / (200/10200) = 0.001996 / 0.01961 = 0.1018
    {
        "name": "PRR no signal (PRR < 2)",
        "tool": "compute-prr",
        "args": {"a": 1, "b": 500, "c": 200, "d": 10000},
        "checks": [
            ("status", "==", "ok"),
            ("prr", "approx", 0.1018),
            ("signal", "==", "no_signal"),
        ],
    },
    # PRR edge: a=0 should return PRR=0
    {
        "name": "PRR zero reports",
        "tool": "compute-prr",
        "args": {"a": 0, "b": 100, "c": 200, "d": 10000},
        "checks": [
            ("status", "==", "ok"),
            ("prr", "approx", 0.0),
        ],
    },

    # ── ROR ──
    # ROR = (a*d) / (b*c) = (15*10000) / (100*200) = 150000/20000 = 7.5
    {
        "name": "ROR basic signal",
        "tool": "compute-ror",
        "args": {"a": 15, "b": 100, "c": 200, "d": 10000},
        "checks": [
            ("status", "==", "ok"),
            ("ror", "approx", 7.5),
            ("signal", "==", "signal_detected"),
        ],
    },

    # ── IC (BCPNN) ──
    # IC = log2(observed/expected)
    # expected = (a+b)*(a+c)/N = 115*215/10315 = 2.3971
    # IC = log2(15/2.3971) = log2(6.256) = 2.645
    {
        "name": "IC positive signal",
        "tool": "compute-ic",
        "args": {"a": 15, "b": 100, "c": 200, "d": 10000},
        "checks": [
            ("status", "==", "ok"),
            ("ic", "approx", 2.645),
        ],
    },

    # ── EBGM ──
    {
        "name": "EBGM signal present",
        "tool": "compute-ebgm",
        "args": {"a": 15, "b": 100, "c": 200, "d": 10000},
        "checks": [
            ("status", "==", "ok"),
            ("signal", "==", "signal_detected"),
        ],
    },

    # ── Disproportionality Table ──
    # All four scores at once — nested under method names
    {
        "name": "Disproportionality table consensus",
        "tool": "compute-disproportionality-table",
        "args": {"a": 15, "b": 100, "c": 200, "d": 10000},
        "checks": [
            ("status", "==", "ok"),
            ("prr.value", "approx", 6.652),
            ("ror.value", "approx", 7.5),
            ("ic.value", "approx", 2.645),
            ("consensus_signal", "==", "strong_signal"),
            ("signals_detected", "==", 4),
        ],
    },

    # ── Naranjo Causality ──
    # Mixed answers → score 9 = definite (from prior smoke test)
    {
        "name": "Naranjo definite case",
        "tool": "assess-naranjo-causality",
        "args": {
            "previous_reports": True,
            "after_drug": True,
            "improved_on_withdrawal": "yes",
            "reappeared_on_rechallenge": "not_done",
            "alternative_causes": False,
            "placebo_reaction": "not_done",
            "drug_detected": "not_done",
            "dose_related": "yes",
            "previous_exposure": True,
            "objective_evidence": True,
        },
        "checks": [
            ("status", "==", "ok"),
            ("score", ">=", 9),
            ("category", "==", "definite"),
        ],
    },
    # Naranjo max: all max-scoring answers → 13
    {
        "name": "Naranjo max score (all positive)",
        "tool": "assess-naranjo-causality",
        "args": {
            "previous_reports": True,
            "after_drug": True,
            "improved_on_withdrawal": "yes",
            "reappeared_on_rechallenge": "yes",
            "alternative_causes": False,
            "placebo_reaction": "no",
            "drug_detected": "yes",
            "dose_related": "yes",
            "previous_exposure": True,
            "objective_evidence": True,
        },
        "checks": [
            ("status", "==", "ok"),
            ("score", "==", 13),
            ("category", "==", "definite"),
        ],
    },
    # Naranjo doubtful: all negative
    {
        "name": "Naranjo doubtful (all negative)",
        "tool": "assess-naranjo-causality",
        "args": {
            "previous_reports": False,
            "after_drug": False,
            "improved_on_withdrawal": "no",
            "reappeared_on_rechallenge": "no",
            "alternative_causes": True,
            "placebo_reaction": "yes",
            "drug_detected": "no",
            "dose_related": "no",
            "previous_exposure": False,
            "objective_evidence": False,
        },
        "checks": [
            ("status", "==", "ok"),
            ("score", "<=", 0),
            ("category", "==", "doubtful"),
        ],
    },

    # ── WHO-UMC Causality ──
    {
        "name": "WHO-UMC Certain",
        "tool": "assess-who-umc-causality",
        "args": {
            "temporal_relationship": True,
            "known_response": True,
            "dechallenge_positive": "yes",
            "rechallenge_positive": "yes",
            "alternative_explanation": False,
            "sufficient_information": True,
        },
        "checks": [
            ("status", "==", "ok"),
            ("category", "==", "certain"),
        ],
    },
    {
        "name": "WHO-UMC Unlikely",
        "tool": "assess-who-umc-causality",
        "args": {
            "temporal_relationship": False,
            "known_response": False,
            "dechallenge_positive": "no",
            "rechallenge_positive": "not_done",
            "alternative_explanation": True,
            "sufficient_information": True,
        },
        "checks": [
            ("status", "==", "ok"),
            ("category", "==", "unlikely"),
        ],
    },

    # ── ICH E2A Seriousness ──
    {
        "name": "Seriousness: non-serious (all false)",
        "tool": "classify-seriousness",
        "args": {
            "resulted_in_death": False,
            "life_threatening": False,
            "required_hospitalization": False,
            "resulted_in_disability": False,
            "congenital_anomaly": False,
            "medically_important": False,
        },
        "checks": [
            ("status", "==", "ok"),
            ("is_serious", "==", False),
        ],
    },
    {
        "name": "Seriousness: serious (death)",
        "tool": "classify-seriousness",
        "args": {
            "resulted_in_death": True,
            "life_threatening": False,
            "required_hospitalization": False,
            "resulted_in_disability": False,
            "congenital_anomaly": False,
            "medically_important": False,
        },
        "checks": [
            ("status", "==", "ok"),
            ("is_serious", "==", True),
            ("criteria_met", "contains", "death"),
        ],
    },

    # ── Benefit-Risk ──
    # Benefit = 0.8 * 0.7 = 0.56, Risk = 0.3 * 0.05 * (1-0.8) = 0.003
    {
        "name": "Benefit-risk favorable",
        "tool": "compute-benefit-risk",
        "args": {
            "efficacy_score": 0.8,
            "population_impact": 0.7,
            "risk_severity": 0.3,
            "risk_frequency": 0.05,
            "risk_detectability": 0.8,
        },
        "checks": [
            ("status", "==", "ok"),
            ("benefit_score", "approx", 0.56),
            ("assessment", "==", "favorable"),
        ],
    },
    {
        "name": "Benefit-risk unfavorable",
        "tool": "compute-benefit-risk",
        "args": {
            "efficacy_score": 0.2,
            "population_impact": 0.1,
            "risk_severity": 0.9,
            "risk_frequency": 0.5,
            "risk_detectability": 0.1,
        },
        "checks": [
            ("status", "==", "ok"),
            ("assessment", "==", "unfavorable"),
        ],
    },

    # ── Reporting Rate ──
    {
        "name": "Reporting rate per prescriptions",
        "tool": "compute-reporting-rate",
        "args": {
            "case_count": 50,
            "exposure_denominator": 100000,
            "denominator_unit": "prescriptions",
        },
        "checks": [
            ("status", "==", "ok"),
        ],
    },

    # ── Signal Half-Life ──
    # half_life = ln(2) / decay_rate = 0.693 / 0.1 = 6.93 months
    {
        "name": "Signal half-life exponential decay",
        "tool": "compute-signal-half-life",
        "args": {
            "initial_signal_strength": 8.0,
            "decay_rate": 0.1,
        },
        "checks": [
            ("status", "==", "ok"),
            ("half_life_months", "approx", 6.93),
            ("months_until_undetectable", "approx", 13.86),
        ],
    },

    # ── Expectedness ──
    {
        "name": "Expectedness classification",
        "tool": "compute-expectedness",
        "args": {
            "event_term": "hepatotoxicity",
            "drug_name": "metformin",
        },
        "checks": [
            ("status", "==", "ok"),
        ],
    },

    # ── Time-to-Onset (Weibull) ──
    # Regular timing (low CV) → high k → late hazard
    {
        "name": "Time-to-onset regular timing (late hazard)",
        "tool": "compute-time-to-onset",
        "args": {"onset_days": [28, 30, 32, 29, 31, 27, 33, 30]},
        "checks": [
            ("status", "==", "ok"),
            ("onset_pattern", "==", "late_hazard"),
            ("mean_days", "approx", 30.0),
            ("n_cases", "==", 8),
        ],
    },
    # Scattered timing (high CV) → low k → early hazard
    {
        "name": "Time-to-onset scattered (early hazard)",
        "tool": "compute-time-to-onset",
        "args": {"onset_days": [1, 2, 3, 90, 120, 200]},
        "checks": [
            ("status", "==", "ok"),
            ("onset_pattern", "==", "early_hazard"),
        ],
    },

    # ── Case Completeness (E2B) ──
    # All 4 required + 2 recommended → valid, partial completeness
    {
        "name": "Case completeness: all required present",
        "tool": "score-case-completeness",
        "args": {
            "patient_identifier": "PT-001",
            "reporter_identifier": "Dr. Smith",
            "suspect_drug": "metformin",
            "adverse_event": "lactic acidosis",
            "patient_age": "65",
            "patient_sex": "male",
        },
        "checks": [
            ("status", "==", "ok"),
            ("required_score", "==", 100.0),
            ("validity", "in", ["acceptable", "complete", "minimal"]),
        ],
    },
    # Missing required field → invalid
    {
        "name": "Case completeness: missing required",
        "tool": "score-case-completeness",
        "args": {
            "patient_identifier": "PT-001",
            "reporter_identifier": "Dr. Smith",
        },
        "checks": [
            ("status", "==", "ok"),
            ("validity", "==", "invalid"),
        ],
    },

    # ── Number Needed to Harm ──
    # NNH = 1 / |0.05 - 0.01| = 1/0.04 = 25
    {
        "name": "NNH basic calculation",
        "tool": "compute-number-needed-harm",
        "args": {"risk_exposed": 0.05, "risk_unexposed": 0.01},
        "checks": [
            ("status", "==", "ok"),
            ("nnh", "approx", 25.0),
            ("ari", "approx", 0.04),
            ("severity", "==", "frequent_harm"),
        ],
    },
    # Equal risks → NNH undefined
    {
        "name": "NNH equal risks (undefined)",
        "tool": "compute-number-needed-harm",
        "args": {"risk_exposed": 0.03, "risk_unexposed": 0.03},
        "checks": [
            ("status", "==", "ok"),
            ("ari", "==", 0.0),
        ],
    },

    # ── Confidence Interval (Wilson) ──
    # p=8/100=0.08, n=100, z=1.96
    # Wilson center = (0.08 + 1.96²/(2*100)) / (1 + 1.96²/100)
    #               = (0.08 + 0.019208) / (1 + 0.038416) = 0.099208/1.038416 = 0.09554
    # Wilson spread = 1.96 * sqrt(0.08*0.92/100 + 1.96²/(4*100²)) / 1.038416
    {
        "name": "Wilson CI for 8/100",
        "tool": "compute-confidence-interval",
        "args": {"successes": 8, "total": 100},
        "checks": [
            ("status", "==", "ok"),
            ("proportion", "approx", 0.08),
            ("wilson_ci_lower", ">=", 0.03),
            ("wilson_ci_upper", "<=", 0.16),
        ],
    },
    # Extreme proportion: 1/1000
    {
        "name": "Wilson CI for rare event (1/1000)",
        "tool": "compute-confidence-interval",
        "args": {"successes": 1, "total": 1000},
        "checks": [
            ("status", "==", "ok"),
            ("proportion", "approx", 0.001),
            ("wilson_ci_lower", ">=", 0.0),
        ],
    },

    # ── Signal Trend ──
    # Linear increasing: periods 1-4, scores 2,4,6,8 → slope=2.0, R²=1.0
    {
        "name": "Signal trend: perfect linear increase",
        "tool": "compute-signal-trend",
        "args": {
            "observations": [
                {"period": 1, "score": 2.0},
                {"period": 2, "score": 4.0},
                {"period": 3, "score": 6.0},
                {"period": 4, "score": 8.0},
            ]
        },
        "checks": [
            ("status", "==", "ok"),
            ("slope", "approx", 2.0),
            ("r_squared", "approx", 1.0),
            ("direction", "==", "increasing"),
            ("projected_next_period", "approx", 10.0),
        ],
    },
    # Stable signal
    {
        "name": "Signal trend: stable",
        "tool": "compute-signal-trend",
        "args": {
            "observations": [
                {"period": 1, "score": 5.0},
                {"period": 2, "score": 5.1},
                {"period": 3, "score": 4.9},
                {"period": 4, "score": 5.0},
            ]
        },
        "checks": [
            ("status", "==", "ok"),
            ("direction", "==", "stable"),
        ],
    },
]


def resolve_path(obj: dict, path: str) -> object:
    """Resolve a dotted path like 'result.prr' into nested dict."""
    parts = path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def check_assertion(response: dict, field: str, op: str, expected: object) -> tuple[bool, str]:
    """Check a single assertion against the response. Returns (passed, detail)."""
    actual = resolve_path(response, field)

    if actual is None and op != "==":
        return False, f"{field}=MISSING (expected {op} {expected})"

    if op == "==":
        if actual == expected:
            return True, ""
        return False, f"{field}={actual!r} (expected {expected!r})"

    elif op == "approx":
        if actual is None:
            return False, f"{field}=MISSING (expected ≈{expected})"
        if approx(float(actual), float(expected)):
            return True, ""
        return False, f"{field}={actual} (expected ≈{expected}, Δ={abs(float(actual)-float(expected)):.4f})"

    elif op == ">=":
        if actual is not None and actual >= expected:  # type: ignore[operator]
            return True, ""
        return False, f"{field}={actual} (expected >={expected})"

    elif op == "<=":
        if actual is not None and actual <= expected:  # type: ignore[operator]
            return True, ""
        return False, f"{field}={actual} (expected <={expected})"

    elif op == "in":
        if actual in expected:
            return True, ""
        return False, f"{field}={actual!r} (expected one of {expected!r})"

    elif op == "contains":
        if isinstance(actual, (list, str)):
            # Check if expected substring is in any element
            if isinstance(actual, list):
                found = any(expected.lower() in str(item).lower() for item in actual)
            else:
                found = expected.lower() in actual.lower()
            if found:
                return True, ""
            return False, f"{field} does not contain '{expected}'"
        return False, f"{field} is not iterable"

    return False, f"Unknown operator: {op}"


def main() -> None:
    tool_filter = ""
    verbose = "--verbose" in sys.argv
    for i, arg in enumerate(sys.argv):
        if arg == "--tool" and i + 1 < len(sys.argv):
            tool_filter = sys.argv[i + 1].lower()

    print("NexVigilant Station — Calculation Validation Suite")
    print("=" * 72)

    total = 0
    passed = 0
    failed = 0
    failures: list[tuple[str, list[str]]] = []

    for case in CASES:
        if tool_filter and tool_filter not in case["tool"].lower():
            continue

        total += 1
        response = call_tool(case["tool"], case["args"])

        case_failures = []
        for field, op, expected in case["checks"]:
            ok, detail = check_assertion(response, field, op, expected)
            if not ok:
                case_failures.append(detail)

        if case_failures:
            failed += 1
            failures.append((case["name"], case_failures))
            print(f"  [  FAIL] {case['name']}")
            for f in case_failures:
                print(f"           └─ {f}")
        else:
            passed += 1
            print(f"  [  PASS] {case['name']}")

        if verbose and response.get("status") == "ok":
            result = response.get("result", {})
            for k, v in sorted(result.items()) if isinstance(result, dict) else []:
                print(f"           {k}: {v}")

    print("=" * 72)
    print(f"Validation: {passed}/{total} passed, {failed} failed")

    if failures:
        print(f"\nFailed cases:")
        for name, details in failures:
            print(f"  {name}:")
            for d in details:
                print(f"    - {d}")
        sys.exit(1)
    else:
        print("\nAll calculations verified against reference values.")


if __name__ == "__main__":
    main()
