#!/usr/bin/env python3
"""
Pfizer Safety Data Proxy — curated Pfizer product data enriched with live FDA APIs.

Usage:
    echo '{"tool": "get-products", "args": {"therapeutic_area": "oncology"}}' | python3 pfizer_proxy.py
    echo '{"tool": "get-safety-info", "args": {"product_name": "Eliquis"}}' | python3 pfizer_proxy.py

Data sources:
  - Curated Pfizer product portfolio and pipeline (static reference)
  - openFDA drug label API: safety sections (adverse reactions, boxed warnings, contraindications)
  - openFDA FAERS: post-marketing adverse event frequency
  - DailyMed: medication guide URLs and setIds

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
OPENFDA_EVENT_URL = "https://api.fda.gov/drug/event.json"
DAILYMED_BASE = "https://dailymed.nlm.nih.gov/dailymed/services"
REQUEST_TIMEOUT_SECONDS = 20
_RETRY_CODES = {429, 503}
_MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Curated Pfizer product portfolio
# ---------------------------------------------------------------------------

PFIZER_PRODUCTS = [
    {
        "brand_name": "Comirnaty",
        "generic_name": "tozinameran / COVID-19 mRNA vaccine",
        "therapeutic_area": "vaccines",
        "indication": "Prevention of COVID-19",
        "approval_year": 2021,
        "co_marketer": "BioNTech",
    },
    {
        "brand_name": "Paxlovid",
        "generic_name": "nirmatrelvir/ritonavir",
        "therapeutic_area": "anti-infectives",
        "indication": "Treatment of mild-to-moderate COVID-19 in adults at high risk",
        "approval_year": 2023,
        "co_marketer": None,
    },
    {
        "brand_name": "Eliquis",
        "generic_name": "apixaban",
        "therapeutic_area": "cardiology",
        "indication": "Prevention of stroke and systemic embolism in nonvalvular atrial fibrillation; treatment/prevention of DVT and PE",
        "approval_year": 2012,
        "co_marketer": "Bristol-Myers Squibb",
    },
    {
        "brand_name": "Ibrance",
        "generic_name": "palbociclib",
        "therapeutic_area": "oncology",
        "indication": "HR+/HER2- metastatic breast cancer in combination with endocrine therapy",
        "approval_year": 2015,
        "co_marketer": None,
    },
    {
        "brand_name": "Xeljanz",
        "generic_name": "tofacitinib",
        "therapeutic_area": "inflammation",
        "indication": "Rheumatoid arthritis, psoriatic arthritis, ulcerative colitis, ankylosing spondylitis",
        "approval_year": 2012,
        "co_marketer": None,
    },
    {
        "brand_name": "Prevnar 20",
        "generic_name": "pneumococcal 20-valent conjugate vaccine",
        "therapeutic_area": "vaccines",
        "indication": "Prevention of invasive pneumococcal disease and pneumococcal pneumonia in adults",
        "approval_year": 2021,
        "co_marketer": None,
    },
    {
        "brand_name": "Vyndaqel",
        "generic_name": "tafamidis meglumine",
        "therapeutic_area": "cardiology",
        "indication": "Transthyretin amyloid cardiomyopathy (ATTR-CM)",
        "approval_year": 2019,
        "co_marketer": None,
    },
    {
        "brand_name": "Vyndamax",
        "generic_name": "tafamidis",
        "therapeutic_area": "cardiology",
        "indication": "Transthyretin amyloid cardiomyopathy (ATTR-CM)",
        "approval_year": 2019,
        "co_marketer": None,
    },
    {
        "brand_name": "Xtandi",
        "generic_name": "enzalutamide",
        "therapeutic_area": "oncology",
        "indication": "Metastatic and non-metastatic castration-resistant prostate cancer",
        "approval_year": 2012,
        "co_marketer": "Astellas",
    },
    {
        "brand_name": "Lorbrena",
        "generic_name": "lorlatinib",
        "therapeutic_area": "oncology",
        "indication": "ALK-positive metastatic non-small cell lung cancer",
        "approval_year": 2018,
        "co_marketer": None,
    },
    {
        "brand_name": "Bavencio",
        "generic_name": "avelumab",
        "therapeutic_area": "oncology",
        "indication": "Merkel cell carcinoma, urothelial carcinoma, renal cell carcinoma",
        "approval_year": 2017,
        "co_marketer": "Merck KGaA (EMD Serono)",
    },
    {
        "brand_name": "Nurtec ODT",
        "generic_name": "rimegepant",
        "therapeutic_area": "neuroscience",
        "indication": "Acute treatment and prevention of episodic migraine",
        "approval_year": 2020,
        "co_marketer": None,
    },
    {
        "brand_name": "Oxbryta",
        "generic_name": "voxelotor",
        "therapeutic_area": "rare-disease",
        "indication": "Sickle cell disease in adults and pediatric patients",
        "approval_year": 2019,
        "co_marketer": None,
    },
    {
        "brand_name": "Zavzpret",
        "generic_name": "zavegepant",
        "therapeutic_area": "neuroscience",
        "indication": "Acute treatment of migraine with or without aura",
        "approval_year": 2023,
        "co_marketer": None,
    },
    {
        "brand_name": "Bosulif",
        "generic_name": "bosutinib",
        "therapeutic_area": "oncology",
        "indication": "Philadelphia chromosome-positive chronic myelogenous leukemia",
        "approval_year": 2012,
        "co_marketer": None,
    },
    {
        "brand_name": "Inlyta",
        "generic_name": "axitinib",
        "therapeutic_area": "oncology",
        "indication": "Advanced renal cell carcinoma after failure of one prior systemic therapy",
        "approval_year": 2012,
        "co_marketer": None,
    },
    {
        "brand_name": "Sutent",
        "generic_name": "sunitinib",
        "therapeutic_area": "oncology",
        "indication": "GIST, advanced renal cell carcinoma, pancreatic neuroendocrine tumors",
        "approval_year": 2006,
        "co_marketer": None,
    },
    {
        "brand_name": "Vizimpro",
        "generic_name": "dacomitinib",
        "therapeutic_area": "oncology",
        "indication": "First-line treatment of metastatic NSCLC with EGFR exon 19 deletion or exon 21 L858R substitution",
        "approval_year": 2018,
        "co_marketer": None,
    },
    {
        "brand_name": "Litfulo",
        "generic_name": "ritlecitinib",
        "therapeutic_area": "inflammation",
        "indication": "Severe alopecia areata in adults and adolescents",
        "approval_year": 2023,
        "co_marketer": None,
    },
    {
        "brand_name": "Abrysvo",
        "generic_name": "respiratory syncytial virus vaccine",
        "therapeutic_area": "vaccines",
        "indication": "Prevention of RSV lower respiratory tract disease in infants (maternal immunization) and adults 60+",
        "approval_year": 2023,
        "co_marketer": None,
    },
    {
        "brand_name": "Talzenna",
        "generic_name": "talazoparib",
        "therapeutic_area": "oncology",
        "indication": "HER2-negative locally advanced or metastatic breast cancer with germline BRCA mutation",
        "approval_year": 2018,
        "co_marketer": None,
    },
    {
        "brand_name": "Braftovi",
        "generic_name": "encorafenib",
        "therapeutic_area": "oncology",
        "indication": "BRAF V600E-mutant metastatic colorectal cancer (with cetuximab); melanoma",
        "approval_year": 2018,
        "co_marketer": None,
    },
    {
        "brand_name": "Padcev",
        "generic_name": "enfortumab vedotin",
        "therapeutic_area": "oncology",
        "indication": "Locally advanced or metastatic urothelial cancer",
        "approval_year": 2019,
        "co_marketer": "Astellas",
    },
    {
        "brand_name": "Adcetris",
        "generic_name": "brentuximab vedotin",
        "therapeutic_area": "oncology",
        "indication": "Classical Hodgkin lymphoma, systemic anaplastic large cell lymphoma",
        "approval_year": 2011,
        "co_marketer": "Seagen",
    },
]


# ---------------------------------------------------------------------------
# Curated Pfizer pipeline (representative late-stage candidates)
# ---------------------------------------------------------------------------

PFIZER_PIPELINE = [
    {
        "candidate_name": "Danuglipron",
        "generic_name": "danuglipron",
        "phase": "Phase 2",
        "mechanism": "GLP-1 receptor agonist (oral)",
        "therapeutic_area": "metabolism",
        "indication": "Obesity and type 2 diabetes",
    },
    {
        "candidate_name": "PF-07817883",
        "generic_name": None,
        "phase": "Phase 2",
        "mechanism": "GLP-1 receptor agonist (oral, once-daily)",
        "therapeutic_area": "metabolism",
        "indication": "Obesity",
    },
    {
        "candidate_name": "Elranatamab (Elrexfio)",
        "generic_name": "elranatamab",
        "phase": "Approved",
        "mechanism": "BCMA x CD3 bispecific antibody",
        "therapeutic_area": "oncology",
        "indication": "Relapsed or refractory multiple myeloma",
    },
    {
        "candidate_name": "Sasanlimab",
        "generic_name": "sasanlimab",
        "phase": "Phase 3",
        "mechanism": "Anti-PD-1 (subcutaneous)",
        "therapeutic_area": "oncology",
        "indication": "Non-muscle invasive bladder cancer; various solid tumors",
    },
    {
        "candidate_name": "Sigvotatug vedotin",
        "generic_name": "sigvotatug vedotin",
        "phase": "Phase 3",
        "mechanism": "TROP2 ADC",
        "therapeutic_area": "oncology",
        "indication": "HR+/HER2- metastatic breast cancer, NSCLC",
    },
    {
        "candidate_name": "Atirmociclib",
        "generic_name": "atirmociclib",
        "phase": "Phase 3",
        "mechanism": "CDK4 inhibitor (selective)",
        "therapeutic_area": "oncology",
        "indication": "HR+/HER2- metastatic breast cancer",
    },
    {
        "candidate_name": "Marstacimab",
        "generic_name": "marstacimab",
        "phase": "Phase 3",
        "mechanism": "Anti-TFPI antibody",
        "therapeutic_area": "rare-disease",
        "indication": "Hemophilia A and B (subcutaneous prophylaxis)",
    },
    {
        "candidate_name": "Fidanacogene elaparvovec (Beqvez)",
        "generic_name": "fidanacogene elaparvovec",
        "phase": "Approved",
        "mechanism": "AAV gene therapy (FIX)",
        "therapeutic_area": "rare-disease",
        "indication": "Hemophilia B",
    },
    {
        "candidate_name": "Giroctocogene fitelparvovec",
        "generic_name": "giroctocogene fitelparvovec",
        "phase": "Filed",
        "mechanism": "AAV gene therapy (FVIII)",
        "therapeutic_area": "rare-disease",
        "indication": "Hemophilia A",
    },
    {
        "candidate_name": "Vepdegestrant",
        "generic_name": "vepdegestrant",
        "phase": "Phase 3",
        "mechanism": "Oral PROTAC estrogen receptor degrader",
        "therapeutic_area": "oncology",
        "indication": "ER+/HER2- metastatic breast cancer",
    },
    {
        "candidate_name": "Ritlenvimab",
        "generic_name": "ritlenvimab",
        "phase": "Phase 3",
        "mechanism": "Anti-RSV monoclonal antibody",
        "therapeutic_area": "anti-infectives",
        "indication": "Prevention of RSV in infants",
    },
    {
        "candidate_name": "Lotilaner",
        "generic_name": "lotilaner",
        "phase": "Filed",
        "mechanism": "GABA-gated chloride channel inhibitor (ophthalmic)",
        "therapeutic_area": "ophthalmology",
        "indication": "Demodex blepharitis",
    },
]


# ---------------------------------------------------------------------------
# Curated Dear HCP letters and safety communications
# ---------------------------------------------------------------------------

PFIZER_MEDICAL_LETTERS = [
    {
        "product": "Xeljanz",
        "generic_name": "tofacitinib",
        "date": "2021-09-01",
        "title": "Boxed Warning Update: Increased risks of serious heart-related events, cancer, blood clots, and death",
        "summary": "FDA required updated Boxed Warning for Xeljanz/Xeljanz XR based on ORAL Surveillance trial results showing increased risks of MACE, malignancies, thrombosis, and all-cause mortality vs. TNF inhibitors in RA patients with CV risk factors.",
        "letter_type": "DHCP",
    },
    {
        "product": "Xeljanz",
        "generic_name": "tofacitinib",
        "date": "2019-07-26",
        "title": "Dose Limitation: 10 mg twice daily dose restriction for UC patients",
        "summary": "FDA safety review identified increased risk of pulmonary embolism and overall mortality with 10 mg twice daily dose. Interim safety measure limiting use of higher dose in UC.",
        "letter_type": "DHCP",
    },
    {
        "product": "Comirnaty",
        "generic_name": "COVID-19 mRNA vaccine",
        "date": "2021-06-25",
        "title": "Myocarditis and Pericarditis Warning Update",
        "summary": "Updated EUA Fact Sheets to include warning of myocarditis and pericarditis, primarily in male adolescents and young adults after the second dose.",
        "letter_type": "Safety Communication",
    },
    {
        "product": "Paxlovid",
        "generic_name": "nirmatrelvir/ritonavir",
        "date": "2023-05-25",
        "title": "Drug Interaction Reminder: CYP3A-dependent medications",
        "summary": "Reminder to healthcare professionals about significant drug-drug interactions with ritonavir component. Contraindicated with drugs highly dependent on CYP3A for clearance where elevated concentrations are associated with serious and/or life-threatening reactions.",
        "letter_type": "DHCP",
    },
    {
        "product": "Oxbryta",
        "generic_name": "voxelotor",
        "date": "2024-09-25",
        "title": "Voluntary Worldwide Withdrawal",
        "summary": "Pfizer announced voluntary worldwide withdrawal of Oxbryta following post-marketing data review showing fatal and non-fatal vaso-occlusive crises. FDA concurred that benefits no longer outweigh risks.",
        "letter_type": "Withdrawal Notice",
    },
    {
        "product": "Eliquis",
        "generic_name": "apixaban",
        "date": "2014-08-22",
        "title": "Updated Dosing Recommendations for Specific Patient Populations",
        "summary": "Updated labeling with dose reduction criteria for patients with at least 2 of: age >= 80, body weight <= 60 kg, serum creatinine >= 1.5 mg/dL. Reinforced risk of spinal/epidural hematoma with neuraxial anesthesia.",
        "letter_type": "DHCP",
    },
    {
        "product": "Bavencio",
        "generic_name": "avelumab",
        "date": "2019-05-14",
        "title": "Immune-Mediated Adverse Reactions Management Guide",
        "summary": "Guidance on monitoring and management of immune-mediated adverse reactions including pneumonitis, hepatitis, colitis, endocrinopathies, nephritis, and dermatologic reactions. Includes corticosteroid dosing algorithms.",
        "letter_type": "DHCP",
    },
    {
        "product": "Ibrance",
        "generic_name": "palbociclib",
        "date": "2019-09-13",
        "title": "Updated Warnings: Severe and Life-Threatening Interstitial Lung Disease/Pneumonitis",
        "summary": "Addition of ILD/pneumonitis to Warnings and Precautions section based on post-marketing reports. Recommendations for monitoring and dose modification.",
        "letter_type": "Safety Communication",
    },
    {
        "product": "Sutent",
        "generic_name": "sunitinib",
        "date": "2018-06-15",
        "title": "Updated Warning: Necrotizing Fasciitis",
        "summary": "Reports of necrotizing fasciitis, including fatal cases, added to post-marketing adverse reactions. Advise patients to seek immediate medical attention for signs of soft tissue infection.",
        "letter_type": "Safety Communication",
    },
    {
        "product": "Prevnar 20",
        "generic_name": "pneumococcal 20-valent conjugate vaccine",
        "date": "2023-04-19",
        "title": "Expanded Age Indication: Adults 18 years and older",
        "summary": "FDA approved expanded age indication from 65+ to all adults 18 years and older for prevention of invasive disease and pneumonia caused by Streptococcus pneumoniae serotypes in the vaccine.",
        "letter_type": "Safety Communication",
    },
]


# ---------------------------------------------------------------------------
# HTTP helpers (matching station proxy pattern)
# ---------------------------------------------------------------------------

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


def _resolve_product(args: dict) -> str:
    """Resolve product name from any known alias."""
    return (args.get("product_name") or args.get("drug_name") or args.get("drug")
            or args.get("name") or args.get("brand_name") or args.get("product")
            or args.get("query") or "").strip()


def _match_product(query: str) -> dict | None:
    """Find the best matching Pfizer product by brand or generic name."""
    q = query.lower()
    for p in PFIZER_PRODUCTS:
        if q == p["brand_name"].lower() or q == p["generic_name"].lower():
            return p
    # Partial match
    for p in PFIZER_PRODUCTS:
        if q in p["brand_name"].lower() or q in p["generic_name"].lower():
            return p
    return None


def _get_openfda_label(drug_name: str) -> dict | None:
    """Fetch the first matching openFDA drug label."""
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
    """Extract the first entry from a label section."""
    val = label.get(field)
    if isinstance(val, list) and val:
        text = val[0]
        return text[:max_len] + "..." if len(text) > max_len else text
    return val


def _get_dailymed_url(drug_name: str) -> str | None:
    """Resolve drug name to a DailyMed medication guide URL."""
    encoded = _quote(drug_name)
    url = f"{DAILYMED_BASE}/v2/spls.json?drug_name={encoded}&pagesize=1"
    try:
        data = _fetch(url)
        results = data.get("data", [])
        if results:
            setid = results[0].get("setid")
            if setid:
                return f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"
    except RuntimeError:
        pass
    return None


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def get_products(args: dict) -> dict:
    """
    Tool: get-products

    Return Pfizer product portfolio, optionally filtered by therapeutic area
    or search query. Curated reference data covering key marketed products.
    """
    therapeutic_area = ensure_str(args.get("therapeutic_area") or "").strip().lower()
    query = (args.get("query") or args.get("search_query") or "").strip().lower()

    products = PFIZER_PRODUCTS

    if therapeutic_area:
        products = [p for p in products if therapeutic_area in p["therapeutic_area"].lower()]

    if query:
        products = [
            p for p in products
            if (query in p["brand_name"].lower()
                or query in p["generic_name"].lower()
                or query in p["indication"].lower()
                or query in p["therapeutic_area"].lower())
        ]

    return {
        "status": "ok",
        "total_products": len(products),
        "filter": {
            "therapeutic_area": therapeutic_area or None,
            "query": query or None,
        },
        "products": products,
        "sources": ["Pfizer product portfolio (curated reference, updated Q1 2026)"],
    }


def get_pipeline(args: dict) -> dict:
    """
    Tool: get-pipeline

    Return Pfizer development pipeline candidates, optionally filtered by
    phase or therapeutic area. Curated from public pipeline disclosures.
    """
    phase_filter = ensure_str(args.get("phase") or "").strip().lower()
    ta_filter = ensure_str(args.get("therapeutic_area") or "").strip().lower()

    pipeline = PFIZER_PIPELINE

    if phase_filter:
        pipeline = [p for p in pipeline if phase_filter in p["phase"].lower()]

    if ta_filter:
        pipeline = [p for p in pipeline if ta_filter in p["therapeutic_area"].lower()]

    return {
        "status": "ok",
        "total_candidates": len(pipeline),
        "filter": {
            "phase": phase_filter or None,
            "therapeutic_area": ta_filter or None,
        },
        "pipeline": pipeline,
        "sources": ["Pfizer pipeline (curated from public disclosures, updated Q1 2026)"],
    }


def get_safety_info(args: dict) -> dict:
    """
    Tool: get-safety-info

    Get comprehensive safety information for a Pfizer product by combining
    curated portfolio data with live FDA label sections and FAERS signal data.
    """
    product_name = _resolve_product(args)
    if not product_name:
        return {"status": "error", "message": "product_name is required"}

    # Match to Pfizer portfolio
    product = _match_product(product_name)
    if not product:
        return {
            "status": "not_found",
            "message": f"'{product_name}' not found in Pfizer product portfolio. Use get-products to list available products.",
            "available_products": [p["brand_name"] for p in PFIZER_PRODUCTS],
        }

    # Use generic name for FDA lookups (more reliable than brand)
    lookup_name = product["generic_name"]
    brand = product["brand_name"]

    # Source 1: openFDA drug label safety sections
    label = _get_openfda_label(lookup_name)
    if not label:
        # Fallback to brand name
        label = _get_openfda_label(brand)

    boxed_warning = None
    adverse_reactions = None
    contraindications = None
    warnings = None

    if label:
        boxed_warning = _first_label_section(label, "boxed_warning")
        adverse_reactions = _first_label_section(label, "adverse_reactions")
        contraindications = _first_label_section(label, "contraindications")
        warnings = _first_label_section(label, "warnings_and_precautions") or _first_label_section(label, "warnings")

    # Source 2: FAERS top adverse events
    faers_reactions = []
    encoded = _quote(lookup_name.split("/")[0].strip())  # handle "nirmatrelvir/ritonavir"
    url = f"{OPENFDA_EVENT_URL}?search=patient.drug.openfda.generic_name:\"{encoded}\"&count=patient.reaction.reactionmeddrapt.exact"
    try:
        data = _fetch(url)
        for item in data.get("results", [])[:20]:
            faers_reactions.append({
                "reaction": item.get("term"),
                "report_count": item.get("count"),
            })
    except RuntimeError:
        pass

    # Source 3: DailyMed medication guide URL
    med_guide_url = _get_dailymed_url(lookup_name) or _get_dailymed_url(brand)

    sources = ["Pfizer product portfolio (curated)"]
    if label:
        sources.append("openFDA drug label API")
    if faers_reactions:
        sources.append("openFDA FAERS")
    if med_guide_url:
        sources.append("DailyMed")

    return {
        "status": "ok",
        "brand_name": brand,
        "generic_name": product["generic_name"],
        "therapeutic_area": product["therapeutic_area"],
        "indication": product["indication"],
        "co_marketer": product["co_marketer"],
        "has_boxed_warning": boxed_warning is not None and len(str(boxed_warning).strip()) > 0,
        "boxed_warning": boxed_warning,
        "adverse_reactions": adverse_reactions,
        "contraindications": contraindications,
        "warnings_and_precautions": warnings,
        "faers_top_reactions": faers_reactions,
        "medication_guide_url": med_guide_url,
        "sources": sources,
    }


def get_medical_letters(args: dict) -> dict:
    """
    Tool: get-medical-letters

    Return Dear HCP letters and safety communications from Pfizer. Optionally
    filter by product name. Curated from FDA safety archives and Pfizer disclosures.
    """
    product_name = (args.get("product_name") or args.get("drug_name") or args.get("drug")
                    or args.get("query") or "").strip().lower()
    limit = get_int_param(args, "limit", 10)
    limit = max(1, min(limit, 50))

    letters = PFIZER_MEDICAL_LETTERS

    if product_name:
        letters = [
            l for l in letters
            if (product_name in l["product"].lower()
                or product_name in l["generic_name"].lower())
        ]

    letters = letters[:limit]

    return {
        "status": "ok",
        "total_letters": len(letters),
        "filter": {"product_name": product_name or None},
        "letters": letters,
        "sources": ["Pfizer safety communications (curated from FDA archives and Pfizer disclosures)"],
    }


def get_patient_resources(args: dict) -> dict:
    """
    Tool: get-patient-resources

    Get patient-facing resources for a Pfizer product: medication guide URL,
    patient information from FDA label, indications summary, and links to
    Pfizer patient support programs.
    """
    product_name = _resolve_product(args)
    if not product_name:
        return {"status": "error", "message": "product_name is required"}

    product = _match_product(product_name)
    if not product:
        return {
            "status": "not_found",
            "message": f"'{product_name}' not found in Pfizer product portfolio. Use get-products to list available products.",
            "available_products": [p["brand_name"] for p in PFIZER_PRODUCTS],
        }

    lookup_name = product["generic_name"]
    brand = product["brand_name"]

    # FDA label patient-facing sections
    label = _get_openfda_label(lookup_name)
    if not label:
        label = _get_openfda_label(brand)

    patient_info = None
    indications = None
    dosage = None

    if label:
        patient_info = (
            _first_label_section(label, "patient_medication_information")
            or _first_label_section(label, "information_for_patients")
        )
        indications = _first_label_section(label, "indications_and_usage", max_len=1000)
        dosage = _first_label_section(label, "dosage_and_administration", max_len=1000)

    # DailyMed medication guide
    med_guide_url = _get_dailymed_url(lookup_name) or _get_dailymed_url(brand)

    # Pfizer patient support resources (constructed URLs)
    brand_slug = brand.lower().replace(" ", "-").replace("/", "-")
    pfizer_resources = [
        {
            "title": f"{brand} Official Site",
            "url": f"https://www.{brand_slug}.com",
            "note": "Product website (may not exist for all products)",
        },
        {
            "title": "Pfizer Patient Assistance (Pfizer RxPathways)",
            "url": "https://www.pfizerrxpathways.com",
            "note": "Financial assistance and insurance support programs",
        },
        {
            "title": "Pfizer Medical Information",
            "url": "https://www.pfizermedicalinformation.com",
            "note": "Healthcare professional and patient medical information portal",
        },
    ]

    sources = ["Pfizer product portfolio (curated)"]
    if label:
        sources.append("openFDA drug label API")
    if med_guide_url:
        sources.append("DailyMed")

    return {
        "status": "ok",
        "brand_name": brand,
        "generic_name": product["generic_name"],
        "therapeutic_area": product["therapeutic_area"],
        "indication": product["indication"],
        "medication_guide_url": med_guide_url,
        "patient_info": patient_info,
        "indications_summary": indications,
        "dosage_summary": dosage,
        "pfizer_resources": pfizer_resources,
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
