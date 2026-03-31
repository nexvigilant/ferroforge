#!/usr/bin/env python3
"""
Novartis Proxy — curated Novartis product portfolio, pipeline, and safety data.

Usage:
    echo '{"tool": "get-products", "args": {}}' | python3 novartis_proxy.py
    echo '{"tool": "get-safety-info", "args": {"product_name": "Entresto"}}' | python3 novartis_proxy.py

Data sources:
  - Static curated reference: Novartis product portfolio and pipeline
  - openFDA drug label API: adverse reactions, boxed warnings, clinical sections
  - openFDA FAERS API: post-marketing adverse event frequency
  - Novartis.com URLs: medication guides, patient resources

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


def _resolve_product(args: dict) -> str:
    """Resolve product name from any known alias."""
    return (args.get("product_name") or args.get("drug_name") or args.get("drug")
            or args.get("name") or args.get("brand_name")
            or args.get("query") or "").strip()


def _get_openfda_label(drug_name: str) -> dict | None:
    """Fetch the first matching openFDA drug label."""
    encoded = _quote(drug_name)
    for field in ("openfda.brand_name", "openfda.generic_name"):
        url = f"{OPENFDA_LABEL_URL}?search={field}:{encoded}&limit=1"
        try:
            data = _fetch(url)
            results = data.get("results", [])
            if results:
                return results[0]
        except RuntimeError:
            continue
    return None


def _first_label_section(label: dict, field: str) -> str | None:
    """Extract the first entry from a label section."""
    val = label.get(field)
    if isinstance(val, list) and val:
        return val[0]
    return val


# ---------------------------------------------------------------------------
# Novartis product reference data (curated)
# ---------------------------------------------------------------------------

NOVARTIS_PRODUCTS = [
    {
        "brand_name": "Entresto",
        "generic_name": "sacubitril/valsartan",
        "therapeutic_area": "Cardiovascular",
        "indication": "Heart failure with reduced ejection fraction (HFrEF)",
        "novartis_url": "https://www.novartis.com/us-en/products/entresto",
        "patient_website": "https://www.entresto.com",
        "medication_guide_url": "https://www.novartis.com/us-en/sites/novartis_us/files/entresto_medication_guide.pdf",
        "support_program": {"name": "Entresto Patient Support", "url": "https://www.entresto.com/savings", "phone": "1-888-368-7378"},
    },
    {
        "brand_name": "Cosentyx",
        "generic_name": "secukinumab",
        "therapeutic_area": "Immunology",
        "indication": "Plaque psoriasis, psoriatic arthritis, ankylosing spondylitis",
        "novartis_url": "https://www.novartis.com/us-en/products/cosentyx",
        "patient_website": "https://www.cosentyx.com",
        "medication_guide_url": "https://www.novartis.com/us-en/sites/novartis_us/files/cosentyx_medication_guide.pdf",
        "support_program": {"name": "Cosentyx Connect", "url": "https://www.cosentyx.com/support", "phone": "1-844-267-3689"},
    },
    {
        "brand_name": "Kisqali",
        "generic_name": "ribociclib",
        "therapeutic_area": "Oncology",
        "indication": "HR+/HER2- advanced or metastatic breast cancer",
        "novartis_url": "https://www.novartis.com/us-en/products/kisqali",
        "patient_website": "https://www.kisqali.com",
        "medication_guide_url": "https://www.novartis.com/us-en/sites/novartis_us/files/kisqali_medication_guide.pdf",
        "support_program": {"name": "Kisqali Patient Support", "url": "https://www.kisqali.com/support", "phone": "1-800-282-7630"},
    },
    {
        "brand_name": "Kesimpta",
        "generic_name": "ofatumumab",
        "therapeutic_area": "Neuroscience",
        "indication": "Relapsing forms of multiple sclerosis (RMS)",
        "novartis_url": "https://www.novartis.com/us-en/products/kesimpta",
        "patient_website": "https://www.kesimpta.com",
        "medication_guide_url": "https://www.novartis.com/us-en/sites/novartis_us/files/kesimpta_medication_guide.pdf",
        "support_program": {"name": "Kesimpta Connect", "url": "https://www.kesimpta.com/support", "phone": "1-855-537-4678"},
    },
    {
        "brand_name": "Leqvio",
        "generic_name": "inclisiran",
        "therapeutic_area": "Cardiovascular",
        "indication": "Primary hyperlipidemia (heterozygous familial and non-familial) or mixed dyslipidemia",
        "novartis_url": "https://www.novartis.com/us-en/products/leqvio",
        "patient_website": "https://www.leqvio.com",
        "medication_guide_url": "https://www.novartis.com/us-en/sites/novartis_us/files/leqvio_medication_guide.pdf",
        "support_program": {"name": "Leqvio Patient Support", "url": "https://www.leqvio.com/savings", "phone": "1-833-537-8468"},
    },
    {
        "brand_name": "Pluvicto",
        "generic_name": "lutetium Lu 177 vipivotide tetraxetan",
        "therapeutic_area": "Oncology",
        "indication": "PSMA-positive metastatic castration-resistant prostate cancer (mCRPC)",
        "novartis_url": "https://www.novartis.com/us-en/products/pluvicto",
        "patient_website": "https://www.pluvicto.com",
        "medication_guide_url": "https://www.novartis.com/us-en/sites/novartis_us/files/pluvicto_prescribing_information.pdf",
        "support_program": {"name": "Pluvicto Patient Support", "url": "https://www.pluvicto.com/support", "phone": "1-833-758-8286"},
    },
    {
        "brand_name": "Scemblix",
        "generic_name": "asciminib",
        "therapeutic_area": "Oncology",
        "indication": "Philadelphia chromosome-positive chronic myeloid leukemia (Ph+ CML)",
        "novartis_url": "https://www.novartis.com/us-en/products/scemblix",
        "patient_website": "https://www.scemblix.com",
        "medication_guide_url": "https://www.novartis.com/us-en/sites/novartis_us/files/scemblix_prescribing_information.pdf",
        "support_program": {"name": "Novartis Patient Assistance", "url": "https://www.scemblix.com/support", "phone": "1-800-282-7630"},
    },
    {
        "brand_name": "Jakavi",
        "generic_name": "ruxolitinib",
        "therapeutic_area": "Hematology",
        "indication": "Myelofibrosis, polycythemia vera, graft-versus-host disease",
        "novartis_url": "https://www.novartis.com/us-en/products/jakafi",
        "patient_website": "https://www.jakafi.com",
        "medication_guide_url": "https://www.novartis.com/us-en/sites/novartis_us/files/jakafi_medication_guide.pdf",
        "support_program": {"name": "Jakafi Support", "url": "https://www.jakafi.com/support", "phone": "1-855-452-5234"},
    },
    {
        "brand_name": "Tasigna",
        "generic_name": "nilotinib",
        "therapeutic_area": "Oncology",
        "indication": "Philadelphia chromosome-positive chronic myeloid leukemia (Ph+ CML)",
        "novartis_url": "https://www.novartis.com/us-en/products/tasigna",
        "patient_website": "https://www.tasigna.com",
        "medication_guide_url": "https://www.novartis.com/us-en/sites/novartis_us/files/tasigna_medication_guide.pdf",
        "support_program": {"name": "Novartis Patient Assistance", "url": "https://www.tasigna.com/support", "phone": "1-800-282-7630"},
    },
    {
        "brand_name": "Zolgensma",
        "generic_name": "onasemnogene abeparvovec-xioi",
        "therapeutic_area": "Neuroscience",
        "indication": "Spinal muscular atrophy (SMA) in pediatric patients",
        "novartis_url": "https://www.novartis.com/us-en/products/zolgensma",
        "patient_website": "https://www.zolgensma.com",
        "medication_guide_url": "https://www.novartis.com/us-en/sites/novartis_us/files/zolgensma_prescribing_information.pdf",
        "support_program": {"name": "Zolgensma Patient Support", "url": "https://www.zolgensma.com/support", "phone": "1-855-965-4372"},
    },
    {
        "brand_name": "Aimovig",
        "generic_name": "erenumab-aooe",
        "therapeutic_area": "Neuroscience",
        "indication": "Preventive treatment of migraine in adults",
        "novartis_url": "https://www.novartis.com/us-en/products/aimovig",
        "patient_website": "https://www.aimovig.com",
        "medication_guide_url": "https://www.novartis.com/us-en/sites/novartis_us/files/aimovig_medication_guide.pdf",
        "support_program": {"name": "Aimovig Ally", "url": "https://www.aimovig.com/support", "phone": "1-833-246-6844"},
    },
    {
        "brand_name": "Promacta",
        "generic_name": "eltrombopag",
        "therapeutic_area": "Hematology",
        "indication": "Chronic immune thrombocytopenia (ITP), severe aplastic anemia",
        "novartis_url": "https://www.novartis.com/us-en/products/promacta",
        "patient_website": "https://www.promacta.com",
        "medication_guide_url": "https://www.novartis.com/us-en/sites/novartis_us/files/promacta_medication_guide.pdf",
        "support_program": {"name": "Promacta Patient Support", "url": "https://www.promacta.com/support", "phone": "1-800-282-7630"},
    },
    {
        "brand_name": "Fabhalta",
        "generic_name": "iptacopan",
        "therapeutic_area": "Hematology",
        "indication": "Paroxysmal nocturnal hemoglobinuria (PNH) in adults",
        "novartis_url": "https://www.novartis.com/us-en/products/fabhalta",
        "patient_website": "https://www.fabhalta.com",
        "medication_guide_url": "https://www.novartis.com/us-en/sites/novartis_us/files/fabhalta_prescribing_information.pdf",
        "support_program": {"name": "Novartis Patient Assistance", "url": "https://www.fabhalta.com/support", "phone": "1-800-282-7630"},
    },
]

# Lookup index: lowercase brand name → product dict
_PRODUCT_INDEX: dict[str, dict] = {p["brand_name"].lower(): p for p in NOVARTIS_PRODUCTS}

# Also index by generic name for flexible lookup
for _p in NOVARTIS_PRODUCTS:
    _gen = _p["generic_name"].lower()
    if _gen not in _PRODUCT_INDEX:
        _PRODUCT_INDEX[_gen] = _p


# ---------------------------------------------------------------------------
# Novartis pipeline reference data (curated from public disclosures)
# ---------------------------------------------------------------------------

NOVARTIS_PIPELINE = [
    {"compound": "Iptacopan (LNP023)", "phase": "Approved", "therapeutic_area": "Hematology", "mechanism": "Complement factor B inhibitor", "indication": "Paroxysmal nocturnal hemoglobinuria"},
    {"compound": "Remibrutinib (LOU064)", "phase": "Phase III", "therapeutic_area": "Immunology", "mechanism": "BTK inhibitor", "indication": "Chronic spontaneous urticaria"},
    {"compound": "Pelabresib (CPI-0610)", "phase": "Phase III", "therapeutic_area": "Hematology", "mechanism": "BET inhibitor", "indication": "Myelofibrosis"},
    {"compound": "Inavolisib", "phase": "Phase III", "therapeutic_area": "Oncology", "mechanism": "PI3K alpha inhibitor", "indication": "HR+/HER2- breast cancer"},
    {"compound": "Atrasentan", "phase": "Phase III", "therapeutic_area": "Nephrology", "mechanism": "Endothelin A receptor antagonist", "indication": "IgA nephropathy"},
    {"compound": "Pluvicto (177Lu-PSMA-617)", "phase": "Phase III", "therapeutic_area": "Oncology", "mechanism": "Radioligand therapy", "indication": "Pre-taxane mCRPC (PSMA+)"},
    {"compound": "Scemblix (asciminib)", "phase": "Phase III", "therapeutic_area": "Oncology", "mechanism": "STAMP inhibitor (allosteric BCR-ABL1)", "indication": "Newly diagnosed Ph+ CML"},
    {"compound": "Kisqali (ribociclib)", "phase": "Phase III", "therapeutic_area": "Oncology", "mechanism": "CDK4/6 inhibitor", "indication": "Early breast cancer (adjuvant)"},
    {"compound": "LNP023 (iptacopan)", "phase": "Phase III", "therapeutic_area": "Nephrology", "mechanism": "Complement factor B inhibitor", "indication": "C3 glomerulopathy"},
    {"compound": "Cosentyx (secukinumab) IV", "phase": "Phase III", "therapeutic_area": "Immunology", "mechanism": "IL-17A inhibitor", "indication": "IV formulation for plaque psoriasis"},
    {"compound": "Pelacarsen (TQJ230)", "phase": "Phase III", "therapeutic_area": "Cardiovascular", "mechanism": "Antisense oligonucleotide (Lp(a) lowering)", "indication": "Cardiovascular risk reduction in elevated Lp(a)"},
    {"compound": "CFZ533 (iscalimab)", "phase": "Phase III", "therapeutic_area": "Transplantation", "mechanism": "Anti-CD40 monoclonal antibody", "indication": "Kidney transplant rejection prevention"},
    {"compound": "VAY736 (ianalumab)", "phase": "Phase III", "therapeutic_area": "Immunology", "mechanism": "Anti-BAFF receptor monoclonal antibody", "indication": "Systemic lupus erythematosus, Sjogren's syndrome"},
    {"compound": "NIS793 (lacnotuzumab)", "phase": "Phase II", "therapeutic_area": "Oncology", "mechanism": "Anti-TGF-beta monoclonal antibody", "indication": "Pancreatic cancer"},
    {"compound": "MBG453 (sabatolimab)", "phase": "Phase III", "therapeutic_area": "Hematology", "mechanism": "Anti-TIM-3 monoclonal antibody", "indication": "Myelodysplastic syndromes / AML"},
]


# ---------------------------------------------------------------------------
# Novartis safety communications reference (curated)
# ---------------------------------------------------------------------------

NOVARTIS_SAFETY_COMMUNICATIONS = [
    {
        "title": "Important Safety Information Update for Entresto",
        "date": "2024-06",
        "product": "Entresto",
        "type": "Dear HCP Letter",
        "summary": "Updated warnings regarding angioedema risk, hypotension, and renal impairment. Contraindicated with ACE inhibitors.",
        "url": "https://www.novartis.com/us-en/sites/novartis_us/files/entresto_safety_letter.pdf",
    },
    {
        "title": "Kisqali: QT Prolongation Monitoring Recommendations",
        "date": "2024-03",
        "product": "Kisqali",
        "type": "Dear HCP Letter",
        "summary": "ECG monitoring recommended before and during treatment. Dose modification for QTcF prolongation >480 ms.",
        "url": "https://www.novartis.com/us-en/sites/novartis_us/files/kisqali_safety_letter.pdf",
    },
    {
        "title": "Zolgensma: Hepatotoxicity Risk and Monitoring",
        "date": "2023-08",
        "product": "Zolgensma",
        "type": "Safety Communication",
        "summary": "Cases of acute serious liver injury reported. Liver function tests required before and regularly after infusion.",
        "url": "https://www.novartis.com/us-en/sites/novartis_us/files/zolgensma_safety_communication.pdf",
    },
    {
        "title": "Pluvicto: Bone Marrow Suppression and Renal Toxicity",
        "date": "2024-01",
        "product": "Pluvicto",
        "type": "Dear HCP Letter",
        "summary": "Monitor complete blood counts and renal function. Dose delay or discontinuation for severe myelosuppression.",
        "url": "https://www.novartis.com/us-en/sites/novartis_us/files/pluvicto_safety_letter.pdf",
    },
    {
        "title": "Cosentyx: Inflammatory Bowel Disease Cases",
        "date": "2023-11",
        "product": "Cosentyx",
        "type": "Safety Communication",
        "summary": "Post-marketing cases of new-onset or exacerbation of inflammatory bowel disease. Monitor and discontinue if IBD develops.",
        "url": "https://www.novartis.com/us-en/sites/novartis_us/files/cosentyx_safety_ibd.pdf",
    },
    {
        "title": "Jakavi: Risk of Non-Melanoma Skin Cancer",
        "date": "2023-06",
        "product": "Jakavi",
        "type": "Safety Communication",
        "summary": "Increased risk of non-melanoma skin cancer. Periodic skin examination recommended for all patients.",
        "url": "https://www.novartis.com/us-en/sites/novartis_us/files/jakafi_safety_skin_cancer.pdf",
    },
    {
        "title": "Promacta: Hepatotoxicity and Thromboembolic Risk Update",
        "date": "2024-02",
        "product": "Promacta",
        "type": "Dear HCP Letter",
        "summary": "Hepatotoxicity risk requires liver function monitoring. Risk of thrombotic/thromboembolic complications including portal vein thrombosis.",
        "url": "https://www.novartis.com/us-en/sites/novartis_us/files/promacta_safety_letter.pdf",
    },
    {
        "title": "Tasigna: Cardiovascular Events and Pancreatitis",
        "date": "2023-09",
        "product": "Tasigna",
        "type": "Safety Communication",
        "summary": "Risk of peripheral arterial occlusive disease, coronary heart disease, and cerebrovascular events. Lipase elevation and pancreatitis reported.",
        "url": "https://www.novartis.com/us-en/sites/novartis_us/files/tasigna_safety_cardiovascular.pdf",
    },
    {
        "title": "Kesimpta: Progressive Multifocal Leukoencephalopathy Warning",
        "date": "2024-04",
        "product": "Kesimpta",
        "type": "Safety Communication",
        "summary": "PML risk in patients treated with anti-CD20 antibodies. Withhold treatment at first sign of PML.",
        "url": "https://www.novartis.com/us-en/sites/novartis_us/files/kesimpta_safety_pml.pdf",
    },
]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def get_products(args: dict) -> dict:
    """
    Tool: get-products

    Return Novartis product portfolio. Optionally filter by therapeutic area
    or search by brand/generic name.
    """
    ta_filter = ensure_str(args.get("therapeutic_area") or "").strip().lower()
    query = (args.get("query") or args.get("drug_name") or args.get("drug")
             or args.get("name") or "").strip().lower()

    results = []
    for product in NOVARTIS_PRODUCTS:
        if ta_filter and ta_filter not in product["therapeutic_area"].lower():
            continue
        if query and (query not in product["brand_name"].lower()
                      and query not in product["generic_name"].lower()):
            continue
        results.append({
            "brand_name": product["brand_name"],
            "generic_name": product["generic_name"],
            "therapeutic_area": product["therapeutic_area"],
            "indication": product["indication"],
            "novartis_url": product["novartis_url"],
        })

    return {
        "status": "ok",
        "total": len(results),
        "therapeutic_area_filter": ta_filter if ta_filter else None,
        "query_filter": query if query else None,
        "products": results,
        "source": "Novartis public product portfolio (curated reference data)",
    }


def get_pipeline(args: dict) -> dict:
    """
    Tool: get-pipeline

    Return Novartis development pipeline. Optionally filter by phase or
    therapeutic area.
    """
    phase_filter = ensure_str(args.get("phase") or "").strip().lower()
    ta_filter = ensure_str(args.get("therapeutic_area") or "").strip().lower()

    results = []
    for candidate in NOVARTIS_PIPELINE:
        if phase_filter and phase_filter not in candidate["phase"].lower():
            continue
        if ta_filter and ta_filter not in candidate["therapeutic_area"].lower():
            continue
        results.append(candidate)

    return {
        "status": "ok",
        "total": len(results),
        "phase_filter": phase_filter if phase_filter else None,
        "therapeutic_area_filter": ta_filter if ta_filter else None,
        "pipeline": results,
        "source": "Novartis public pipeline disclosures (curated reference data)",
    }


def get_safety_info(args: dict) -> dict:
    """
    Tool: get-safety-info

    Get safety information for a specific Novartis product by combining
    curated reference data with live openFDA label and FAERS data.
    """
    product_name = _resolve_product(args)
    if not product_name:
        return {"status": "error", "message": "product_name is required"}

    # Step 1: Find product in curated index
    product = _PRODUCT_INDEX.get(product_name.lower())
    if not product:
        # Fuzzy fallback: check if query is a substring of any brand/generic
        for key, val in _PRODUCT_INDEX.items():
            if product_name.lower() in key:
                product = val
                break

    if not product:
        return {
            "status": "not_found",
            "message": f"'{product_name}' not found in Novartis product portfolio. "
                       f"Known products: {', '.join(p['brand_name'] for p in NOVARTIS_PRODUCTS)}",
            "product_name": product_name,
        }

    brand = product["brand_name"]
    generic = product["generic_name"]
    sources = ["Novartis curated reference"]

    # Step 2: Enrich with openFDA label data
    label_ar = None
    boxed_warning = None
    label = _get_openfda_label(generic)
    if not label:
        label = _get_openfda_label(brand)
    if label:
        sources.append("openFDA drug label")
        raw_ar = _first_label_section(label, "adverse_reactions")
        if raw_ar:
            label_ar = raw_ar[:3000] if len(raw_ar) > 3000 else raw_ar
        raw_bw = _first_label_section(label, "boxed_warning")
        if raw_bw:
            boxed_warning = raw_bw[:1000] if len(raw_bw) > 1000 else raw_bw

    # Step 3: Enrich with FAERS top reactions
    faers_reactions = []
    encoded = _quote(generic.split("/")[0] if "/" in generic else generic)
    url = f"{OPENFDA_EVENT_URL}?search=patient.drug.openfda.generic_name:\"{encoded}\"&count=patient.reaction.reactionmeddrapt.exact"
    try:
        data = _fetch(url)
        for item in data.get("results", [])[:20]:
            faers_reactions.append({
                "reaction": item.get("term"),
                "report_count": item.get("count"),
            })
        if faers_reactions:
            sources.append("openFDA FAERS")
    except RuntimeError:
        pass

    return {
        "status": "ok",
        "brand_name": brand,
        "generic_name": generic,
        "therapeutic_area": product["therapeutic_area"],
        "indication": product["indication"],
        "has_boxed_warning": boxed_warning is not None and len(str(boxed_warning).strip()) > 0,
        "boxed_warning": boxed_warning,
        "adverse_reactions": label_ar,
        "faers_top_reactions": faers_reactions,
        "medication_guide_url": product.get("medication_guide_url"),
        "novartis_url": product.get("novartis_url"),
        "sources": sources,
    }


def get_medical_letters(args: dict) -> dict:
    """
    Tool: get-medical-letters

    Return safety communications and Dear HCP letters for Novartis products.
    Optionally filter by product name or search query.
    """
    product_filter = (args.get("product_name") or args.get("drug_name")
                      or args.get("drug") or "").strip().lower()
    query = ensure_str(args.get("query") or "").strip().lower()

    results = []
    for comm in NOVARTIS_SAFETY_COMMUNICATIONS:
        if product_filter and product_filter not in comm["product"].lower():
            continue
        if query and (query not in comm["title"].lower()
                      and query not in comm["summary"].lower()
                      and query not in comm["product"].lower()):
            continue
        results.append(comm)

    return {
        "status": "ok",
        "product_filter": product_filter if product_filter else None,
        "query_filter": query if query else None,
        "total": len(results),
        "communications": results,
        "sources": ["Novartis safety communications (curated reference data)"],
    }


def get_patient_resources(args: dict) -> dict:
    """
    Tool: get-patient-resources

    Return patient medication guides, educational materials, and support
    program information for a Novartis product.
    """
    product_name = _resolve_product(args)
    if not product_name:
        return {"status": "error", "message": "product_name is required"}

    product = _PRODUCT_INDEX.get(product_name.lower())
    if not product:
        for key, val in _PRODUCT_INDEX.items():
            if product_name.lower() in key:
                product = val
                break

    if not product:
        return {
            "status": "not_found",
            "message": f"'{product_name}' not found in Novartis product portfolio. "
                       f"Known products: {', '.join(p['brand_name'] for p in NOVARTIS_PRODUCTS)}",
            "product_name": product_name,
        }

    # Supplement with openFDA label indications for plain-language summary
    indication_summary = product["indication"]
    label = _get_openfda_label(product["generic_name"])
    if not label:
        label = _get_openfda_label(product["brand_name"])
    if label:
        raw_ind = _first_label_section(label, "indications_and_usage")
        if raw_ind:
            indication_summary = raw_ind[:1500] if len(raw_ind) > 1500 else raw_ind

    return {
        "status": "ok",
        "brand_name": product["brand_name"],
        "generic_name": product["generic_name"],
        "therapeutic_area": product["therapeutic_area"],
        "medication_guide_url": product.get("medication_guide_url"),
        "patient_website": product.get("patient_website"),
        "support_program": product.get("support_program"),
        "indication_summary": indication_summary,
        "novartis_url": product.get("novartis_url"),
        "sources": ["Novartis curated reference", "openFDA drug label" if label else None],
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
