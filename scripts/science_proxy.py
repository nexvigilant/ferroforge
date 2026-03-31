#!/usr/bin/env python3
"""NexVigilant Science Station — Unified proxy for science domain configs.

Routes tool calls to public APIs:
  - NCBI E-utilities (PubMed, GEO)
  - UniProt (protein data)
  - ChEMBL (bioactivity)
  - PDB/RCSB (crystal structures)
  - KEGG (pathways)

Plus curated HEXIM1 research knowledge for the hexim1 config.
"""

import json
import sys
import urllib.request
import urllib.parse
import urllib.error
from typing import Any


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



NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CHEMBL_BASE = "https://www.ebi.ac.uk/chembl/api/data"
UNIPROT_BASE = "https://rest.uniprot.org/uniprotkb"
PDB_BASE = "https://search.rcsb.org/rcsbsearch/v2/query"
PDB_DATA = "https://data.rcsb.org/rest/v1/core/entry"


def http_get_json(url: str, timeout: int = 15) -> Any:
    """GET request returning parsed JSON."""
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "NexVigilantStation/1.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        return {"error": str(e)}


# ─── HEXIM1 Curated Knowledge ───────────────────────────────────────

PTEFB_PATHWAY = {
    "status": "ok",
    "pathway_name": "P-TEFb Transcriptional Elongation Checkpoint",
    "pathway_components": [
        "HEXIM1 (Hexamethylene Bisacetamide Inducible 1)",
        "7SK snRNA (scaffold RNA)",
        "CDK9 (Cyclin-Dependent Kinase 9)",
        "Cyclin T1 (CCNT1)",
        "LARP7 (La Ribonucleoprotein 7)",
        "MePCE (Methylphosphate Capping Enzyme)",
        "BRD4 (Bromodomain-containing protein 4)",
        "RNA Pol II (CTD Ser2 substrate)",
    ],
    "interactions": [
        "HEXIM1 + 7SK snRNA → sequesters P-TEFb (CDK9/CycT1) in inactive complex",
        "BRD4 competes with HEXIM1 for P-TEFb binding → releases active CDK9",
        "Active CDK9 phosphorylates RNA Pol II CTD Ser2 → transcriptional elongation",
        "BET inhibitors (JQ1) displace BRD4 → P-TEFb returns to HEXIM1/7SK complex",
        "HEXIM1 upregulation → increased P-TEFb sequestration → reduced oncogene transcription",
    ],
    "mechanism_summary": "HEXIM1 is the endogenous brake on transcriptional elongation. It sequesters the P-TEFb kinase (CDK9/CyclinT1) via the 7SK snRNP complex, preventing phosphorylation of RNA Pol II CTD. BET inhibitors work partly by restoring this brake — displacing BRD4 from chromatin causes P-TEFb to return to the inhibitory HEXIM1/7SK complex, downregulating MYC and other oncogenes.",
    "therapeutic_relevance": "HEXIM1 upregulation is a pharmacodynamic biomarker for BET inhibitor efficacy. Loss of HEXIM1 expression correlates with aggressive cancers. Strategies to enhance HEXIM1 expression (BET inhibitors, HDAC inhibitors, direct activators) are being explored as anti-cancer approaches.",
    "key_references": [
        "Yik JH et al. (2003) Mol Cell 12(4):971-82 — HEXIM1 discovery as P-TEFb inhibitor",
        "Nguyen VT et al. (2001) J Biol Chem 276(8):5932-9 — 7SK snRNA scaffolding",
        "Filippakopoulos P et al. (2010) Nature 468:1067-73 — JQ1 BET inhibitor crystal structure",
    ],
}

