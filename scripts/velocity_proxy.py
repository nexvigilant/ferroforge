#!/usr/bin/env python3
"""Velocity proxy — routes to nexvigilant.com/api/bot/velocity."""
import json, sys, urllib.request

VELOCITY_URL = "https://www.nexvigilant.com/api/bot/velocity"

def get_signal_velocity(params):
    req = urllib.request.Request(VELOCITY_URL, headers={"Accept": "application/json"})
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read().decode("utf-8"))

def get_drug_trend(params):
    drug = params.get("drug", "")
    if not drug:
        return {"error": "drug parameter required"}
    req = urllib.request.Request(VELOCITY_URL, headers={"Accept": "application/json"})
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read().decode("utf-8"))
    trend = []
    for day in data.get("history", []):
        for entry in day.get("per_drug", []):
            if entry["drug"].lower() == drug.lower():
                trend.append({"date": day["date"], "ml_probability": entry["ml_probability"], "signal": entry["signal"]})
                break
    return {"drug": drug, "trend": trend, "days": len(trend)}

DISPATCH = {"get-signal-velocity": get_signal_velocity, "get-drug-trend": get_drug_trend}

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"error": "no input"})); sys.exit(1)
    try:
        req = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"error": "invalid JSON"})); sys.exit(1)
    tool = req.get("tool", "")
    params = req.get("params", req.get("arguments", {}))
    handler = DISPATCH.get(tool)
    if not handler:
        print(json.dumps({"error": f"unknown tool: {tool}"})); sys.exit(1)
    try:
        print(json.dumps(handler(params)))
    except Exception as e:
        print(json.dumps({"error": str(e)}))

if __name__ == "__main__":
    main()
