#!/usr/bin/env python3
"""
DrugBank Proxy — aggregates free public APIs to provide comprehensive drug data.

Usage:
    echo '{"tool": "get-drug-info", "args": {"drug_name": "metformin"}}' | python3 drugbank_proxy.py

Data sources (all free, no API key required):
  - PubChem REST PUG: molecular data, identifiers, classification
  - openFDA drug label API: regulatory status, clinical sections
  - RxNav REST: drug-drug interactions via RxCUI
  - openFDA FAERS: adverse effect frequency from post-marketing reports

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.
"""

import json
import sys
import urllib.parse
import urllib.request
import urllib.error

PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"
OPENFDA_EVENT_URL = "https://api.fda.gov/drug/event.json"
REQUEST_TIMEOUT_SECONDS = 20


def _fetch(url: str) -> dict:
    """Execute an HTTP GET and return parsed JSON. Raises RuntimeError on failure."""
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
        msg = error_body.get("error", {}).get("message", exc.reason) if error_body else exc.reason
        raise RuntimeError(f"HTTP {exc.code}: {msg}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc



def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _get_pubchem_cid(drug_name: str) -> int | None:
    """Resolve a drug name to a PubChem CID."""
    url = f"{PUBCHEM_BASE}/compound/name/{_quote(drug_name)}/cids/JSON"
    try:
        data = _fetch(url)
        cids = data.get("IdentifierList", {}).get("CID", [])
        return cids[0] if cids else None
    except RuntimeError:
        return None


def _get_pubchem_properties(cid: int) -> dict:
    """Fetch key molecular properties for a PubChem CID."""
    props = "MolecularFormula,MolecularWeight,IUPACName,InChIKey,CanonicalSMILES,XLogP"
    url = f"{PUBCHEM_BASE}/compound/cid/{cid}/property/{props}/JSON"
    try:
        data = _fetch(url)
        results = data.get("PropertyTable", {}).get("Properties", [])
        return results[0] if results else {}
    except RuntimeError:
        return {}


def _get_pubchem_description(cid: int) -> str | None:
    """Fetch the compound description/summary from PubChem."""
    url = f"{PUBCHEM_BASE}/compound/cid/{cid}/description/JSON"
    try:
        data = _fetch(url)
        infos = data.get("InformationList", {}).get("Information", [])
        for info in infos:
            desc = info.get("Description")
            if desc and len(desc) > 20:
                return desc[:1000] if len(desc) > 1000 else desc
        return None
    except RuntimeError:
        return None


def _get_pubchem_synonyms(cid: int, limit: int = 10) -> list[str]:
    """Fetch synonyms (brand names, alternative names) from PubChem."""
    url = f"{PUBCHEM_BASE}/compound/cid/{cid}/synonyms/JSON"
    try:
        data = _fetch(url)
        info_list = data.get("InformationList", {}).get("Information", [])
        if info_list:
            syns = info_list[0].get("Synonym", [])
            return syns[:limit]
        return []
    except RuntimeError:
        return []


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



def _first_label_section(label: dict, field: str) -> str | None:
    """Extract the first entry from a label section (openFDA returns lists)."""
    val = label.get(field)
    if isinstance(val, list) and val:
        return val[0]
    return val


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def get_drug_info(args: dict) -> dict:
    """
    Tool: get-drug-info

    Retrieves comprehensive drug information by aggregating PubChem (molecular
    data, identifiers) and openFDA (regulatory status, clinical classification).
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    # PubChem: molecular identity
    cid = _get_pubchem_cid(drug_name)
    pubchem_data = {}
    if cid:
        props = _get_pubchem_properties(cid)
        desc = _get_pubchem_description(cid)
        synonyms = _get_pubchem_synonyms(cid)
        pubchem_data = {
            "pubchem_cid": cid,
            "iupac_name": props.get("IUPACName"),
            "molecular_formula": props.get("MolecularFormula"),
            "molecular_weight": props.get("MolecularWeight"),
            "inchikey": props.get("InChIKey"),
            "canonical_smiles": props.get("CanonicalSMILES"),
            "xlogp": props.get("XLogP"),
            "description": desc,
            "synonyms": synonyms,
        }

    # openFDA: regulatory and clinical classification
    openfda_data = {}
    label = _get_openfda_label(drug_name)
    if label:
        ofd = label.get("openfda", {})
        openfda_data = {
            "brand_name": ofd.get("brand_name", [None])[0] if ofd.get("brand_name") else None,
            "generic_name": ofd.get("generic_name", [None])[0] if ofd.get("generic_name") else None,
            "manufacturer": ofd.get("manufacturer_name", [None])[0] if ofd.get("manufacturer_name") else None,
            "product_type": ofd.get("product_type", [None])[0] if ofd.get("product_type") else None,
            "route": ofd.get("route", []),
            "substance_name": ofd.get("substance_name", []),
            "pharm_class_epc": ofd.get("pharm_class_epc", []),
            "pharm_class_moa": ofd.get("pharm_class_moa", []),
            "application_number": ofd.get("application_number", [None])[0] if ofd.get("application_number") else None,
        }

    if not cid and not label:
        return {
            "status": "not_found",
            "message": f"No data found for '{drug_name}' in PubChem or openFDA",
            "drug_name": drug_name,
        }

    return {
        "status": "ok",
        "drug_name": drug_name,
        "pubchem": pubchem_data,
        "regulatory": openfda_data,
        "sources": [s for s in ["PubChem" if cid else None, "openFDA" if label else None] if s],
    }


def get_interactions(args: dict) -> dict:
    """
    Tool: get-interactions

    Retrieves drug-drug interactions from two sources:
    - RxNav interaction API (structured interaction pairs with severity)
    - openFDA drug label drug_interactions section (clinical narrative)
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    # Source: openFDA label drug_interactions section
    # Note: RxNav interaction API deprecated (404 since March 2026, per rxnav_proxy.py)
    label_text = None
    label = _get_openfda_label(drug_name)
    if label:
        raw = _first_label_section(label, "drug_interactions")
        if raw:
            label_text = raw[:3000] if len(raw) > 3000 else raw

    # Also pull FAERS co-reported drugs for empirical interaction signal
    faers_codrugs = []
    encoded = _quote(drug_name)
    url = f"{OPENFDA_EVENT_URL}?search=patient.drug.openfda.generic_name:\"{encoded}\"&count=patient.drug.openfda.generic_name.exact"
    try:
        data = _fetch(url)
        raw_results = data.get("results", [])
        # Top co-reported drugs (excluding the queried drug itself)
        for item in raw_results[:30]:
            term = item.get("term", "")
            if term.upper() != drug_name.upper():
                faers_codrugs.append({
                    "co_reported_drug": term,
                    "report_count": item.get("count"),
                })
            if len(faers_codrugs) >= 20:
                break
    except RuntimeError:
        pass

    if not label_text and not faers_codrugs:
        return {
            "status": "not_found",
            "message": f"No interaction data found for '{drug_name}'",
            "drug_name": drug_name,
        }

    return {
        "status": "ok",
        "drug_name": drug_name,
        "label_drug_interactions": label_text,
        "faers_co_reported_drugs": faers_codrugs,
        "sources": [s for s in [
            "openFDA label" if label_text else None,
            "openFDA FAERS" if faers_codrugs else None,
        ] if s],
    }


def get_pharmacology(args: dict) -> dict:
    """
    Tool: get-pharmacology

    Retrieves pharmacological profile from openFDA drug label sections:
    mechanism of action, clinical pharmacology, pharmacokinetics,
    and PubChem description for molecular context.
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    label = _get_openfda_label(drug_name)
    if not label:
        return {
            "status": "not_found",
            "message": f"No label found for '{drug_name}'",
            "drug_name": drug_name,
        }

    def _section(field: str, max_len: int = 1500) -> str | None:
        val = _first_label_section(label, field)
        if val:
            return val[:max_len] + "..." if len(val) > max_len else val
        return None

    pharmacology = {
        "mechanism_of_action": _section("mechanism_of_action"),
        "clinical_pharmacology": _section("clinical_pharmacology"),
        "pharmacokinetics": _section("pharmacokinetics"),
        "pharmacodynamics": _section("pharmacodynamics"),
        "absorption": _section("absorption"),
        "distribution": _section("distribution"),
        "metabolism": _section("metabolism"),
        "excretion": _section("excretion"),
        "overdosage": _section("overdosage"),
        "food_interactions": _section("food_drug_interactions"),
    }

    # Filter out None sections
    pharmacology = {k: v for k, v in pharmacology.items() if v is not None}

    # Supplement with PubChem description
    cid = _get_pubchem_cid(drug_name)
    pubchem_desc = None
    if cid:
        pubchem_desc = _get_pubchem_description(cid)

    # Pharmacological class from openFDA
    ofd = label.get("openfda", {})
    pharm_classes = {
        "epc": ofd.get("pharm_class_epc", []),
        "moa": ofd.get("pharm_class_moa", []),
        "pe": ofd.get("pharm_class_pe", []),
        "cs": ofd.get("pharm_class_cs", []),
    }
    pharm_classes = {k: v for k, v in pharm_classes.items() if v}

    return {
        "status": "ok",
        "drug_name": drug_name,
        "sections_found": len(pharmacology),
        "pharmacology": pharmacology,
        "pharmacological_classes": pharm_classes,
        "pubchem_description": pubchem_desc,
        "sources": [s for s in ["openFDA label", "PubChem" if pubchem_desc else None] if s],
    }


def get_targets(args: dict) -> dict:
    """
    Tool: get-targets

    Retrieves molecular target information from PubChem's bioactivity data
    and openFDA pharmacological class annotations. Returns target genes,
    mechanism classifications, and pharmacological action types.
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    targets = []

    # Source 1: openFDA pharmacological classes (mechanism of action targets)
    label = _get_openfda_label(drug_name)
    if label:
        ofd = label.get("openfda", {})
        for moa in ofd.get("pharm_class_moa", []):
            targets.append({
                "target": moa,
                "type": "mechanism_of_action",
                "source": "openFDA",
            })
        for epc in ofd.get("pharm_class_epc", []):
            targets.append({
                "target": epc,
                "type": "established_pharmacologic_class",
                "source": "openFDA",
            })

    # Source 2: PubChem — gene targets from compound-gene links
    cid = _get_pubchem_cid(drug_name)
    gene_targets = []
    if cid:
        url = f"{PUBCHEM_BASE}/compound/cid/{cid}/assaysummary/JSON"
        try:
            data = _fetch(url)
            table = data.get("Table", {})
            columns = table.get("Columns", {}).get("Column", [])
            rows = table.get("Row", [])

            # Find column indices
            gene_idx = None
            target_name_idx = None
            activity_idx = None
            for i, col in enumerate(columns):
                if col == "Target GeneSymbol":
                    gene_idx = i
                elif col == "Target Name":
                    target_name_idx = i
                elif col == "Activity Outcome":
                    activity_idx = i

            # Extract unique gene targets
            seen_genes = set()
            for row in rows[:200]:  # cap to avoid huge responses
                cells = row.get("Cell", [])
                gene = cells[gene_idx] if gene_idx is not None and gene_idx < len(cells) else None
                target_name = cells[target_name_idx] if target_name_idx is not None and target_name_idx < len(cells) else None
                activity = cells[activity_idx] if activity_idx is not None and activity_idx < len(cells) else None

                if gene and gene not in seen_genes and activity == "Active":
                    seen_genes.add(gene)
                    gene_targets.append({
                        "gene_symbol": gene,
                        "target_name": target_name,
                        "activity": activity,
                        "source": "PubChem BioAssay",
                    })
        except RuntimeError:
            pass

    return {
        "status": "ok",
        "drug_name": drug_name,
        "pubchem_cid": cid,
        "pharmacological_classes": targets,
        "gene_targets": gene_targets[:30],
        "total_gene_targets": len(gene_targets),
        "sources": [s for s in [
            "openFDA" if targets else None,
            "PubChem BioAssay" if gene_targets else None,
        ] if s],
    }


def get_adverse_effects(args: dict) -> dict:
    """
    Tool: get-adverse-effects

    Retrieves adverse effects from two complementary sources:
    - openFDA drug label: adverse_reactions section (clinical narrative)
    - openFDA FAERS: top reported reactions by frequency (post-marketing)
    """
    drug_name = args.get("drug_name", "").strip()
    if not drug_name:
        return {"status": "error", "message": "drug_name is required"}

    # Source 1: Label adverse reactions section
    label_text = None
    boxed_warning = None
    label = _get_openfda_label(drug_name)
    if label:
        raw_ar = _first_label_section(label, "adverse_reactions")
        if raw_ar:
            label_text = raw_ar[:3000] if len(raw_ar) > 3000 else raw_ar
        raw_bw = _first_label_section(label, "boxed_warning")
        if raw_bw:
            boxed_warning = raw_bw[:1000] if len(raw_bw) > 1000 else raw_bw

    # Source 2: FAERS top reactions by frequency
    faers_reactions = []
    encoded = _quote(drug_name)
    url = f"{OPENFDA_EVENT_URL}?search=patient.drug.openfda.generic_name:\"{encoded}\"&count=patient.reaction.reactionmeddrapt.exact"
    try:
        data = _fetch(url)
        raw = data.get("results", [])
        # Top 25 reactions
        for item in raw[:25]:
            faers_reactions.append({
                "reaction": item.get("term"),
                "report_count": item.get("count"),
            })
    except RuntimeError:
        pass

    if not label_text and not faers_reactions:
        return {
            "status": "not_found",
            "message": f"No adverse effect data found for '{drug_name}'",
            "drug_name": drug_name,
        }

    return {
        "status": "ok",
        "drug_name": drug_name,
        "label_adverse_reactions": label_text,
        "boxed_warning": boxed_warning,
        "faers_top_reactions": faers_reactions,
        "faers_reaction_count": len(faers_reactions),
        "sources": [s for s in [
            "openFDA label" if label_text else None,
            "openFDA FAERS" if faers_reactions else None,
        ] if s],
    }


TOOL_DISPATCH = {
    "get-drug-info": get_drug_info,
    "get-interactions": get_interactions,
    "get-pharmacology": get_pharmacology,
    "get-targets": get_targets,
    "get-adverse-effects": get_adverse_effects,
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
        result = {
            "status": "error",
            "message": f"Unknown tool '{tool_name}'. Known tools: {known}",
        }
        print(json.dumps(result))
        sys.exit(1)

    handler = TOOL_DISPATCH[tool_name]
    result = handler(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
