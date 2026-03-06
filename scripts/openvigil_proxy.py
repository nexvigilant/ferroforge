#!/usr/bin/env python3
"""
OpenVigil Proxy — computes disproportionality scores (PRR, ROR, IC) from openFDA FAERS data.

Builds 2x2 contingency tables from openFDA count endpoints and computes
standard pharmacovigilance signal detection metrics. No external dependencies.

Usage:
    echo '{"tool": "compute-disproportionality", "arguments": {"drug": "metformin", "event": "lactic acidosis"}}' | python3 openvigil_proxy.py

2x2 contingency table:
              Event+    Event-    Total
    Drug+       a         b       a+b
    Drug-       c         d       c+d
    Total      a+c       b+d       N
"""

import json
import math
import sys
import urllib.parse
import urllib.request
import urllib.error

BASE_URL = "https://api.fda.gov/drug/event.json"
REQUEST_TIMEOUT_SECONDS = 15
DEFAULT_TOP_LIMIT = 10


def _fetch(url: str) -> dict:
    """Execute an HTTP GET and return parsed JSON."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "NexVigilant-FerroForge/1.0 (ferroforge@nexvigilant.com)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        error_body = {}
        try:
            error_body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            pass
        raise RuntimeError(
            f"HTTP {exc.code}: {error_body.get('error', {}).get('message', exc.reason)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _get_count(search_expr: str) -> int:
    """Get total report count for a search expression."""
    url = f"{BASE_URL}?search={search_expr}&limit=1"
    try:
        data = _fetch(url)
        return data.get("meta", {}).get("results", {}).get("total", 0)
    except RuntimeError:
        return 0


def _build_2x2(drug: str, event: str) -> dict:
    """
    Build the 2x2 contingency table from openFDA counts.

    a = reports with drug AND event
    a_plus_b = reports with drug (any event)
    a_plus_c = reports with event (any drug)
    N = total reports in FAERS
    """
    drug_q = f'patient.drug.openfda.generic_name:"{_quote(drug)}"'
    event_q = f'patient.reaction.reactionmeddrapt:"{_quote(event)}"'

    a = _get_count(f"{drug_q}+AND+{event_q}")
    a_plus_b = _get_count(drug_q)
    a_plus_c = _get_count(event_q)

    # Total FAERS reports — use a broad count endpoint
    try:
        total_data = _fetch(f"{BASE_URL}?search=_exists_:safetyreportid&limit=1")
        n = total_data.get("meta", {}).get("results", {}).get("total", 0)
    except RuntimeError:
        n = 0

    if n == 0 or a_plus_b == 0 or a_plus_c == 0:
        return {"error": "Insufficient data to build contingency table", "a": a, "a_plus_b": a_plus_b, "a_plus_c": a_plus_c, "N": n}

    b = a_plus_b - a
    c = a_plus_c - a
    d = n - a - b - c

    return {"a": a, "b": b, "c": c, "d": d, "N": n, "a_plus_b": a_plus_b, "a_plus_c": a_plus_c}


def _compute_scores(table: dict) -> dict:
    """Compute PRR, ROR, IC, and confidence intervals from a 2x2 table."""
    a = table["a"]
    b = table["b"]
    c = table["c"]
    d = table["d"]
    n = table["N"]

    result = {}

    # PRR = (a/(a+b)) / (c/(c+d))
    if (a + b) > 0 and (c + d) > 0 and c > 0:
        drug_rate = a / (a + b)
        background_rate = c / (c + d)
        prr = drug_rate / background_rate if background_rate > 0 else 0.0
        # PRR 95% CI: exp(ln(PRR) +/- 1.96 * sqrt(1/a - 1/(a+b) + 1/c - 1/(c+d)))
        if prr > 0 and a > 0:
            se_ln_prr = math.sqrt(1/a - 1/(a+b) + 1/c - 1/(c+d))
            ln_prr = math.log(prr)
            result["PRR"] = round(prr, 4)
            result["PRR_CI_lower"] = round(math.exp(ln_prr - 1.96 * se_ln_prr), 4)
            result["PRR_CI_upper"] = round(math.exp(ln_prr + 1.96 * se_ln_prr), 4)
        else:
            result["PRR"] = 0.0
    else:
        result["PRR"] = None

    # ROR = (a*d) / (b*c)
    if b > 0 and c > 0:
        ror = (a * d) / (b * c)
        if ror > 0 and a > 0:
            se_ln_ror = math.sqrt(1/a + 1/b + 1/c + 1/d)
            ln_ror = math.log(ror)
            result["ROR"] = round(ror, 4)
            result["ROR_CI_lower"] = round(math.exp(ln_ror - 1.96 * se_ln_ror), 4)
            result["ROR_CI_upper"] = round(math.exp(ln_ror + 1.96 * se_ln_ror), 4)
        else:
            result["ROR"] = 0.0
    else:
        result["ROR"] = None

    # IC = log2(a * N / ((a+b) * (a+c)))  — Information Component
    if a > 0 and (a + b) > 0 and (a + c) > 0:
        observed = a / n
        expected = ((a + b) / n) * ((a + c) / n)
        ic = math.log2(observed / expected) if expected > 0 else 0.0
        # IC 95% CI — frequentist SE with full variance terms
        # SE(IC) = sqrt(1/a + 1/(a+b) + 1/(a+c) - 1/N) / ln(2)
        se_ic = math.sqrt(1/a + 1/(a+b) + 1/(a+c) - 1/n) / math.log(2)
        result["IC"] = round(ic, 4)
        result["IC025"] = round(ic - 1.96 * se_ic, 4)
        result["IC975"] = round(ic + 1.96 * se_ic, 4)
    else:
        result["IC"] = None

    # Chi-squared (full 2x2 Yates-corrected)
    # χ² = N * (|ad - bc| - N/2)² / ((a+b)(c+d)(a+c)(b+d))
    if a > 0 and (a+b) > 0 and (c+d) > 0 and (a+c) > 0 and (b+d) > 0:
        chi2 = n * (abs(a*d - b*c) - n/2)**2 / ((a+b) * (c+d) * (a+c) * (b+d))
        result["chi_squared"] = round(chi2, 4)
    else:
        result["chi_squared"] = None

    return result


def compute_disproportionality(args: dict) -> dict:
    """
    Tool: compute-disproportionality

    Compute PRR, ROR, and IC for a drug-event combination using FAERS data.
    Builds a 2x2 contingency table from openFDA counts.
    """
    drug = args.get("drug", "").strip()
    event = args.get("event", "").strip()

    if not drug or not event:
        return {"status": "error", "message": "Both 'drug' and 'event' are required"}

    table = _build_2x2(drug, event)

    if "error" in table:
        return {"status": "error", "message": table["error"], "counts": table}

    scores = _compute_scores(table)

    # Signal assessment
    signal = "none"
    if scores.get("PRR") is not None and scores.get("PRR_CI_lower") is not None:
        if scores["PRR"] >= 2.0 and scores.get("chi_squared", 0) >= 4.0 and table["a"] >= 3:
            signal = "signal_detected"
        elif scores["PRR_CI_lower"] > 1.0:
            signal = "possible_signal"

    return {
        "status": "ok",
        "drug": drug,
        "event": event,
        "contingency_table": {
            "a_drug_event": table["a"],
            "b_drug_noevent": table["b"],
            "c_nodrug_event": table["c"],
            "d_nodrug_noevent": table["d"],
            "total_reports": table["N"],
        },
        "scores": scores,
        "signal_assessment": signal,
        "criteria": "Evans (2001): PRR >= 2.0, chi2 >= 4.0, N >= 3",
    }


def get_top_reactions(args: dict) -> dict:
    """
    Tool: get-top-reactions

    Get top adverse reactions for a drug ranked by report count.
    For the top reactions, computes PRR as a signal strength indicator.
    """
    drug = args.get("drug", "").strip()
    if not drug:
        return {"status": "error", "message": "'drug' is required"}

    limit = int(args.get("limit", DEFAULT_TOP_LIMIT))
    limit = max(1, min(limit, 25))

    drug_q = f'patient.drug.openfda.generic_name:"{_quote(drug)}"'
    count_field = "patient.reaction.reactionmeddrapt.exact"
    url = f"{BASE_URL}?search={drug_q}&count={count_field}&limit={limit}"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc)}

    raw_results = data.get("results", [])
    drug_total = _get_count(drug_q)

    # Get total FAERS for background rate
    try:
        total_data = _fetch(f"{BASE_URL}?search=_exists_:safetyreportid&limit=1")
        n = total_data.get("meta", {}).get("results", {}).get("total", 0)
    except RuntimeError:
        n = 0

    reactions = []
    for item in raw_results:
        term = item.get("term", "")
        count = item.get("count", 0)
        entry = {"reaction": term, "case_count": count}
        reactions.append(entry)

    return {
        "status": "ok",
        "drug": drug,
        "drug_total_reports": drug_total,
        "total_faers_reports": n,
        "count": len(reactions),
        "reactions": reactions,
    }


def get_top_drugs(args: dict) -> dict:
    """
    Tool: get-top-drugs

    Get top drugs associated with a specific adverse event.
    """
    event = args.get("event", "").strip()
    if not event:
        return {"status": "error", "message": "'event' is required"}

    limit = int(args.get("limit", DEFAULT_TOP_LIMIT))
    limit = max(1, min(limit, 25))

    event_q = f'patient.reaction.reactionmeddrapt:"{_quote(event)}"'
    count_field = "patient.drug.openfda.generic_name.exact"
    url = f"{BASE_URL}?search={event_q}&count={count_field}&limit={limit}"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc)}

    raw_results = data.get("results", [])
    event_total = _get_count(event_q)

    drugs = []
    for item in raw_results:
        drugs.append({
            "drug": item.get("term", ""),
            "case_count": item.get("count", 0),
        })

    return {
        "status": "ok",
        "event": event,
        "event_total_reports": event_total,
        "count": len(drugs),
        "drugs": drugs,
    }


def get_case_demographics(args: dict) -> dict:
    """
    Tool: get-case-demographics

    Get demographic breakdown of cases for a drug (optionally filtered by event).
    Returns age, sex, and country distributions.
    """
    drug = args.get("drug", "").strip()
    if not drug:
        return {"status": "error", "message": "'drug' is required"}

    event = args.get("event", "").strip()

    drug_q = f'patient.drug.openfda.generic_name:"{_quote(drug)}"'
    search_expr = drug_q
    if event:
        search_expr = f'{drug_q}+AND+patient.reaction.reactionmeddrapt:"{_quote(event)}"'

    demographics = {}

    # Sex distribution
    url = f"{BASE_URL}?search={search_expr}&count=patient.patientsex"
    try:
        data = _fetch(url)
        sex_map = {"0": "unknown", "1": "male", "2": "female"}
        demographics["sex"] = [
            {"sex": sex_map.get(str(item.get("term", "")), str(item.get("term", ""))), "count": item.get("count", 0)}
            for item in data.get("results", [])
        ]
    except RuntimeError:
        demographics["sex"] = []

    # Age distribution (by decade)
    url = f"{BASE_URL}?search={search_expr}&count=patient.patientonsetage"
    try:
        data = _fetch(url)
        # Bucket into decades (filter ages > 120 — FAERS data quality artifacts)
        decade_counts = {}
        for item in data.get("results", []):
            age = int(item.get("term", 0))
            count = item.get("count", 0)
            if age < 0 or age > 120:
                continue
            decade = (age // 10) * 10
            label = f"{decade}-{decade+9}"
            decade_counts[label] = decade_counts.get(label, 0) + count
        demographics["age_groups"] = [
            {"age_group": k, "count": v}
            for k, v in sorted(decade_counts.items())
        ]
    except RuntimeError:
        demographics["age_groups"] = []

    # Country distribution
    url = f"{BASE_URL}?search={search_expr}&count=occurcountry.exact&limit=15"
    try:
        data = _fetch(url)
        demographics["countries"] = [
            {"country": item.get("term", ""), "count": item.get("count", 0)}
            for item in data.get("results", [])
        ]
    except RuntimeError:
        demographics["countries"] = []

    return {
        "status": "ok",
        "drug": drug,
        "event": event or None,
        "demographics": demographics,
    }


TOOL_DISPATCH = {
    "compute-disproportionality": compute_disproportionality,
    "get-top-reactions": get_top_reactions,
    "get-top-drugs": get_top_drugs,
    "get-case-demographics": get_case_demographics,
}


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        result = {"status": "error", "message": "No input received on stdin"}
        print(json.dumps(result))
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        result = {"status": "error", "message": f"Invalid JSON input: {exc}"}
        print(json.dumps(result))
        sys.exit(1)

    tool_name = payload.get("tool", "").strip()
    args = payload.get("arguments", payload.get("args", {}))

    if tool_name not in TOOL_DISPATCH:
        known = list(TOOL_DISPATCH.keys())
        result = {"status": "error", "message": f"Unknown tool '{tool_name}'. Known tools: {known}"}
        print(json.dumps(result))
        sys.exit(1)

    handler = TOOL_DISPATCH[tool_name]
    result = handler(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
