#!/usr/bin/env python3
"""
ML vs Statistical Comparator proxy — calls bot tunnel and classifies agreement.

Tools:
  compare-ml-vs-prr       → Single drug-event pair
  compare-ml-vs-prr-batch → Multiple pairs with summary
"""

import json
import sys
import urllib.request
import urllib.error
import urllib.parse

BOT_URL = "https://www.nexvigilant.com/api/bot/signal"
PRR_THRESHOLD = 2.0
ML_THRESHOLD = 0.5

INTERPRETATIONS = {
    "BOTH_SIGNAL": "Both methods agree this is a safety signal. Escalate to signal committee.",
    "BOTH_NOISE": "Both methods agree this is not a signal. Archive or deprioritize.",
    "ML_ONLY": "ML detects a non-linear pattern that PRR misses. Review — may capture emerging or low-frequency signals.",
    "PRR_ONLY": "PRR exceeds threshold but ML classifies as noise. Likely an expected pharmacological effect — false alarm reduction.",
}


def classify(prr, ml_prob):
    prr_sig = prr is not None and prr >= PRR_THRESHOLD
    ml_sig = ml_prob is not None and ml_prob > ML_THRESHOLD
    if prr_sig and ml_sig:
        return "BOTH_SIGNAL"
    if not prr_sig and not ml_sig:
        return "BOTH_NOISE"
    if ml_sig and not prr_sig:
        return "ML_ONLY"
    return "PRR_ONLY"


def fetch_signal(drug, event):
    qs = f"drug={urllib.parse.quote(drug)}&event={urllib.parse.quote(event)}"
    req = urllib.request.Request(f"{BOT_URL}?{qs}", headers={"Accept": "application/json"})
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read().decode("utf-8"))
    if data.get("signals"):
        return data["signals"][0]
    return None


def compare_single(params):
    drug = params.get("drug", "")
    event = params.get("event", "")
    if not drug or not event:
        return {"error": "drug and event are required"}

    sig = fetch_signal(drug, event)
    if not sig:
        return {"drug": drug, "event": event, "agreement": "NO_DATA", "interpretation": "No FAERS data available for this pair."}

    ml = sig.get("ml") or {}
    prr = sig.get("prr")
    ml_prob = ml.get("probability")
    agreement = classify(prr, ml_prob)

    return {
        "drug": drug,
        "event": event,
        "prr": prr,
        "prr_signal": prr is not None and prr >= PRR_THRESHOLD,
        "ml_probability": ml_prob,
        "ml_signal": ml_prob is not None and ml_prob > ML_THRESHOLD,
        "ml_source": ml.get("source", "none"),
        "verdict": sig.get("verdict", "unknown"),
        "agreement": agreement,
        "interpretation": INTERPRETATIONS.get(agreement, ""),
    }


def compare_batch(params):
    targets = params.get("targets", [])
    if not targets:
        return {"error": "targets array required: [{drug, event}]"}
    if len(targets) > 20:
        return {"error": "Max 20 targets per request"}

    # POST to bot tunnel for all pairs at once
    payload = json.dumps({"targets": [{"drug": t["drug"], "event": t["event"], "harm": "?"} for t in targets]}).encode()
    req = urllib.request.Request(BOT_URL, data=payload, headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=45)
    data = json.loads(resp.read().decode("utf-8"))

    results = []
    for sig in data.get("signals", []):
        ml = sig.get("ml") or {}
        prr = sig.get("prr")
        ml_prob = ml.get("probability")
        agreement = classify(prr, ml_prob)
        results.append({
            "drug": sig["drug"],
            "event": sig["event"],
            "prr": prr,
            "ml_probability": ml_prob,
            "ml_source": ml.get("source", "none"),
            "agreement": agreement,
            "interpretation": INTERPRETATIONS.get(agreement, ""),
        })

    counts = {}
    for r in results:
        counts[r["agreement"]] = counts.get(r["agreement"], 0) + 1

    return {
        "results": results,
        "summary": {
            "total": len(results),
            "both_signal": counts.get("BOTH_SIGNAL", 0),
            "both_noise": counts.get("BOTH_NOISE", 0),
            "ml_only": counts.get("ML_ONLY", 0),
            "prr_only": counts.get("PRR_ONLY", 0),
            "no_data": counts.get("NO_DATA", 0),
            "agreement_pct": round((counts.get("BOTH_SIGNAL", 0) + counts.get("BOTH_NOISE", 0)) / max(len(results), 1) * 100),
            "false_positive_reduction": counts.get("PRR_ONLY", 0),
        },
    }


DISPATCH = {
    "compare-ml-vs-prr": compare_single,
    "compare-ml-vs-prr-batch": compare_batch,
}


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"error": "no input"}))
        sys.exit(1)
    try:
        req = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"error": "invalid JSON"}))
        sys.exit(1)

    tool = req.get("tool", "")
    params = req.get("params", req.get("arguments", {}))
    handler = DISPATCH.get(tool)
    if not handler:
        print(json.dumps({"error": f"unknown tool: {tool}", "available": list(DISPATCH.keys())}))
        sys.exit(1)

    try:
        print(json.dumps(handler(params)))
    except Exception as e:
        print(json.dumps({"error": str(e)}))


if __name__ == "__main__":
    main()
