#!/usr/bin/env python3
"""
Signal Triangulation Proxy — cross-database PV signal orchestrator.

Queries FAERS (US), EudraVigilance (EU), VigiAccess (WHO), DailyMed (label),
PubMed (literature), and ClinicalTrials.gov (trial SAEs) for a drug-event pair.
Computes disproportionality, concordance score, and returns a unified verdict.

One tool call. Six databases. No competitor has this.

Usage:
    echo '{"tool":"triangulate-signal","arguments":{"drug":"metformin","event":"lactic acidosis"}}' | python3 triangulate_proxy.py
"""

import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


import json

def ensure_str(val) -> str:
    """Coerce any input to string safely to prevent AttributeError."""
    if val is None:
        return ""
    if isinstance(val, (int, float, bool)):
        return str(val)
    if isinstance(val, (list, dict)):
        try:
            return json.dumps(val)
        except Exception:
            return str(val)
    return str(val)

def get_int_param(args: dict, key: str, default: int, min_val: int = None, max_val: int = None) -> int:
    """Safely parse integer parameter with optional clamping."""
    val = args.get(key)
    if val is None:
        return default
    try:
        res = int(val)
    except (ValueError, TypeError):
        return default
    if min_val is not None:
        res = max(res, min_val)
    if max_val is not None:
        res = min(res, max_val)
    return res



DATA_SOURCE = "triangulate.nexvigilant.com"
USER_AGENT = "NexVigilant-Station/1.0 (PV research tool)"
TIMEOUT = 15


# ---------------------------------------------------------------------------
# Shared HTTP helper
# ---------------------------------------------------------------------------

def _fetch_json(url: str, timeout: int = TIMEOUT) -> dict:
    """Fetch a URL and parse JSON response."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        return {"_error": str(e)}


def _fetch_text(url: str, timeout: int = TIMEOUT) -> str:
    """Fetch a URL and return text."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Database 1: FAERS (US) — openFDA
# ---------------------------------------------------------------------------

_FAERS_TOTAL = 20_006_989  # Updated 2026-03-29 from openFDA meta. Refresh monthly.


def _query_faers(drug: str, event: str) -> dict:
    """Query openFDA FAERS for case count and build 2x2 contingency table.
    3 parallel HTTP requests (was 4 sequential). Total count hardcoded."""
    base = "https://api.fda.gov/drug/event.json"

    def _count(search: str) -> int:
        url = f"{base}?search={search}&limit=1"
        data = _fetch_json(url)
        if "_error" in data:
            return 0
        return data.get("meta", {}).get("results", {}).get("total", 0)

    drug_enc = urllib.parse.quote(f'"{drug}"')
    event_enc = urllib.parse.quote(f'"{event}"')
    drug_q = f"patient.drug.openfda.generic_name:{drug_enc}"
    event_q = f"patient.reaction.reactionmeddrapt:{event_enc}"

    # 3 counts in parallel (total is hardcoded — saves 1 HTTP round trip)
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_a = pool.submit(_count, f"{drug_q}+AND+{event_q}")
        f_ab = pool.submit(_count, drug_q)
        f_ac = pool.submit(_count, event_q)
        a = f_a.result()
        ab = f_ab.result()
        ac = f_ac.result()

    n = _FAERS_TOTAL
    b = max(ab - a, 0)
    c = max(ac - a, 0)
    d = max(n - a - b - c, 0)

    return {
        "source": "FAERS (openFDA)",
        "cases": a,
        "total_drug_reports": ab,
        "total_event_reports": ac,
        "total_database": n,
        "contingency": {"a": a, "b": b, "c": c, "d": d},
    }


# ---------------------------------------------------------------------------
# Database 2: EudraVigilance (EU) — adrreports.eu substance tables
# ---------------------------------------------------------------------------

