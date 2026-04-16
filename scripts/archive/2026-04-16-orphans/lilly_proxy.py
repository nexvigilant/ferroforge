#!/usr/bin/env python3
"""
Eli Lilly Proxy — curated Lilly product data enriched with live DailyMed/openFDA safety data.

Usage:
    echo '{"tool": "get-products", "args": {"therapeutic_area": "diabetes"}}' | python3 lilly_proxy.py
    echo '{"tool": "get-safety-info", "args": {"product": "mounjaro"}}' | python3 lilly_proxy.py
    echo '{"tool": "get-pipeline", "args": {"phase": "3"}}' | python3 lilly_proxy.py

Data sources:
  - Curated Lilly product catalog (brand names, generics, therapeutic areas)
  - openFDA drug label API: boxed warnings, adverse reactions, contraindications
  - Lilly.com resource URLs: prescribing info, medication guides, HCP letters

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.
"""

import json
import sys
import urllib.parse
import urllib.request
import urllib.error


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



OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"
REQUEST_TIMEOUT_SECONDS = 20
_RETRY_CODES = {429, 503}
_MAX_RETRIES = 3


def _fetch(url: str) -> dict:
    """Execute an HTTP GET and return parsed JSON. Retries on 429/503."""
    import time
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "NexVigilant-FerroForge/1.0 (ferroforge@nexvigilant.com)"},
    )
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            if exc.code in _RETRY_CODES and attempt < _MAX_RETRIES - 1:
                time.sleep(0.2 * (3 ** attempt))
                last_exc = exc
                continue
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


# ---------------------------------------------------------------------------
# Curated Lilly product catalog
# ---------------------------------------------------------------------------
# Source: lilly.com/products, investor pipeline disclosures, FDA labels.
# Maintained manually — update when Lilly announces new approvals.