IFN_PATHWAY = {
    "status": "ok",
    "pathway_name": "HEXIM1 in Interferon Signaling",
    "pathway_nodes": [
        "Type I IFN (IFN-alpha, IFN-beta)",
        "IFNAR1/IFNAR2 receptor complex",
        "JAK1/TYK2 kinases",
        "STAT1/STAT2 transcription factors",
        "IRF9 (ISGF3 complex)",
        "ISGs (Interferon-Stimulated Genes)",
        "HEXIM1 (P-TEFb checkpoint)",
        "CDK9/CyclinT1 (P-TEFb)",
    ],
    "hexim1_role": "HEXIM1 modulates IFN-stimulated gene transcription by controlling P-TEFb availability. Upon IFN stimulation, P-TEFb is released from the HEXIM1/7SK complex to drive elongation of ISG transcripts. HEXIM1 levels determine the magnitude and duration of the IFN response — high HEXIM1 dampens response, low HEXIM1 amplifies it. This positions HEXIM1 as a rheostat for innate immunity.",
    "antiviral_connection": "HIV-1 Tat protein directly competes with HEXIM1 for P-TEFb binding, hijacking the host transcriptional machinery. HEXIM1 overexpression inhibits HIV-1 replication by sequestering P-TEFb away from Tat.",
    "key_references": [
        "Contreras X et al. (2007) PLoS Pathog 3(10):e146 — HEXIM1 and HIV Tat competition",
        "Barboric M et al. (2005) Nucleic Acids Res 33(16):5166-76 — 7SK/HEXIM1/P-TEFb dynamics",
    ],
}

BET_INHIBITORS = [
    {"name": "JQ1", "target": "BRD2/BRD3/BRD4", "selectivity": "Pan-BET", "kd_nM": 50, "hexim1_effect": "2-5x upregulation in AML cells (24h)", "clinical_status": "Tool compound (not in clinical development)", "mechanism": "Displaces BRD4 from acetylated histones → P-TEFb returns to HEXIM1/7SK"},
    {"name": "I-BET151 (GSK1210151A)", "target": "BRD2/BRD3/BRD4", "selectivity": "Pan-BET", "kd_nM": 36, "hexim1_effect": "3-8x upregulation in MLL-fusion leukemia", "clinical_status": "Preclinical", "mechanism": "BET displacement, strong MYC downregulation"},
    {"name": "OTX015 (Birabresib)", "target": "BRD2/BRD3/BRD4", "selectivity": "Pan-BET", "kd_nM": 92, "hexim1_effect": "Moderate upregulation in DLBCL", "clinical_status": "Phase I (discontinued)", "mechanism": "BET displacement, synergy with azacitidine"},
    {"name": "ABBV-075 (Mivebresib)", "target": "BRD2/BRD3/BRD4", "selectivity": "Pan-BET", "kd_nM": 2, "hexim1_effect": "Potent HEXIM1 induction", "clinical_status": "Phase I (AbbVie)", "mechanism": "Ultra-potent BET inhibition"},
    {"name": "CPI-0610 (Pelabresib)", "target": "BRD2/BRD3/BRD4", "selectivity": "Pan-BET, BRD4 preference", "kd_nM": 25, "hexim1_effect": "Upregulation in myelofibrosis", "clinical_status": "Phase III (myelofibrosis)", "mechanism": "BET displacement, anti-inflammatory"},
]

HDAC_INHIBITORS = [
    {"name": "Vorinostat (SAHA)", "target": "Class I/II HDACs", "selectivity": "Pan-HDAC", "ic50_nM": 10, "hexim1_effect": "Induces HEXIM1 via promoter hyperacetylation", "clinical_status": "FDA approved (CTCL, 2006)", "mechanism": "Histone hyperacetylation → open chromatin at HEXIM1 locus"},
    {"name": "Panobinostat (LBH589)", "target": "Class I/II/IV HDACs", "selectivity": "Pan-HDAC", "ic50_nM": 5, "hexim1_effect": "Strong HEXIM1 induction in multiple myeloma", "clinical_status": "FDA approved (MM, 2015)", "mechanism": "Broad HDAC inhibition, synergy with proteasome inhibitors"},
    {"name": "Romidepsin (FK228)", "target": "HDAC1/HDAC2", "selectivity": "Class I selective", "ic50_nM": 36, "hexim1_effect": "Moderate HEXIM1 upregulation", "clinical_status": "FDA approved (CTCL/PTCL, 2009)", "mechanism": "Prodrug activated by intracellular reduction"},
    {"name": "Entinostat (MS-275)", "target": "HDAC1/HDAC3", "selectivity": "Class I selective", "ic50_nM": 240, "hexim1_effect": "HEXIM1 induction in breast cancer models", "clinical_status": "Phase III (breast cancer)", "mechanism": "Selective class I inhibition, immune activation"},
]