def _query_eudravigilance(drug: str) -> dict:
    """Query EudraVigilance public substance tables for case counts."""
    first_letter = drug.strip()[0].lower()
    url = f"https://www.adrreports.eu/tables/substance/{first_letter}.html"
    html = _fetch_text(url)
    if not html:
        return {"source": "EudraVigilance", "status": "unavailable"}

    drug_upper = drug.strip().upper()
    for row in html.split("<tr>")[1:]:
        texts = [t.strip() for t in re.findall(r">([^<]+)<", row) if t.strip()]
        if not texts:
            continue
        name = texts[0].strip()
        if name == drug_upper or name.startswith(drug_upper):
            urls = re.findall(r'href="([^"]+)"', row)
            code_match = re.search(r"P3=1\+(\d+)", urls[0]) if urls else None
            return {
                "source": "EudraVigilance",
                "substance": name,
                "substance_code": code_match.group(1) if code_match else None,
                "dashboard_url": urls[0] if urls else None,
                "status": "found",
            }

    return {"source": "EudraVigilance", "status": "not_found"}


# ---------------------------------------------------------------------------
# Database 3: VigiAccess (WHO) — vigiaccess.org
# ---------------------------------------------------------------------------

def _query_vigiaccess(drug: str) -> dict:
    """Query VigiAccess for WHO global reporting data."""
    # VigiAccess has no public API — return reference info
    return {
        "source": "VigiAccess (WHO)",
        "url": f"https://www.vigiaccess.org/",
        "note": "WHO VigiBase data accessible via vigiaccess.org — manual or browser extraction required",
        "status": "reference_only",
    }


# ---------------------------------------------------------------------------
# Database 4: DailyMed (Label)
# ---------------------------------------------------------------------------

def _query_dailymed(drug: str, event: str) -> dict:
    """Check DailyMed for whether the event is on the drug label."""
    search_url = f"https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json?drug_name={urllib.parse.quote(drug)}&page_size=1"
    data = _fetch_json(search_url)
    if "_error" in data or not data.get("data"):
        return {"source": "DailyMed", "status": "not_found", "on_label": None}

    set_id = data["data"][0].get("setid", "")
    if not set_id:
        return {"source": "DailyMed", "status": "no_setid", "on_label": None}

    # Fetch SPL JSON (single request — no HTML fetch needed)
    label_url = f"https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{set_id}.json"
    label_data = _fetch_json(label_url)
    json_text = json.dumps(label_data).lower()

    event_lower = event.lower()
    event_words = event_lower.split()

    on_label = event_lower in json_text
    if not on_label and len(event_words) > 1:
        on_label = all(w in json_text for w in event_words)

    boxed = ("boxed warning" in json_text or "black box" in json_text) and event_lower in json_text

    return {
        "source": "DailyMed",
        "status": "ok",
        "set_id": set_id,
        "on_label": on_label,
        "boxed_warning": boxed,
        "drug_name": data["data"][0].get("title", drug),
    }


# ---------------------------------------------------------------------------
# Database 5: PubMed (Literature)
# ---------------------------------------------------------------------------

def _query_pubmed(drug: str, event: str) -> dict:
    """Search PubMed for signal detection literature."""
    query = f"{drug}[Title/Abstract] AND {event}[Title/Abstract] AND (pharmacovigilance OR safety OR adverse)"
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={urllib.parse.quote(query)}&retmode=json&retmax=5"
    data = _fetch_json(url)
    if "_error" in data:
        return {"source": "PubMed", "status": "error", "count": 0}

    result = data.get("esearchresult", {})
    count = int(result.get("count", 0))
    pmids = result.get("idlist", [])[:5]

    return {
        "source": "PubMed",
        "status": "ok",
        "article_count": count,
        "top_pmids": pmids,
    }


# ---------------------------------------------------------------------------
# Database 6: ClinicalTrials.gov (Trial SAEs)
# ---------------------------------------------------------------------------