LILLY_PRODUCTS = [
    {
        "brand_name": "Mounjaro",
        "generic_name": "tirzepatide",
        "therapeutic_area": "Diabetes",
        "indication": "Type 2 diabetes mellitus",
        "mechanism": "GIP and GLP-1 receptor agonist",
        "approval_year": 2022,
        "prescribing_info_url": "https://uspl.lilly.com/mounjaro/mounjaro.html",
        "medication_guide_url": "https://uspl.lilly.com/mounjaro/mounjaro.html#mg",
    },
    {
        "brand_name": "Zepbound",
        "generic_name": "tirzepatide",
        "therapeutic_area": "Obesity",
        "indication": "Chronic weight management",
        "mechanism": "GIP and GLP-1 receptor agonist",
        "approval_year": 2023,
        "prescribing_info_url": "https://uspl.lilly.com/zepbound/zepbound.html",
        "medication_guide_url": "https://uspl.lilly.com/zepbound/zepbound.html#mg",
    },
    {
        "brand_name": "Trulicity",
        "generic_name": "dulaglutide",
        "therapeutic_area": "Diabetes",
        "indication": "Type 2 diabetes mellitus",
        "mechanism": "GLP-1 receptor agonist",
        "approval_year": 2014,
        "prescribing_info_url": "https://uspl.lilly.com/trulicity/trulicity.html",
        "medication_guide_url": "https://uspl.lilly.com/trulicity/trulicity.html#mg",
    },
    {
        "brand_name": "Humalog",
        "generic_name": "insulin lispro",
        "therapeutic_area": "Diabetes",
        "indication": "Diabetes mellitus (Type 1 and Type 2)",
        "mechanism": "Rapid-acting insulin analog",
        "approval_year": 1996,
        "prescribing_info_url": "https://uspl.lilly.com/humalog/humalog.html",
        "medication_guide_url": "https://uspl.lilly.com/humalog/humalog.html#mg",
    },
    {
        "brand_name": "Jardiance",
        "generic_name": "empagliflozin",
        "therapeutic_area": "Diabetes",
        "indication": "Type 2 diabetes mellitus; heart failure",
        "mechanism": "SGLT2 inhibitor",
        "approval_year": 2014,
        "prescribing_info_url": "https://docs.boehringer-ingelheim.com/Prescribing%20Information/PIs/Jardiance/jardiance.pdf",
        "medication_guide_url": None,
        "note": "Co-marketed with Boehringer Ingelheim",
    },
    {
        "brand_name": "Verzenio",
        "generic_name": "abemaciclib",
        "therapeutic_area": "Oncology",
        "indication": "HR+/HER2- breast cancer",
        "mechanism": "CDK4/6 inhibitor",
        "approval_year": 2017,
        "prescribing_info_url": "https://uspl.lilly.com/verzenio/verzenio.html",
        "medication_guide_url": "https://uspl.lilly.com/verzenio/verzenio.html#mg",
    },
    {
        "brand_name": "Olumiant",
        "generic_name": "baricitinib",
        "therapeutic_area": "Immunology",
        "indication": "Rheumatoid arthritis; alopecia areata",
        "mechanism": "JAK1/JAK2 inhibitor",
        "approval_year": 2018,
        "prescribing_info_url": "https://uspl.lilly.com/olumiant/olumiant.html",
        "medication_guide_url": "https://uspl.lilly.com/olumiant/olumiant.html#mg",
    },
    {
        "brand_name": "Taltz",
        "generic_name": "ixekizumab",
        "therapeutic_area": "Immunology",
        "indication": "Plaque psoriasis; psoriatic arthritis; ankylosing spondylitis",
        "mechanism": "IL-17A antagonist",
        "approval_year": 2016,
        "prescribing_info_url": "https://uspl.lilly.com/taltz/taltz.html",
        "medication_guide_url": "https://uspl.lilly.com/taltz/taltz.html#mg",
    },
    {
        "brand_name": "Emgality",
        "generic_name": "galcanezumab-gnlm",
        "therapeutic_area": "Neuroscience",
        "indication": "Migraine prevention; episodic cluster headache",
        "mechanism": "CGRP antagonist",
        "approval_year": 2018,
        "prescribing_info_url": "https://uspl.lilly.com/emgality/emgality.html",
        "medication_guide_url": "https://uspl.lilly.com/emgality/emgality.html#mg",
    },
    {
        "brand_name": "Cyramza",
        "generic_name": "ramucirumab",
        "therapeutic_area": "Oncology",
        "indication": "Gastric cancer; NSCLC; CRC; HCC",
        "mechanism": "VEGFR2 antagonist",
        "approval_year": 2014,
        "prescribing_info_url": "https://uspl.lilly.com/cyramza/cyramza.html",
        "medication_guide_url": None,
    },
    {
        "brand_name": "Retevmo",
        "generic_name": "selpercatinib",
        "therapeutic_area": "Oncology",
        "indication": "RET fusion-positive NSCLC, thyroid cancer, solid tumors",
        "mechanism": "RET kinase inhibitor",
        "approval_year": 2020,
        "prescribing_info_url": "https://uspl.lilly.com/retevmo/retevmo.html",
        "medication_guide_url": "https://uspl.lilly.com/retevmo/retevmo.html#mg",
    },
    {
        "brand_name": "Jaypirca",
        "generic_name": "pirtobrutinib",
        "therapeutic_area": "Oncology",
        "indication": "Mantle cell lymphoma (relapsed/refractory)",
        "mechanism": "Non-covalent BTK inhibitor",
        "approval_year": 2023,
        "prescribing_info_url": "https://uspl.lilly.com/jaypirca/jaypirca.html",
        "medication_guide_url": None,
    },
    {
        "brand_name": "Ebglyss",
        "generic_name": "lebrikizumab",
        "therapeutic_area": "Immunology",
        "indication": "Atopic dermatitis",
        "mechanism": "IL-13 antagonist",
        "approval_year": 2024,
        "prescribing_info_url": "https://uspl.lilly.com/ebglyss/ebglyss.html",
        "medication_guide_url": "https://uspl.lilly.com/ebglyss/ebglyss.html#mg",
    },
    {
        "brand_name": "Kisunla",
        "generic_name": "donanemab-azbt",
        "therapeutic_area": "Neuroscience",
        "indication": "Early symptomatic Alzheimer disease",
        "mechanism": "Anti-amyloid beta antibody",
        "approval_year": 2024,
        "prescribing_info_url": "https://uspl.lilly.com/kisunla/kisunla.html",
        "medication_guide_url": "https://uspl.lilly.com/kisunla/kisunla.html#mg",
    },
    {
        "brand_name": "Omvoh",
        "generic_name": "mirikizumab-mrkz",
        "therapeutic_area": "Immunology",
        "indication": "Ulcerative colitis",
        "mechanism": "IL-23p19 antagonist",
        "approval_year": 2023,
        "prescribing_info_url": "https://uspl.lilly.com/omvoh/omvoh.html",
        "medication_guide_url": "https://uspl.lilly.com/omvoh/omvoh.html#mg",
    },
]

# Lookup by brand name (case-insensitive)
_PRODUCT_INDEX: dict[str, dict] = {
    p["brand_name"].lower(): p for p in LILLY_PRODUCTS
}
# Also index by generic name
for p in LILLY_PRODUCTS:
    gen = p["generic_name"].lower().split("-")[0]  # strip suffix like -gnlm
    if gen not in _PRODUCT_INDEX:
        _PRODUCT_INDEX[gen] = p


