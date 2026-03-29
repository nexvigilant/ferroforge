#!/usr/bin/env python3
"""
Pharma Company Proxy — unified proxy for all pharmaceutical company configs.

Routes to public regulatory APIs (openFDA, ClinicalTrials.gov) filtered by
manufacturer/sponsor name. Each pharma config injects its company_key via
dispatch.py's company injection layer.

Usage:
    echo '{"tool": "get-portfolio", "arguments": {"company_key": "pfizer"}}' | python3 pharma_proxy.py

Data sources (all free, no API key required):
  - openFDA drug label API: approved products, labeling sections
  - openFDA FAERS API: adverse event reports by manufacturer
  - openFDA enforcement API: recalls by manufacturer
  - ClinicalTrials.gov API v2: clinical trials by sponsor

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.
"""

import json
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

OPENFDA_LABEL = "https://api.fda.gov/drug/label.json"
OPENFDA_EVENT = "https://api.fda.gov/drug/event.json"
OPENFDA_ENFORCE = "https://api.fda.gov/drug/enforcement.json"
CT_GOV = "https://clinicaltrials.gov/api/v2/studies"
REQUEST_TIMEOUT = 20
_RETRY_CODES = {429, 503}
_MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Company Registry
# ---------------------------------------------------------------------------

COMPANY_REGISTRY = {
    "pfizer": {
        "display_name": "Pfizer Inc.",
        "openfda_manufacturer": ["PFIZER", "PFIZER INC", "PFIZER LABORATORIES"],
        "ct_sponsor": "Pfizer",
    },
    "novartis": {
        "display_name": "Novartis AG",
        "openfda_manufacturer": ["NOVARTIS", "NOVARTIS PHARMACEUTICALS"],
        "ct_sponsor": "Novartis",
    },
    "roche": {
        "display_name": "Roche Holding AG",
        "openfda_manufacturer": ["ROCHE", "GENENTECH", "GENENTECH INC"],
        "ct_sponsor": "Hoffmann-La Roche",
    },
    "jnj": {
        "display_name": "Johnson & Johnson",
        "openfda_manufacturer": ["JANSSEN", "JANSSEN PHARMACEUTICALS", "JOHNSON AND JOHNSON"],
        "ct_sponsor": "Janssen",
    },
    "merck": {
        "display_name": "Merck & Co.",
        "openfda_manufacturer": ["MERCK", "MERCK SHARP AND DOHME", "MERCK AND CO"],
        "ct_sponsor": "Merck Sharp & Dohme",
    },
    "astrazeneca": {
        "display_name": "AstraZeneca PLC",
        "openfda_manufacturer": ["ASTRAZENECA", "ASTRAZENECA PHARMACEUTICALS"],
        "ct_sponsor": "AstraZeneca",
    },
    "gsk": {
        "display_name": "GSK plc",
        "openfda_manufacturer": ["GLAXOSMITHKLINE", "GSK", "GLAXO"],
        "ct_sponsor": "GlaxoSmithKline",
    },
    "sanofi": {
        "display_name": "Sanofi S.A.",
        "openfda_manufacturer": ["SANOFI", "SANOFI-AVENTIS", "SANOFI AVENTIS"],
        "ct_sponsor": "Sanofi",
    },
    "abbvie": {
        "display_name": "AbbVie Inc.",
        "openfda_manufacturer": ["ABBVIE", "ABBVIE INC"],
        "ct_sponsor": "AbbVie",
    },
    "lilly": {
        "display_name": "Eli Lilly and Company",
        "openfda_manufacturer": ["ELI LILLY", "ELI LILLY AND COMPANY", "LILLY"],
        "ct_sponsor": "Eli Lilly",
    },
    "bms": {
        "display_name": "Bristol-Myers Squibb",
        "openfda_manufacturer": ["BRISTOL-MYERS SQUIBB", "BRISTOL MYERS SQUIBB", "BMS", "E.R. SQUIBB & SONS, L.L.C.", "E.R. SQUIBB"],
        "ct_sponsor": "Bristol-Myers Squibb",
    },
    "novonordisk": {
        "display_name": "Novo Nordisk A/S",
        "openfda_manufacturer": ["NOVO NORDISK", "NOVO NORDISK INC"],
        "ct_sponsor": "Novo Nordisk",
    },
    "amgen": {
        "display_name": "Amgen Inc.",
        "openfda_manufacturer": ["AMGEN", "AMGEN INC"],
        "ct_sponsor": "Amgen",
    },
    "gilead": {
        "display_name": "Gilead Sciences Inc.",
        "openfda_manufacturer": ["GILEAD", "GILEAD SCIENCES"],
        "ct_sponsor": "Gilead Sciences",
    },
    "bayer": {
        "display_name": "Bayer AG",
        "openfda_manufacturer": ["BAYER", "BAYER HEALTHCARE", "BAYER PHARMA"],
        "ct_sponsor": "Bayer",
    },
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _fetch(url: str) -> dict:
    """Execute HTTP GET, return parsed JSON. Retries on 429/503."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "NexVigilant-FerroForge/1.0 (ferroforge@nexvigilant.com)"},
    )
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in _RETRY_CODES and attempt < _MAX_RETRIES - 1:
                time.sleep(0.2 * (3 ** attempt))
                last_exc = exc
                continue
            # 404 = no results, not a crash
            if exc.code == 404:
                return {}
            error_body = {}
            try:
                error_body = json.loads(exc.read().decode("utf-8"))
            except Exception:
                pass
            msg = error_body.get("error", {}).get("message", exc.reason) if error_body else exc.reason
            raise RuntimeError(f"HTTP {exc.code}: {msg}") from exc
        except urllib.error.URLError as exc:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(0.2 * (3 ** attempt))
                last_exc = exc
                continue
            raise RuntimeError(f"Network error: {exc.reason}") from exc
    raise RuntimeError(f"Failed after {_MAX_RETRIES} retries: {last_exc}")


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _manufacturer_search(company_key: str, prefix: str = "openfda") -> str:
    """Build an openFDA search clause matching any known manufacturer name.

    For label API: prefix="openfda" → openfda.manufacturer_name:"X"
    For FAERS API: prefix="patient.drug.openfda" → patient.drug.openfda.manufacturer_name:"X"
    For enforcement API: pass use_recalling_firm=True instead.
    """
    info = COMPANY_REGISTRY.get(company_key, {})
    names = info.get("openfda_manufacturer", [])
    if not names:
        return f'{prefix}.manufacturer_name:"{_quote(company_key)}"'
    clauses = [f'{prefix}.manufacturer_name:"{_quote(n)}"' for n in names]
    if len(clauses) == 1:
        return clauses[0]
    return "(" + "+OR+".join(clauses) + ")"


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def get_portfolio(company_key: str, args: dict) -> dict:
    """Fetch approved product portfolio from openFDA labels."""
    limit = min(int(args.get("limit", 25)), 100)
    search = _manufacturer_search(company_key)
    url = f"{OPENFDA_LABEL}?search={search}&limit={limit}&sort=effective_time:desc"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "company": company_key}

    results = data.get("results", [])
    if not results:
        return {"status": "not_found", "message": f"No products found for {company_key}", "company": company_key}

    products = []
    seen = set()
    for label in results:
        ofd = label.get("openfda", {})
        brand = (ofd.get("brand_name") or [None])[0]
        generic = (ofd.get("generic_name") or [None])[0]
        key = (brand or "", generic or "")
        if key in seen:
            continue
        seen.add(key)
        products.append({
            "brand_name": brand,
            "generic_name": generic,
            "route": ofd.get("route", []),
            "application_number": (ofd.get("application_number") or [None])[0],
            "pharm_class_epc": ofd.get("pharm_class_epc", []),
            "manufacturer": (ofd.get("manufacturer_name") or [None])[0],
            "product_type": (ofd.get("product_type") or [None])[0],
        })

    info = COMPANY_REGISTRY.get(company_key, {})
    return {
        "status": "ok",
        "company": info.get("display_name", company_key),
        "product_count": len(products),
        "products": products,
        "sources": ["openFDA drug labels"],
    }


def get_pipeline(company_key: str, args: dict) -> dict:
    """Fetch clinical trial pipeline from ClinicalTrials.gov API v2."""
    info = COMPANY_REGISTRY.get(company_key, {})
    sponsor = info.get("ct_sponsor", company_key)
    limit = min(int(args.get("limit", 20)), 50)

    params = {
        "query.spons": sponsor,
        "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING,ENROLLING_BY_INVITATION",
        "pageSize": str(limit),
    }

    phase = args.get("phase")
    if phase:
        params["filter.phase"] = phase

    condition = args.get("condition")
    if condition:
        params["query.cond"] = condition

    query_string = "&".join(f"{k}={_quote(v)}" for k, v in params.items())
    url = f"{CT_GOV}?{query_string}"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "company": company_key}

    studies = data.get("studies", [])
    trials = []
    for study in studies:
        proto = study.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        status_mod = proto.get("statusModule", {})
        design = proto.get("designModule", {})
        cond_mod = proto.get("conditionsModule", {})
        arms_mod = proto.get("armsInterventionsModule", {})

        interventions = []
        for interv in (arms_mod.get("interventions") or []):
            interventions.append(interv.get("name", ""))

        trials.append({
            "nct_id": ident.get("nctId"),
            "title": ident.get("briefTitle"),
            "status": status_mod.get("overallStatus"),
            "phase": (design.get("phases") or ["N/A"])[0] if design.get("phases") else "N/A",
            "conditions": cond_mod.get("conditions", []),
            "interventions": interventions[:5],
            "start_date": (status_mod.get("startDateStruct") or {}).get("date"),
            "enrollment": (design.get("enrollmentInfo") or {}).get("count"),
        })

    return {
        "status": "ok",
        "company": info.get("display_name", company_key),
        "trial_count": len(trials),
        "total_available": data.get("totalCount", len(trials)),
        "trials": trials,
        "sources": ["ClinicalTrials.gov API v2"],
    }


def get_safety_profile(company_key: str, args: dict) -> dict:
    """Aggregate FAERS safety profile across all company products."""
    search = _manufacturer_search(company_key, prefix="patient.drug.openfda")
    product_filter = args.get("product")
    if product_filter:
        search = f"{search}+AND+patient.drug.openfda.generic_name:\"{_quote(product_filter)}\""

    # Sub-query 1: Top reactions
    top_reactions = []
    url1 = f"{OPENFDA_EVENT}?search={search}&count=patient.reaction.reactionmeddrapt.exact"
    try:
        data = _fetch(url1)
        for item in data.get("results", [])[:25]:
            top_reactions.append({
                "reaction": item.get("term"),
                "report_count": item.get("count"),
            })
    except RuntimeError:
        pass

    # Sub-query 2: Top products by report count
    top_products = []
    url2 = f"{OPENFDA_EVENT}?search={search}&count=patient.drug.openfda.generic_name.exact"
    try:
        data = _fetch(url2)
        for item in data.get("results", [])[:20]:
            top_products.append({
                "product": item.get("term"),
                "report_count": item.get("count"),
            })
    except RuntimeError:
        pass

    # Sub-query 3: Serious vs non-serious
    outcome_dist = {}
    url3 = f"{OPENFDA_EVENT}?search={search}&count=serious"
    try:
        data = _fetch(url3)
        for item in data.get("results", []):
            label = "serious" if item.get("term") == 1 else "non_serious"
            outcome_dist[label] = item.get("count", 0)
    except RuntimeError:
        pass

    if not top_reactions and not top_products:
        return {"status": "not_found", "message": f"No FAERS data for {company_key}", "company": company_key}

    total = sum(outcome_dist.values()) if outcome_dist else None
    info = COMPANY_REGISTRY.get(company_key, {})
    return {
        "status": "ok",
        "company": info.get("display_name", company_key),
        "total_reports": total,
        "top_reactions": top_reactions,
        "top_products_by_reports": top_products,
        "outcome_distribution": outcome_dist,
        "sources": ["openFDA FAERS"],
    }


def get_recalls(company_key: str, args: dict) -> dict:
    """Fetch product recalls from openFDA enforcement."""
    info = COMPANY_REGISTRY.get(company_key, {})
    names = info.get("openfda_manufacturer", [company_key])
    limit = min(int(args.get("limit", 20)), 100)

    # Enforcement API uses recalling_firm, not openfda.manufacturer_name
    clauses = [f'recalling_firm:"{_quote(n)}"' for n in names]
    search = clauses[0] if len(clauses) == 1 else "(" + "+OR+".join(clauses) + ")"

    classification = args.get("classification")
    if classification:
        search = f"{search}+AND+classification:\"{_quote(classification)}\""

    url = f"{OPENFDA_ENFORCE}?search={search}&limit={limit}&sort=report_date:desc"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "company": company_key}

    results = data.get("results", [])
    recalls = []
    for r in results:
        recalls.append({
            "recall_number": r.get("recall_number"),
            "product_description": (r.get("product_description") or "")[:300],
            "reason": (r.get("reason_for_recall") or "")[:300],
            "classification": r.get("classification"),
            "status": r.get("status"),
            "report_date": r.get("report_date"),
            "voluntary_mandated": r.get("voluntary_mandated"),
        })

    return {
        "status": "ok",
        "company": info.get("display_name", company_key),
        "recall_count": len(recalls),
        "recalls": recalls,
        "sources": ["openFDA enforcement"],
    }


def get_labeling_changes(company_key: str, args: dict) -> dict:
    """Fetch recent labeling changes from openFDA."""
    import datetime
    since_year = int(args.get("since_year", datetime.date.today().year - 2))
    limit = min(int(args.get("limit", 20)), 100)
    search = _manufacturer_search(company_key)
    search = f"{search}+AND+effective_time:[{since_year}0101+TO+20271231]"
    url = f"{OPENFDA_LABEL}?search={search}&limit={limit}&sort=effective_time:desc"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "company": company_key}

    results = data.get("results", [])
    changes = []
    for label in results:
        ofd = label.get("openfda", {})
        changes.append({
            "brand_name": (ofd.get("brand_name") or [None])[0],
            "generic_name": (ofd.get("generic_name") or [None])[0],
            "effective_date": label.get("effective_time"),
            "has_boxed_warning": bool(label.get("boxed_warning")),
            "application_number": (ofd.get("application_number") or [None])[0],
            "manufacturer": (ofd.get("manufacturer_name") or [None])[0],
        })

    info = COMPANY_REGISTRY.get(company_key, {})
    return {
        "status": "ok",
        "company": info.get("display_name", company_key),
        "since_year": since_year,
        "change_count": len(changes),
        "changes": changes,
        "sources": ["openFDA drug labels"],
    }


def search_products(company_key: str, args: dict) -> dict:
    """Search company products by keyword."""
    query = (args.get("query") or args.get("search") or "").strip()
    if not query:
        return {"status": "error", "message": "query parameter is required", "company": company_key}

    limit = min(int(args.get("limit", 10)), 50)
    mfr = _manufacturer_search(company_key)
    q = _quote(query)
    search = f"{mfr}+AND+({q})"
    url = f"{OPENFDA_LABEL}?search={search}&limit={limit}"

    try:
        data = _fetch(url)
    except RuntimeError as exc:
        return {"status": "error", "message": str(exc), "company": company_key}

    results = data.get("results", [])
    products = []
    seen = set()
    for label in results:
        ofd = label.get("openfda", {})
        brand = (ofd.get("brand_name") or [None])[0]
        generic = (ofd.get("generic_name") or [None])[0]
        key = (brand or "", generic or "")
        if key in seen:
            continue
        seen.add(key)
        products.append({
            "brand_name": brand,
            "generic_name": generic,
            "route": ofd.get("route", []),
            "pharm_class_epc": ofd.get("pharm_class_epc", []),
            "manufacturer": (ofd.get("manufacturer_name") or [None])[0],
        })

    info = COMPANY_REGISTRY.get(company_key, {})
    return {
        "status": "ok",
        "company": info.get("display_name", company_key),
        "query": query,
        "result_count": len(products),
        "products": products,
        "sources": ["openFDA drug labels"],
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def get_head_to_head(company_key: str, args: dict) -> dict:
    """Compare adverse event reporting between this company and a competitor.

    Computes PRR (Proportional Reporting Ratio) for a specific event for each
    company's products, enabling head-to-head safety signal comparison.
    """
    competitor = (args.get("competitor") or "").strip().lower()
    event = (args.get("event") or "").strip()
    if not competitor:
        return {"status": "error", "message": "competitor parameter required (e.g. 'novartis')", "company": company_key}
    if not event:
        return {"status": "error", "message": "event parameter required (e.g. 'nausea')", "company": company_key}
    if competitor not in COMPANY_REGISTRY:
        return {"status": "error", "message": f"Unknown competitor '{competitor}'. Known: {list(COMPANY_REGISTRY.keys())}", "company": company_key}

    drug_class = args.get("drug_class")

    def _faers_counts(ckey: str) -> dict:
        """Get (event_count, total_count) for a company from FAERS."""
        search = _manufacturer_search(ckey, prefix="patient.drug.openfda")
        if drug_class:
            search = f"{search}+AND+patient.drug.openfda.pharm_class_epc:\"{_quote(drug_class)}\""

        # Total reports for this company
        total = 0
        url_total = f"{OPENFDA_EVENT}?search={search}&count=serious"
        try:
            data = _fetch(url_total)
            for item in data.get("results", []):
                total += item.get("count", 0)
        except RuntimeError:
            pass

        # Reports with this specific event
        event_count = 0
        event_q = _quote(event.upper())
        url_event = f"{OPENFDA_EVENT}?search={search}+AND+patient.reaction.reactionmeddrapt:\"{event_q}\"&count=serious"
        try:
            data = _fetch(url_event)
            for item in data.get("results", []):
                event_count += item.get("count", 0)
        except RuntimeError:
            pass

        return {"event_count": event_count, "total_count": total}

    # Parallel-safe: collect data for both companies
    company_data = _faers_counts(company_key)
    competitor_data = _faers_counts(competitor)

    # Compute PRR for each
    def _prr(event_count: int, total: int, other_event: int, other_total: int) -> float | None:
        """PRR = (a/a+b) / (c/c+d) where a=event_this, b=non_event_this, c=event_other, d=non_event_other."""
        if total == 0 or other_total == 0:
            return None
        rate_this = event_count / total
        rate_other = other_event / other_total
        if rate_other == 0:
            return None
        return round(rate_this / rate_other, 4)

    prr_company = _prr(
        company_data["event_count"], company_data["total_count"],
        competitor_data["event_count"], competitor_data["total_count"],
    )
    prr_competitor = _prr(
        competitor_data["event_count"], competitor_data["total_count"],
        company_data["event_count"], company_data["total_count"],
    )

    info_a = COMPANY_REGISTRY.get(company_key, {})
    info_b = COMPANY_REGISTRY.get(competitor, {})

    return {
        "status": "ok",
        "event": event,
        "drug_class_filter": drug_class,
        "company_a": {
            "name": info_a.get("display_name", company_key),
            "event_reports": company_data["event_count"],
            "total_reports": company_data["total_count"],
            "event_rate": round(company_data["event_count"] / company_data["total_count"], 6) if company_data["total_count"] else None,
            "prr_vs_competitor": prr_company,
        },
        "company_b": {
            "name": info_b.get("display_name", competitor),
            "event_reports": competitor_data["event_count"],
            "total_reports": competitor_data["total_count"],
            "event_rate": round(competitor_data["event_count"] / competitor_data["total_count"], 6) if competitor_data["total_count"] else None,
            "prr_vs_competitor": prr_competitor,
        },
        "interpretation": (
            f"PRR>1 indicates higher proportional reporting of '{event}'. "
            "PRR>2 with >=3 cases is a traditional signal threshold."
        ),
        "sources": ["openFDA FAERS"],
    }


TOOL_DISPATCH = {
    "get-portfolio": get_portfolio,
    "get-pipeline": get_pipeline,
    "get-safety-profile": get_safety_profile,
    "get-recalls": get_recalls,
    "get-labeling-changes": get_labeling_changes,
    "search-products": search_products,
    "get-head-to-head": get_head_to_head,
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

    raw_tool = payload.get("tool", "").strip()
    args = payload.get("arguments", payload.get("args", {}))
    company_key = args.pop("company_key", None)

    # Resolve company_key from tool name if not injected by dispatch.py.
    # Production path: Rust router sends bare tool name (e.g., "get-portfolio")
    # plus a request_id. The config domain tells us which company.
    # Fallback: check if the raw tool name contains a company prefix
    # (e.g., "www_pfizer_com_get_portfolio" from MCP dispatch).
    if not company_key or company_key == "unknown":
        # Try to extract from prefixed tool name
        for key in COMPANY_REGISTRY:
            # Match both www_{key}_com_ and {key}_ patterns
            prefix = f"www_{key}_com_"
            if raw_tool.startswith(prefix):
                company_key = key
                raw_tool = raw_tool[len(prefix):].replace("_", "-")
                break
        else:
            # Last resort: check if company was passed as an argument
            company_key = (args.pop("company", None) or
                           args.pop("company_key", None) or
                           "unknown")

    # Normalize tool name: MCP sends underscores, proxy expects hyphens
    tool_name = raw_tool.replace("_", "-") if "_" in raw_tool and raw_tool not in TOOL_DISPATCH else raw_tool

    if tool_name not in TOOL_DISPATCH:
        print(json.dumps({
            "status": "error",
            "message": f"Unknown tool '{tool_name}'. Known: {list(TOOL_DISPATCH.keys())}",
        }))
        sys.exit(1)

    try:
        result = TOOL_DISPATCH[tool_name](company_key, args)
    except Exception as exc:
        result = {"status": "error", "message": f"{type(exc).__name__}: {exc}"}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