def _query_clinicaltrials(drug: str, event: str) -> dict:
    """Search ClinicalTrials.gov for trials with this drug that report SAEs."""
    url = f"https://clinicaltrials.gov/api/v2/studies?query.intr={urllib.parse.quote(drug)}&query.term={urllib.parse.quote(event)}&pageSize=5&format=json"
    data = _fetch_json(url)
    if "_error" in data:
        return {"source": "ClinicalTrials.gov", "status": "error", "trials": 0}

    studies = data.get("studies", [])
    return {
        "source": "ClinicalTrials.gov",
        "status": "ok",
        "trials_found": len(studies),
        "total_matching": data.get("totalCount", len(studies)),
        "top_trials": [
            {
                "nctId": s.get("protocolSection", {}).get("identificationModule", {}).get("nctId", ""),
                "title": s.get("protocolSection", {}).get("identificationModule", {}).get("briefTitle", ""),
            }
            for s in studies[:5]
        ],
    }


# ---------------------------------------------------------------------------
# Disproportionality computation
# ---------------------------------------------------------------------------

def _compute_disproportionality(ct: dict) -> dict:
    """Compute PRR, ROR, IC, chi-squared from 2x2 contingency table."""
    a, b, c, d = ct.get("a", 0), ct.get("b", 0), ct.get("c", 0), ct.get("d", 0)
    n = a + b + c + d

    if a == 0 or n == 0:
        return {"status": "insufficient_data", "a": a, "b": b, "c": c, "d": d}

    # PRR
    prr = (a / (a + b)) / (c / (c + d)) if (a + b) > 0 and (c + d) > 0 and c > 0 else 0
    # PRR 95% CI
    if a > 0 and b > 0 and c > 0 and d > 0:
        se_ln_prr = math.sqrt(1/a - 1/(a+b) + 1/c - 1/(c+d))
        prr_lower = math.exp(math.log(prr) - 1.96 * se_ln_prr)
        prr_upper = math.exp(math.log(prr) + 1.96 * se_ln_prr)
    else:
        prr_lower = prr_upper = 0

    # ROR
    ror = (a * d) / (b * c) if b > 0 and c > 0 else 0
    if a > 0 and b > 0 and c > 0 and d > 0:
        se_ln_ror = math.sqrt(1/a + 1/b + 1/c + 1/d)
        ror_lower = math.exp(math.log(ror) - 1.96 * se_ln_ror)
        ror_upper = math.exp(math.log(ror) + 1.96 * se_ln_ror)
    else:
        ror_lower = ror_upper = 0

    # IC (Information Component)
    expected = ((a + b) * (a + c)) / n if n > 0 else 1
    ic = math.log2(a / expected) if expected > 0 and a > 0 else 0
    # IC 95% CI (approximation)
    if a > 0:
        ic_se = 1 / (math.sqrt(a) * math.log(2))
        ic025 = ic - 1.96 * ic_se
        ic975 = ic + 1.96 * ic_se
    else:
        ic025 = ic975 = 0

    # Chi-squared
    expected_a = ((a + b) * (a + c)) / n if n > 0 else 0
    expected_b = ((a + b) * (b + d)) / n if n > 0 else 0
    expected_c = ((c + d) * (a + c)) / n if n > 0 else 0
    expected_d = ((c + d) * (b + d)) / n if n > 0 else 0
    chi2 = sum(
        ((obs - exp) ** 2) / exp if exp > 0 else 0
        for obs, exp in [(a, expected_a), (b, expected_b), (c, expected_c), (d, expected_d)]
    )

    return {
        "status": "ok",
        "contingency": {"a": a, "b": b, "c": c, "d": d, "N": n},
        "PRR": round(prr, 4),
        "PRR_CI": [round(prr_lower, 4), round(prr_upper, 4)],
        "ROR": round(ror, 4),
        "ROR_CI": [round(ror_lower, 4), round(ror_upper, 4)],
        "IC": round(ic, 4),
        "IC_CI": [round(ic025, 4), round(ic975, 4)],
        "chi_squared": round(chi2, 2),
        "conservation_law": {
            "observed_rate": round(a / (a + b), 6) if (a + b) > 0 else 0,
            "expected_rate": round(c / (c + d), 6) if (c + d) > 0 else 0,
            "note": "PRR=ratio(obs/exp), ROR=odds(obs/exp), IC=log2(obs/exp) — same data, different boundary operator",
        },
    }