# ---------------------------------------------------------------------------
# Curated pipeline candidates
# ---------------------------------------------------------------------------
# Source: lilly.com/pipeline, Q4 2025 investor disclosures.

LILLY_PIPELINE = [
    {"molecule": "tirzepatide", "indication": "Heart failure with preserved ejection fraction (HFpEF)", "phase": "3", "therapeutic_area": "Cardiometabolic", "mechanism": "GIP/GLP-1 receptor agonist"},
    {"molecule": "tirzepatide", "indication": "Obstructive sleep apnea", "phase": "3", "therapeutic_area": "Cardiometabolic", "mechanism": "GIP/GLP-1 receptor agonist"},
    {"molecule": "orforglipron", "indication": "Type 2 diabetes mellitus", "phase": "3", "therapeutic_area": "Diabetes", "mechanism": "Oral GLP-1 receptor agonist"},
    {"molecule": "orforglipron", "indication": "Obesity/weight management", "phase": "3", "therapeutic_area": "Obesity", "mechanism": "Oral GLP-1 receptor agonist"},
    {"molecule": "retatrutide", "indication": "Obesity/weight management", "phase": "3", "therapeutic_area": "Obesity", "mechanism": "GIP/GLP-1/glucagon receptor agonist"},
    {"molecule": "donanemab", "indication": "Alzheimer disease prevention (DIAN-TU)", "phase": "3", "therapeutic_area": "Neuroscience", "mechanism": "Anti-amyloid beta antibody"},
    {"molecule": "lebrikizumab", "indication": "Adolescent atopic dermatitis", "phase": "3", "therapeutic_area": "Immunology", "mechanism": "IL-13 antagonist"},
    {"molecule": "mirikizumab", "indication": "Crohn disease", "phase": "3", "therapeutic_area": "Immunology", "mechanism": "IL-23p19 antagonist"},
    {"molecule": "pirtobrutinib", "indication": "CLL/SLL (first-line and relapsed)", "phase": "3", "therapeutic_area": "Oncology", "mechanism": "Non-covalent BTK inhibitor"},
    {"molecule": "imlunestrant", "indication": "ER+/HER2- breast cancer", "phase": "3", "therapeutic_area": "Oncology", "mechanism": "Oral SERD"},
    {"molecule": "LY3857210", "indication": "Chronic pain", "phase": "2", "therapeutic_area": "Neuroscience", "mechanism": "P2X3 receptor antagonist"},
    {"molecule": "LY3537982", "indication": "KRAS G12C solid tumors", "phase": "2", "therapeutic_area": "Oncology", "mechanism": "KRAS G12C inhibitor"},
    {"molecule": "LY3849891", "indication": "Atopic dermatitis", "phase": "1", "therapeutic_area": "Immunology", "mechanism": "OX40 ligand antagonist"},
    {"molecule": "LY3971176", "indication": "Solid tumors (IO combination)", "phase": "1", "therapeutic_area": "Oncology", "mechanism": "CD73 inhibitor"},
]


# ---------------------------------------------------------------------------
# Curated Dear HCP letters / safety communications
# ---------------------------------------------------------------------------

LILLY_MEDICAL_LETTERS = [
    {"date": "2024-09-12", "product": "Mounjaro", "topic": "Updated prescribing information for pancreatitis risk communication", "type": "Safety update"},
    {"date": "2024-06-15", "product": "Zepbound", "topic": "Launch communication to HCPs on chronic weight management indication", "type": "Launch letter"},
    {"date": "2024-03-20", "product": "Kisunla", "topic": "Pre-approval information for donanemab ARIA monitoring", "type": "Pre-launch letter"},
    {"date": "2023-11-08", "product": "Verzenio", "topic": "Updated venous thromboembolism (VTE) warnings in prescribing information", "type": "Safety update"},
    {"date": "2023-08-22", "product": "Olumiant", "topic": "Updated boxed warning for serious infections, malignancy, thrombosis (class-wide JAK inhibitor update)", "type": "Safety update"},
    {"date": "2023-05-10", "product": "Trulicity", "topic": "Updated labeling for medullary thyroid carcinoma and MEN 2 risk", "type": "Safety update"},
    {"date": "2023-01-15", "product": "Retevmo", "topic": "Updated hepatotoxicity warnings and monitoring recommendations", "type": "Safety update"},
    {"date": "2022-09-30", "product": "Cyramza", "topic": "Reminder on hemorrhage risk and wound healing complications", "type": "Safety reminder"},
    {"date": "2022-06-20", "product": "Taltz", "topic": "Updated inflammatory bowel disease warnings", "type": "Safety update"},
    {"date": "2022-03-15", "product": "Emgality", "topic": "Post-marketing hypersensitivity reactions including anaphylaxis", "type": "Safety update"},
]