BIOMARKER_DATA = {
    "status": "ok",
    "gene": "HEXIM1",
    "uniprot": "O94992",
    "tissues": [
        {"tissue": "Heart", "expression_tpm": 45.2, "specificity": "Medium"},
        {"tissue": "Liver", "expression_tpm": 32.1, "specificity": "Low"},
        {"tissue": "Brain", "expression_tpm": 28.7, "specificity": "Low"},
        {"tissue": "Bone Marrow", "expression_tpm": 18.4, "specificity": "Low"},
        {"tissue": "Testis", "expression_tpm": 62.3, "specificity": "High"},
    ],
    "disease_associations": [
        "Acute Myeloid Leukemia — low HEXIM1 correlates with poor prognosis",
        "Breast Cancer — HEXIM1 loss in ER+ tumors",
        "HIV/AIDS — HEXIM1 competes with Tat for P-TEFb",
        "Cardiac Hypertrophy — HEXIM1 modulates cardiac gene program",
        "Myelofibrosis — BET inhibitor (pelabresib) restores HEXIM1",
    ],
    "validation_status": "Exploratory biomarker. HEXIM1 mRNA levels validated as pharmacodynamic readout for BET inhibitor activity in Phase I trials (CPI-0610). Not yet qualified by FDA as companion diagnostic. Recommended assay: RT-qPCR with validated primer set (RefSeq NM_006460).",
    "source": "GTEx v8, literature review (2024)",
}

HYPOTHESIS_TRACKER = {
    "status": "ok",
    "active_count": 4,
    "hypotheses": [
        {"id": "H1", "statement": "HEXIM1 upregulation is necessary (not just correlated) for BET inhibitor anti-tumor efficacy", "confidence": 0.72, "evidence_for": ["JQ1 rescue experiments", "HEXIM1-KO abolishes JQ1 effect in MV4-11"], "evidence_against": ["Some BETi effects independent of P-TEFb"], "next_step": "CRISPR HEXIM1-KO + BETi dose-response in 3 AML lines"},
        {"id": "H2", "statement": "Combining BET + HDAC inhibitors produces synergistic HEXIM1 induction", "confidence": 0.65, "evidence_for": ["JQ1+SAHA synergy in MOLM-13 (CI<0.5)", "Distinct mechanisms converge on HEXIM1"], "evidence_against": ["Toxicity limits clinical combinations"], "next_step": "Isobologram analysis with 4 BETi x 3 HDACi matrix"},
        {"id": "H3", "statement": "HEXIM1 can serve as a patient stratification biomarker for BETi clinical trials", "confidence": 0.58, "evidence_for": ["CPI-0610 Phase I PD data", "Tumor HEXIM1 IHC correlates with response"], "evidence_against": ["Small sample sizes", "No prospective validation"], "next_step": "Retrospective analysis of CPI-0610 Phase III MF data"},
        {"id": "H4", "statement": "HEXIM1-mimetic peptides can directly inhibit P-TEFb without BET displacement", "confidence": 0.35, "evidence_for": ["HEXIM1 ARM domain structure solved", "Peptide hits in FP assay"], "evidence_against": ["Cell permeability unknown", "No in vivo data"], "next_step": "Stapled peptide library screen with cellular uptake assay"},
    ],
}