# ---------------------------------------------------------------------------
# Signal strength classification
# ---------------------------------------------------------------------------

def _classify_signal(dispro: dict, cases: int) -> dict:
    """Classify signal strength using Evans criteria + multi-metric convergence."""
    prr = dispro.get("PRR", 0)
    ror = dispro.get("ROR", 0)
    ror_lower = dispro.get("ROR_CI", [0, 0])[0]
    ic025 = dispro.get("IC_CI", [0, 0])[0]
    chi2 = dispro.get("chi_squared", 0)

    if prr >= 2.0 and chi2 >= 4.0 and cases >= 3:
        strength = "strong"
    elif prr >= 2.0 or (ror >= 2.0 and ror_lower > 1.0):
        strength = "moderate"
    elif prr >= 1.5:
        strength = "weak"
    else:
        strength = "noise"

    # Multi-metric convergence
    metrics_positive = sum([
        prr >= 2.0,
        ror_lower > 1.0,
        ic025 > 0,
        chi2 >= 3.841,
    ])

    return {
        "signal_strength": strength,
        "metrics_positive": f"{metrics_positive}/4",
        "evans_criteria_met": prr >= 2.0 and chi2 >= 4.0 and cases >= 3,
    }


# ---------------------------------------------------------------------------
# Concordance scoring
# ---------------------------------------------------------------------------