# ---------------------------------------------------------------------------
# openFDA label fetching (enrichment)
# ---------------------------------------------------------------------------

def _get_openfda_label(drug_name: str) -> dict | None:
    """Fetch the first matching openFDA drug label for a drug name."""
    encoded = _quote(drug_name)
    for field in ("openfda.generic_name", "openfda.brand_name"):
        url = f"{OPENFDA_LABEL_URL}?search={field}:{encoded}&limit=1"
        try:
            data = _fetch(url)
            results = data.get("results", [])
            if results:
                return results[0]
        except RuntimeError:
            continue
    return None


def _first_label_section(label: dict, field: str, max_len: int = 2000) -> str | None:
    """Extract the first entry from a label section (openFDA returns lists)."""
    val = label.get(field)
    if isinstance(val, list) and val:
        text = val[0]
        return text[:max_len] + "..." if len(text) > max_len else text
    return val


def _resolve_product(args: dict) -> str:
    """Resolve product name from any known parameter alias."""
    return (args.get("product") or args.get("drug_name") or args.get("drug")
            or args.get("name") or args.get("brand_name") or "").strip()


def _find_product(name: str) -> dict | None:
    """Look up a Lilly product by brand or generic name (case-insensitive)."""
    key = name.lower().strip()
    if key in _PRODUCT_INDEX:
        return _PRODUCT_INDEX[key]
    # Partial match fallback
    for prod_key, prod in _PRODUCT_INDEX.items():
        if key in prod_key or prod_key in key:
            return prod
    return None


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def get_products(args: dict) -> dict:
    """
    Tool: get-products

    Return Eli Lilly product portfolio. Optionally filter by therapeutic area.
    """
    area_filter = ensure_str(args.get("therapeutic_area") or "").strip().lower()

    products = LILLY_PRODUCTS
    if area_filter:
        products = [
            p for p in products
            if area_filter in p["therapeutic_area"].lower()
        ]

    return {
        "status": "ok",
        "therapeutic_area_filter": area_filter or None,
        "product_count": len(products),
        "products": [
            {
                "brand_name": p["brand_name"],
                "generic_name": p["generic_name"],
                "therapeutic_area": p["therapeutic_area"],
                "indication": p["indication"],
                "mechanism": p["mechanism"],
                "approval_year": p["approval_year"],
                "prescribing_info_url": p["prescribing_info_url"],
            }
            for p in products
        ],
        "sources": ["Eli Lilly product catalog (curated from lilly.com)"],
    }


def get_pipeline(args: dict) -> dict:
    """
    Tool: get-pipeline

    Return Eli Lilly development pipeline. Optionally filter by phase or
    therapeutic area.
    """
    phase_filter = ensure_str(args.get("phase") or "").strip()
    area_filter = ensure_str(args.get("therapeutic_area") or "").strip().lower()

    candidates = LILLY_PIPELINE
    if phase_filter:
        candidates = [c for c in candidates if c["phase"] == phase_filter]
    if area_filter:
        candidates = [
            c for c in candidates
            if area_filter in c["therapeutic_area"].lower()
        ]

    return {
        "status": "ok",
        "phase_filter": phase_filter or None,
        "therapeutic_area_filter": area_filter or None,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "sources": ["Eli Lilly pipeline (curated from lilly.com/pipeline and investor disclosures)"],
    }