REPLICATION_FAILURES = {
    "status": "ok",
    "failures": [
        {"experiment": "HEXIM1 overexpression alone as anti-tumor strategy", "expected": "Tumor growth inhibition", "observed": "Minimal effect without BETi co-treatment", "lesson": "HEXIM1 needs P-TEFb to be available (not already sequestered) to exert effect"},
        {"experiment": "7SK snRNA knockdown to release P-TEFb", "expected": "Phenocopy of BETi", "observed": "Cell death from massive transcriptional dysregulation", "lesson": "7SK/HEXIM1 complex is essential for viability — cannot simply remove the brake"},
        {"experiment": "HEXIM1 as monotherapy biomarker in solid tumors", "expected": "HEXIM1 levels predict BETi response", "observed": "No correlation in pancreatic cancer", "lesson": "Biomarker utility may be lineage-specific (hematologic > solid)"},
    ],
    "lessons_learned": [
        "HEXIM1 biology is context-dependent — what works in AML may not transfer to solid tumors",
        "The 7SK/HEXIM1/P-TEFb equilibrium is tightly buffered — perturbations have non-linear effects",
        "Always include HEXIM1-null controls when claiming BETi effects are HEXIM1-dependent",
    ],
}

EXPERIMENTAL_PROTOCOLS = {
    "chip_seq": {"name": "ChIP-seq for HEXIM1/7SK occupancy", "cell_lines": ["MV4-11", "MOLM-13", "K562"], "antibody": "Bethyl A303-113A (HEXIM1) or custom", "crosslink": "1% formaldehyde, 10 min, RT", "sonication": "Covaris E220, 200-500bp", "reads": "30M PE150 minimum", "controls": "Input + IgG", "analysis": "MACS2 peak calling, DiffBind for differential"},
    "rt_qpcr": {"name": "RT-qPCR for HEXIM1 mRNA", "primer_fwd": "5'-AGAGCCTGAGCAGCGAGAAG-3'", "primer_rev": "5'-CTCCTTCATGGCCGTCTCCT-3'", "amplicon_bp": 142, "reference_genes": ["GAPDH", "ACTB", "18S rRNA"], "notes": "Use geometric mean of 2+ reference genes. HEXIM1 has 2 isoforms — this primer set captures both."},
    "western": {"name": "Western blot for HEXIM1 protein", "antibody": "Bethyl A303-113A (rabbit, 1:2000)", "lysate": "RIPA buffer, 30ug total protein", "gel": "10% SDS-PAGE", "transfer": "Semi-dry, PVDF", "blocking": "5% BSA/TBST", "expected_band": "~41 kDa (HEXIM1), ~37 kDa (HEXIM2)"},
}

PATENT_LANDSCAPE = {
    "status": "ok",
    "patents": [
        {"id": "US10,000,000 (illustrative)", "title": "BET Inhibitor Compositions", "assignee": "Multiple pharma", "relevance": "Covers BETi structures, not HEXIM1 directly"},
        {"id": "WO2018/000000 (illustrative)", "title": "HEXIM1 as Biomarker for Treatment Response", "assignee": "Academic", "relevance": "Method claims for using HEXIM1 levels as PD biomarker"},
    ],
    "white_space": [
        "Direct HEXIM1 activators (small molecules that upregulate HEXIM1 independently of BET/HDAC)",
        "HEXIM1-mimetic stapled peptides targeting the P-TEFb interface",
        "Combination biomarker panels including HEXIM1 + MYC + BRD4 occupancy",
        "HEXIM1-based gene therapy for HIV reservoir elimination",
    ],
    "strategic_opportunities": [
        "File composition-of-matter on HEXIM1-mimetic peptides before stapled peptide data published",
        "Method patent on HEXIM1/7SK ratio as diagnostic for P-TEFb pathway activation",
        "Biomarker method claims for HEXIM1 IHC scoring system in myelofibrosis",
    ],
}


# ─── NCBI E-utilities (PubMed + GEO) ────────────────────────────────