def _score_concordance(faers: dict, eudra: dict, vigiaccess: dict, label: dict, pubmed: dict, trials: dict) -> dict:
    """Score cross-database agreement."""
    sources_queried = 0
    sources_positive = 0
    details = []

    # FAERS
    if faers.get("cases", 0) > 0:
        sources_queried += 1
        if faers["cases"] >= 3:
            sources_positive += 1
            details.append(f"FAERS: {faers['cases']} cases (positive)")
        else:
            details.append(f"FAERS: {faers['cases']} cases (insufficient)")

    # EudraVigilance
    if eudra.get("status") == "found":
        sources_queried += 1
        sources_positive += 1  # Substance exists = EU has data
        details.append(f"EudraVigilance: substance found (code {eudra.get('substance_code')})")
    elif eudra.get("status") != "unavailable":
        sources_queried += 1
        details.append("EudraVigilance: substance not found")

    # VigiAccess (reference only for now)
    if vigiaccess.get("status") == "reference_only":
        details.append("VigiAccess: reference link provided (manual verification needed)")

    # DailyMed label
    if label.get("on_label") is not None:
        sources_queried += 1
        if label["on_label"]:
            sources_positive += 1
            boxed = " (BOXED WARNING)" if label.get("boxed_warning") else ""
            details.append(f"DailyMed: ON LABEL{boxed}")
        else:
            details.append("DailyMed: NOT on label — potential new signal")

    # PubMed
    if pubmed.get("article_count", 0) > 0:
        sources_queried += 1
        sources_positive += 1
        details.append(f"PubMed: {pubmed['article_count']} articles")
    elif pubmed.get("status") == "ok":
        sources_queried += 1
        details.append("PubMed: 0 articles (no literature support)")

    # ClinicalTrials.gov
    if trials.get("total_matching", 0) > 0:
        sources_queried += 1
        sources_positive += 1
        details.append(f"ClinicalTrials.gov: {trials['total_matching']} matching trials")
    elif trials.get("status") == "ok":
        sources_queried += 1
        details.append("ClinicalTrials.gov: no matching trials")

    score = sources_positive / sources_queried if sources_queried > 0 else 0

    return {
        "concordance_score": round(score, 2),
        "sources_positive": sources_positive,
        "sources_queried": sources_queried,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def _verdict(signal: dict, concordance: dict, label: dict) -> tuple:
    """Determine final verdict and recommendation."""
    strength = signal.get("signal_strength", "noise")
    conc = concordance.get("concordance_score", 0)
    on_label = label.get("on_label")

    if strength == "strong" and conc >= 0.6:
        verdict = "CONFIRMED_SIGNAL"
        rec = "Initiate causality assessment and regulatory review. Cross-database concordance supports signal."
    elif strength == "strong" or (strength == "moderate" and conc >= 0.5):
        verdict = "PROBABLE_SIGNAL"
        rec = "Schedule causality assessment. Continue monitoring with increased frequency."
    elif strength == "moderate":
        verdict = "POSSIBLE_SIGNAL"
        rec = "Continue monitoring. Collect additional data before escalation."
    elif strength == "weak":
        verdict = "INSUFFICIENT_DATA"
        rec = "Monitor passively. Revisit when more data accumulates."
    else:
        verdict = "NO_SIGNAL"
        rec = "No action required at this time."

    # Escalate if not on label
    if on_label is False and strength in ("strong", "moderate"):
        verdict = "CONFIRMED_SIGNAL" if verdict == "PROBABLE_SIGNAL" else verdict
        rec = f"POTENTIAL NEW SIGNAL — not on current labeling. {rec}"

    return verdict, rec


# ---------------------------------------------------------------------------
# Tool: triangulate-signal (full)
# ---------------------------------------------------------------------------

def triangulate_signal(args: dict) -> dict:
    """Full cross-database signal triangulation."""
    drug = (args.get("drug") or args.get("drug_name") or args.get("substance") or "").strip()
    event = (args.get("event") or args.get("reaction") or "").strip()

    if not drug or not event:
        return {"status": "error", "message": "Both 'drug' and 'event' are required"}

    start = time.time()

    # Query all databases in parallel
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(_query_faers, drug, event): "faers",
            pool.submit(_query_eudravigilance, drug): "eudravigilance",
            pool.submit(_query_vigiaccess, drug): "vigiaccess",
            pool.submit(_query_dailymed, drug, event): "dailymed",
            pool.submit(_query_pubmed, drug, event): "pubmed",
            pool.submit(_query_clinicaltrials, drug, event): "clinicaltrials",
        }

        results = {}
        for future in as_completed(futures, timeout=30):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                results[key] = {"status": "error", "message": str(e)}

    faers = results.get("faers", {})
    eudra = results.get("eudravigilance", {})
    vigi = results.get("vigiaccess", {})
    label = results.get("dailymed", {})
    pubmed = results.get("pubmed", {})
    trials = results.get("clinicaltrials", {})

    # Compute disproportionality from FAERS contingency table
    dispro = _compute_disproportionality(faers.get("contingency", {}))

    # Classify signal strength
    signal = _classify_signal(dispro, faers.get("cases", 0))

    # Score concordance across databases
    concordance = _score_concordance(faers, eudra, vigi, label, pubmed, trials)

    # Final verdict
    verdict, recommendation = _verdict(signal, concordance, label)

    elapsed = round(time.time() - start, 2)

    return {
        "status": "ok",
        "drug": drug,
        "event": event,
        "databases": {
            "faers": faers,
            "eudravigilance": eudra,
            "vigiaccess": vigi,
            "dailymed": {
                "on_label": label.get("on_label"),
                "boxed_warning": label.get("boxed_warning", False),
            },
            "pubmed": {
                "article_count": pubmed.get("article_count", 0),
                "top_pmids": pubmed.get("top_pmids", []),
            },
            "clinicaltrials": {
                "trials_found": trials.get("total_matching", 0),
                "top_trials": trials.get("top_trials", []),
            },
        },
        "disproportionality": dispro,
        "signal_classification": signal,
        "concordance": concordance,
        "verdict": verdict,
        "recommendation": recommendation,
        "elapsed_seconds": elapsed,
        "data_sources": ["FAERS", "EudraVigilance", "VigiAccess", "DailyMed", "PubMed", "ClinicalTrials.gov"],
        "data_source": DATA_SOURCE,
    }