def get_safety_info(args: dict) -> dict:
    """
    Tool: get-safety-info

    Get safety information for a specific Eli Lilly product. Combines curated
    Lilly product data with live openFDA drug label enrichment for boxed
    warnings, adverse reactions, contraindications, and warnings/precautions.
    """
    product_name = _resolve_product(args)
    if not product_name:
        return {"status": "error", "message": "product is required (e.g., mounjaro, trulicity, verzenio)"}

    product = _find_product(product_name)
    if not product:
        return {
            "status": "not_found",
            "message": f"'{product_name}' not found in Lilly product catalog. Use get-products to see available products.",
            "product": product_name,
        }

    result = {
        "status": "ok",
        "product": product_name,
        "brand_name": product["brand_name"],
        "generic_name": product["generic_name"],
        "therapeutic_area": product["therapeutic_area"],
        "indication": product["indication"],
        "mechanism": product["mechanism"],
        "lilly_resources": {
            "prescribing_info": product["prescribing_info_url"],
            "medication_guide": product.get("medication_guide_url"),
        },
    }

    # Enrich with live openFDA label data
    label = _get_openfda_label(product["generic_name"])
    sources = ["Eli Lilly product catalog"]

    if label:
        sources.append("openFDA drug label API")

        boxed = _first_label_section(label, "boxed_warning")
        result["has_boxed_warning"] = boxed is not None and len(str(boxed).strip()) > 0
        result["boxed_warning"] = boxed
        result["adverse_reactions"] = _first_label_section(label, "adverse_reactions")
        result["warnings_and_precautions"] = _first_label_section(label, "warnings_and_cautions") or _first_label_section(label, "warnings")
        result["contraindications"] = _first_label_section(label, "contraindications")

        # REMS check
        rems = _first_label_section(label, "risk_evaluation_and_mitigation_strategy")
        if rems:
            result["rems"] = rems
    else:
        result["has_boxed_warning"] = None
        result["note"] = "openFDA label lookup returned no results; safety sections unavailable. See prescribing info URL for full label."

    result["sources"] = sources
    return result


def get_medical_letters(args: dict) -> dict:
    """
    Tool: get-medical-letters

    Return Dear Healthcare Provider letters and safety communications from
    Eli Lilly. Optionally filter by product name.
    """
    product_filter = _resolve_product(args).lower()

    letters = LILLY_MEDICAL_LETTERS
    if product_filter:
        letters = [
            l for l in letters
            if product_filter in l["product"].lower()
        ]

    return {
        "status": "ok",
        "product_filter": product_filter or None,
        "letter_count": len(letters),
        "letters": letters,
        "sources": ["Eli Lilly DHCP letters (curated from lilly.com/medical-information)"],
    }


def get_patient_resources(args: dict) -> dict:
    """
    Tool: get-patient-resources

    Return patient medication guides and educational resources for a Lilly product.
    Enriches curated URLs with openFDA label patient counseling information.
    """
    product_name = _resolve_product(args)
    if not product_name:
        return {"status": "error", "message": "product is required (e.g., mounjaro, trulicity, verzenio)"}

    product = _find_product(product_name)
    if not product:
        return {
            "status": "not_found",
            "message": f"'{product_name}' not found in Lilly product catalog. Use get-products to see available products.",
            "product": product_name,
        }

    resources = []
    sources = ["Eli Lilly product catalog"]

    # Curated Lilly resources
    if product.get("prescribing_info_url"):
        resources.append({
            "title": f"{product['brand_name']} Full Prescribing Information",
            "type": "prescribing_information",
            "url": product["prescribing_info_url"],
        })
    if product.get("medication_guide_url"):
        resources.append({
            "title": f"{product['brand_name']} Medication Guide",
            "type": "medication_guide",
            "url": product["medication_guide_url"],
        })

    # Lilly branded patient site (standard pattern)
    brand_lower = product["brand_name"].lower()
    resources.append({
        "title": f"{product['brand_name']} Patient Website",
        "type": "patient_website",
        "url": f"https://www.{brand_lower}.com/",
    })

    # Enrich with openFDA patient counseling information
    label = _get_openfda_label(product["generic_name"])
    if label:
        sources.append("openFDA drug label API")
        pci = _first_label_section(label, "patient_medication_information")
        if not pci:
            pci = _first_label_section(label, "information_for_patients")
        if pci:
            resources.append({
                "title": "Patient Counseling Information (from FDA label)",
                "type": "patient_counseling_information",
                "text": pci,
            })

    return {
        "status": "ok",
        "product": product_name,
        "brand_name": product["brand_name"],
        "generic_name": product["generic_name"],
        "resources": resources,
        "sources": sources,
    }


TOOL_DISPATCH = {
    "get-products": get_products,
    "get-pipeline": get_pipeline,
    "get-safety-info": get_safety_info,
    "get-medical-letters": get_medical_letters,
    "get-patient-resources": get_patient_resources,
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

    tool_name = ensure_str(payload.get("tool", "")).strip()
    args = payload.get("arguments", payload.get("args", {}))

    if tool_name not in TOOL_DISPATCH:
        known = list(TOOL_DISPATCH.keys())
        result = {
            "status": "error",
            "message": f"Unknown tool '{tool_name}'. Known tools: {known}",
        }
        print(json.dumps(result))
        sys.exit(1)

    handler = TOOL_DISPATCH[tool_name]
    try:
        result = handler(args)
    except RuntimeError as exc:
        result = {"status": "error", "error": True, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        result = {
            "status": "error",
            "error": True,
            "message": f"Unexpected error in '{tool_name}': {type(exc).__name__}: {exc}",
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