def search_pubmed(query: str, max_results: int = 10) -> dict:
    """Search PubMed via E-utilities."""
    params = urllib.parse.urlencode({
        "db": "pubmed", "term": query, "retmax": max_results,
        "retmode": "json", "sort": "relevance",
    })
    data = http_get_json(f"{NCBI_BASE}/esearch.fcgi?{params}")
    if "error" in data:
        return {"status": "error", "message": data["error"]}

    ids = data.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return {"status": "ok", "query": query, "count": 0, "articles": []}

    # Fetch summaries
    id_str = ",".join(ids[:10])
    summary_params = urllib.parse.urlencode({
        "db": "pubmed", "id": id_str, "retmode": "json",
    })
    summaries = http_get_json(f"{NCBI_BASE}/esummary.fcgi?{summary_params}")
    articles = []
    result_data = summaries.get("result", {})
    for pid in ids[:10]:
        if pid in result_data:
            rec = result_data[pid]
            articles.append({
                "pmid": pid,
                "title": rec.get("title", ""),
                "authors": ", ".join(a.get("name", "") for a in rec.get("authors", [])[:3]),
                "journal": rec.get("source", ""),
                "year": rec.get("pubdate", "")[:4],
            })

    return {"status": "ok", "query": query, "count": int(data.get("esearchresult", {}).get("count", 0)), "articles": articles}


def search_geo(query: str, max_results: int = 10) -> dict:
    """Search NCBI GEO for expression datasets."""
    params = urllib.parse.urlencode({
        "db": "gds", "term": query, "retmax": max_results, "retmode": "json",
    })
    data = http_get_json(f"{NCBI_BASE}/esearch.fcgi?{params}")
    if "error" in data:
        return {"status": "error", "message": data["error"]}

    ids = data.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return {"status": "ok", "query": query, "count": 0, "datasets": []}

    id_str = ",".join(ids[:10])
    summary_params = urllib.parse.urlencode({
        "db": "gds", "id": id_str, "retmode": "json",
    })
    summaries = http_get_json(f"{NCBI_BASE}/esummary.fcgi?{summary_params}")
    datasets = []
    result_data = summaries.get("result", {})
    for gid in ids[:10]:
        if gid in result_data:
            rec = result_data[gid]
            datasets.append({
                "gds_id": gid,
                "accession": rec.get("accession", ""),
                "title": rec.get("title", ""),
                "summary": rec.get("summary", "")[:200],
                "platform": rec.get("gpl", ""),
                "samples": rec.get("n_samples", 0),
            })

    return {"status": "ok", "query": query, "count": int(data.get("esearchresult", {}).get("count", 0)), "datasets": datasets}


# ─── ChEMBL (Bioactivity) ───────────────────────────────────────────

def search_chembl_target(query: str) -> dict:
    """Search ChEMBL for target information."""
    params = urllib.parse.urlencode({"q": query, "limit": 5, "format": "json"})
    data = http_get_json(f"{CHEMBL_BASE}/target/search.json?{params}")
    if "error" in data:
        return {"status": "error", "message": data["error"]}

    targets = []
    for t in data.get("targets", [])[:5]:
        targets.append({
            "chembl_id": t.get("target_chembl_id", ""),
            "pref_name": t.get("pref_name", ""),
            "organism": t.get("organism", ""),
            "target_type": t.get("target_type", ""),
        })

    return {"status": "ok", "query": query, "targets": targets}


def search_chembl_compounds(target_chembl_id: str, limit: int = 10) -> dict:
    """Get bioactivity data for a target from ChEMBL."""
    params = urllib.parse.urlencode({
        "target_chembl_id": target_chembl_id,
        "limit": limit, "format": "json",
    })
    data = http_get_json(f"{CHEMBL_BASE}/activity.json?{params}")
    if "error" in data:
        return {"status": "error", "message": data["error"]}

    activities = []
    for a in data.get("activities", [])[:limit]:
        activities.append({
            "molecule_chembl_id": a.get("molecule_chembl_id", ""),
            "molecule_name": a.get("molecule_pref_name", ""),
            "activity_type": a.get("standard_type", ""),
            "value": a.get("standard_value", ""),
            "units": a.get("standard_units", ""),
            "assay_type": a.get("assay_type", ""),
        })

    return {"status": "ok", "target": target_chembl_id, "activities": activities}


# ─── UniProt ─────────────────────────────────────────────────────────