# ---------------------------------------------------------------------------
# Tool: quick-triangulate (fast screening)
# ---------------------------------------------------------------------------

def quick_triangulate(args: dict) -> dict:
    """Fast FAERS-only triangulation for rapid screening."""
    drug = (args.get("drug") or args.get("drug_name") or "").strip()
    event = (args.get("event") or args.get("reaction") or "").strip()

    if not drug or not event:
        return {"status": "error", "message": "Both 'drug' and 'event' are required"}

    start = time.time()

    # FAERS + DailyMed only (parallel)
    with ThreadPoolExecutor(max_workers=2) as pool:
        faers_f = pool.submit(_query_faers, drug, event)
        label_f = pool.submit(_query_dailymed, drug, event)
        faers = faers_f.result()
        label = label_f.result()

    dispro = _compute_disproportionality(faers.get("contingency", {}))
    signal = _classify_signal(dispro, faers.get("cases", 0))

    return {
        "status": "ok",
        "drug": drug,
        "event": event,
        "cases": faers.get("cases", 0),
        "prr": dispro.get("PRR", 0),
        "prr_ci": dispro.get("PRR_CI", [0, 0]),
        "ror": dispro.get("ROR", 0),
        "ror_ci": dispro.get("ROR_CI", [0, 0]),
        "ic": dispro.get("IC", 0),
        "chi_squared": dispro.get("chi_squared", 0),
        "on_label": label.get("on_label"),
        "signal_strength": signal.get("signal_strength", "unknown"),
        "verdict": "SIGNAL" if signal.get("signal_strength") in ("strong", "moderate") else "NO_SIGNAL",
        "elapsed_seconds": round(time.time() - start, 2),
        "data_source": DATA_SOURCE,
    }


# ---------------------------------------------------------------------------
# Tool: batch-triangulate
# ---------------------------------------------------------------------------

def batch_triangulate(args: dict) -> dict:
    """Batch screening of multiple drug-event pairs."""
    pairs = args.get("pairs", [])
    if not pairs:
        return {"status": "error", "message": "'pairs' array is required"}

    results = []
    flagged = 0

    for pair in pairs[:20]:  # Cap at 20 pairs
        drug = pair.get("drug", "")
        event = pair.get("event", "")
        if not drug or not event:
            results.append({"drug": drug, "event": event, "status": "skipped", "reason": "missing drug or event"})
            continue

        r = quick_triangulate({"drug": drug, "event": event})
        if r.get("signal_strength") in ("strong", "moderate"):
            flagged += 1
            r["flagged"] = True
        else:
            r["flagged"] = False
        results.append(r)

    return {
        "status": "ok",
        "total_screened": len(results),
        "flagged_count": flagged,
        "results": results,
        "data_source": DATA_SOURCE,
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

TOOL_DISPATCH = {
    "triangulate-signal": triangulate_signal,
    "quick-triangulate": quick_triangulate,
    "batch-triangulate": batch_triangulate,
}


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"status": "error", "message": "No input on stdin"}))
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "message": f"Invalid JSON: {exc}"}))
        sys.exit(1)

    tool_name = ensure_str(payload.get("tool", "")).strip()
    args = payload.get("arguments", payload.get("args", {}))

    if tool_name not in TOOL_DISPATCH:
        print(json.dumps({
            "status": "error",
            "message": f"Unknown tool '{tool_name}'. Available: {list(TOOL_DISPATCH.keys())}",
        }))
        sys.exit(1)

    result = TOOL_DISPATCH[tool_name](args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