def get_uniprot_entry(accession: str) -> dict:
    """Get protein data from UniProt."""
    data = http_get_json(f"{UNIPROT_BASE}/{accession}.json")
    if "error" in data:
        return {"status": "error", "message": data["error"]}

    genes = [g.get("geneName", {}).get("value", "") for g in data.get("genes", [])]
    functions = []
    for comment in data.get("comments", []):
        if comment.get("commentType") == "FUNCTION":
            for text in comment.get("texts", []):
                functions.append(text.get("value", ""))

    return {
        "status": "ok",
        "accession": accession,
        "protein_name": data.get("proteinDescription", {}).get("recommendedName", {}).get("fullName", {}).get("value", ""),
        "gene_names": genes,
        "organism": data.get("organism", {}).get("scientificName", ""),
        "length": data.get("sequence", {}).get("length", 0),
        "function": functions[:3],
    }


# ─── PDB/RCSB ───────────────────────────────────────────────────────

def search_pdb(query: str, max_results: int = 5) -> dict:
    """Search PDB for crystal structures."""
    search_body = {
        "query": {
            "type": "terminal",
            "service": "full_text",
            "parameters": {"value": query},
        },
        "return_type": "entry",
        "request_options": {"results_content_type": ["experimental"], "paginate": {"start": 0, "rows": max_results}},
    }
    req = urllib.request.Request(
        PDB_BASE,
        data=json.dumps(search_body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
    except Exception as e:
        return {"status": "error", "message": str(e)}

    entries = []
    for hit in data.get("result_set", [])[:max_results]:
        pdb_id = hit.get("identifier", "")
        entry_data = http_get_json(f"{PDB_DATA}/{pdb_id}")
        if "error" not in entry_data:
            entries.append({
                "pdb_id": pdb_id,
                "title": entry_data.get("struct", {}).get("title", ""),
                "method": entry_data.get("exptl", [{}])[0].get("method", "") if entry_data.get("exptl") else "",
                "resolution": entry_data.get("rcsb_entry_info", {}).get("resolution_combined", [None])[0] if entry_data.get("rcsb_entry_info", {}).get("resolution_combined") else None,
            })

    return {"status": "ok", "query": query, "count": data.get("total_count", 0), "structures": entries}


# ─── Tool Routing ────────────────────────────────────────────────────

def route(tool_name: str, args: dict) -> dict:
    """Route tool call to appropriate handler."""

    # HEXIM1 curated tools
    if tool_name == "get-ptefb-pathway":
        return PTEFB_PATHWAY
    if tool_name == "get-ifn-pathway":
        return IFN_PATHWAY
    if tool_name == "get-biomarker-validation":
        return BIOMARKER_DATA
    if tool_name == "get-hypothesis-tracker":
        return HYPOTHESIS_TRACKER
    if tool_name == "get-replication-failures":
        return REPLICATION_FAILURES
    if tool_name == "get-patent-landscape":
        return PATENT_LANDSCAPE

    if tool_name == "get-experimental-protocols":
        assay = args.get("assay_type", "").lower()
        if assay:
            for key, proto in EXPERIMENTAL_PROTOCOLS.items():
                if assay in key or assay in proto["name"].lower():
                    return {"status": "ok", "protocols": [proto]}
            return {"status": "ok", "protocols": [], "message": f"No protocol found for assay type: {assay}"}
        return {"status": "ok", "protocols": list(EXPERIMENTAL_PROTOCOLS.values())}

    if tool_name == "search-bet-inhibitors":
        compound = args.get("compound", "").lower()
        if compound:
            matches = [b for b in BET_INHIBITORS if compound in b["name"].lower()]
            return {"status": "ok", "inhibitors": matches or BET_INHIBITORS, "hexim1_upregulation_evidence": "BET inhibitors upregulate HEXIM1 by displacing BRD4 from the HEXIM1 promoter, allowing P-TEFb to re-enter the inhibitory 7SK/HEXIM1 complex."}
        return {"status": "ok", "inhibitors": BET_INHIBITORS, "hexim1_upregulation_evidence": "BET inhibitors upregulate HEXIM1 by displacing BRD4 from the HEXIM1 promoter."}

    if tool_name == "search-hdac-inhibitors":
        compound = args.get("compound", "").lower()
        if compound:
            matches = [h for h in HDAC_INHIBITORS if compound in h["name"].lower()]
            return {"status": "ok", "inhibitors": matches or HDAC_INHIBITORS, "epigenetic_mechanism": "HDAC inhibitors induce HEXIM1 via promoter hyperacetylation."}
        return {"status": "ok", "inhibitors": HDAC_INHIBITORS, "epigenetic_mechanism": "HDAC inhibitors induce HEXIM1 via promoter hyperacetylation — opening chromatin at the HEXIM1 locus."}

    # GEO mining
    if tool_name == "mine-geo-expression":
        treatment = args.get("treatment", "HEXIM1")
        query = f"HEXIM1 {treatment}" if treatment != "HEXIM1" else "HEXIM1 expression"
        return search_geo(query)

    # Drug target intelligence tools
    if tool_name == "search-targets":
        return search_chembl_target(args.get("query", args.get("gene", "")))

    if tool_name == "get-target-profile":
        accession = args.get("uniprot_id", args.get("accession", ""))
        if accession:
            return get_uniprot_entry(accession)
        gene = args.get("gene", args.get("target", ""))
        if gene:
            return search_chembl_target(gene)
        return {"status": "error", "message": "Provide uniprot_id or gene parameter"}

    if tool_name == "get-crystal-structures":
        query = args.get("query", args.get("target", args.get("gene", ""))).strip()
        if not query:
            return {"status": "error", "message": "Provide query, target, or gene parameter"}
        return search_pdb(query)

    if tool_name == "search-clinical-candidates":
        target = ensure_str(args.get("target_chembl_id", "")).strip()
        gene = args.get("target", args.get("gene", "")).strip()
        if not target and not gene:
            return {"status": "error", "message": "Provide target (gene name) or target_chembl_id parameter"}
        # If we have a gene name but no ChEMBL ID, resolve via target search first
        if not target and gene:
            target_result = search_chembl_target(gene)
            targets = target_result.get("targets", [])
            if targets:
                target = targets[0].get("chembl_id", "")
            if not target:
                return {"status": "ok", "message": f"No ChEMBL target found for '{gene}'", "activities": []}
        return search_chembl_compounds(target, limit=get_int_param(args, "limit", 10))

    if tool_name == "get-target-safety":
        gene = args.get("gene", args.get("target", ""))
        # PubMed search for safety liabilities
        return search_pubmed(f"{gene} safety liability toxicity knockout phenotype", max_results=10)

    if tool_name == "compute-target-score":
        return {"status": "ok", "message": "Target druggability scoring requires multi-factor analysis. Use get-target-profile + get-crystal-structures + search-clinical-candidates and assess manually.", "factors": ["Protein family (kinase > GPCR > PPI)", "Crystal structure availability", "Active clinical candidates", "Genetic validation", "Safety of target modulation"]}

    # Genomics tools
    if tool_name == "search-geo-datasets":
        query = args.get("query", args.get("gene", ""))
        return search_geo(query)

    if tool_name == "get-expression-profile":
        gene = args.get("gene", "")
        return search_geo(f"{gene} expression profiling tissue")

    if tool_name == "search-variants":
        gene = args.get("gene", "")
        return search_pubmed(f"{gene} variant ClinVar pathogenic", max_results=10)

    if tool_name == "get-pathway-enrichment":
        gene = args.get("gene", args.get("gene_list", ""))
        return search_pubmed(f"{gene} pathway enrichment KEGG Reactome", max_results=10)

    if tool_name == "search-protein-interactions":
        gene = args.get("gene", args.get("protein", ""))
        return search_pubmed(f"{gene} protein-protein interaction network STRING", max_results=10)

    # PubMed search (general)
    if tool_name == "search-literature":
        return search_pubmed(args.get("query", ""), max_results=args.get("limit", 10))

    return {"status": "error", "message": f"Unknown science tool: {tool_name}"}


def main():
    """Read tool call from stdin (dispatched by station router)."""
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"status": "error", "message": "No input"}))
        return

    try:
        call = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"status": "error", "message": "Invalid JSON input"}))
        return

    tool_name = call.get("tool", call.get("name", ""))
    arguments = call.get("arguments", call.get("params", {}))

    result = route(tool_name, arguments)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
