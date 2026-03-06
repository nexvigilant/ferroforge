//! HEXIM1 Research — curated knowledge compiled into the binary.
//!
//! PTEFb pathway, BET/HDAC inhibitors, biomarker validation,
//! experimental protocols, hypothesis tracker, patent landscape.

use serde_json::{json, Value};

/// Route an HEXIM1 tool call to the appropriate curated dataset.
pub fn handle(tool_name: &str, args: &Value) -> Option<Value> {
    match tool_name {
        "get-ptefb-pathway" => Some(ptefb_pathway()),
        "get-ifn-pathway" => Some(ifn_pathway()),
        "get-biomarker-validation" => Some(biomarker_data()),
        "get-hypothesis-tracker" => Some(hypothesis_tracker()),
        "get-replication-failures" => Some(replication_failures()),
        "get-patent-landscape" => Some(patent_landscape()),
        "get-experimental-protocols" => Some(experimental_protocols(args)),
        "search-bet-inhibitors" => Some(bet_inhibitors(args)),
        "search-hdac-inhibitors" => Some(hdac_inhibitors(args)),
        _ => None,
    }
}

fn ptefb_pathway() -> Value {
    json!({
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
            "RNA Pol II (CTD Ser2 substrate)"
        ],
        "interactions": [
            "HEXIM1 + 7SK snRNA → sequesters P-TEFb (CDK9/CycT1) in inactive complex",
            "BRD4 competes with HEXIM1 for P-TEFb binding → releases active CDK9",
            "Active CDK9 phosphorylates RNA Pol II CTD Ser2 → transcriptional elongation",
            "BET inhibitors (JQ1) displace BRD4 → P-TEFb returns to HEXIM1/7SK complex",
            "HEXIM1 upregulation → increased P-TEFb sequestration → reduced oncogene transcription"
        ],
        "mechanism_summary": "HEXIM1 is the endogenous brake on transcriptional elongation. It sequesters the P-TEFb kinase (CDK9/CyclinT1) via the 7SK snRNP complex, preventing phosphorylation of RNA Pol II CTD. BET inhibitors restore this brake — displacing BRD4 causes P-TEFb to return to the HEXIM1/7SK complex, downregulating MYC and other oncogenes.",
        "therapeutic_relevance": "HEXIM1 upregulation is a pharmacodynamic biomarker for BET inhibitor efficacy. Loss of HEXIM1 correlates with aggressive cancers.",
        "key_references": [
            "Yik JH et al. (2003) Mol Cell 12(4):971-82",
            "Nguyen VT et al. (2001) J Biol Chem 276(8):5932-9",
            "Filippakopoulos P et al. (2010) Nature 468:1067-73"
        ]
    })
}

fn ifn_pathway() -> Value {
    json!({
        "status": "ok",
        "pathway_name": "HEXIM1 in Interferon Signaling",
        "pathway_nodes": [
            "Type I IFN (IFN-alpha, IFN-beta)",
            "IFNAR1/IFNAR2 receptor",
            "JAK1/TYK2", "STAT1/STAT2", "IRF9 (ISGF3)",
            "ISGs", "HEXIM1", "CDK9/CyclinT1 (P-TEFb)"
        ],
        "hexim1_role": "HEXIM1 modulates IFN-stimulated gene transcription by controlling P-TEFb availability. High HEXIM1 dampens IFN response; low HEXIM1 amplifies it. Positions HEXIM1 as a rheostat for innate immunity.",
        "antiviral_connection": "HIV-1 Tat protein competes with HEXIM1 for P-TEFb binding, hijacking host transcriptional machinery. HEXIM1 overexpression inhibits HIV-1 replication."
    })
}

fn biomarker_data() -> Value {
    json!({
        "status": "ok",
        "gene": "HEXIM1", "uniprot": "O94992",
        "tissues": [
            {"tissue": "Heart", "expression_tpm": 45.2, "specificity": "Medium"},
            {"tissue": "Liver", "expression_tpm": 32.1, "specificity": "Low"},
            {"tissue": "Brain", "expression_tpm": 28.7, "specificity": "Low"},
            {"tissue": "Bone Marrow", "expression_tpm": 18.4, "specificity": "Low"},
            {"tissue": "Testis", "expression_tpm": 62.3, "specificity": "High"}
        ],
        "disease_associations": [
            "AML — low HEXIM1 correlates with poor prognosis",
            "Breast Cancer — HEXIM1 loss in ER+ tumors",
            "HIV/AIDS — HEXIM1 competes with Tat for P-TEFb",
            "Cardiac Hypertrophy — HEXIM1 modulates cardiac gene program",
            "Myelofibrosis — BET inhibitor (pelabresib) restores HEXIM1"
        ],
        "validation_status": "Exploratory biomarker. HEXIM1 mRNA validated as PD readout for BET inhibitor activity in Phase I (CPI-0610). Not FDA-qualified. Assay: RT-qPCR (RefSeq NM_006460).",
        "source": "GTEx v8, literature review (2024)"
    })
}

fn hypothesis_tracker() -> Value {
    json!({
        "status": "ok",
        "active_count": 4,
        "hypotheses": [
            {"id": "H1", "statement": "HEXIM1 upregulation is necessary for BET inhibitor anti-tumor efficacy", "confidence": 0.72,
             "evidence_for": ["JQ1 rescue experiments", "HEXIM1-KO abolishes JQ1 effect in MV4-11"],
             "evidence_against": ["Some BETi effects independent of P-TEFb"],
             "next_step": "CRISPR HEXIM1-KO + BETi dose-response in 3 AML lines"},
            {"id": "H2", "statement": "BET + HDAC inhibitor combination produces synergistic HEXIM1 induction", "confidence": 0.65,
             "evidence_for": ["JQ1+SAHA synergy in MOLM-13 (CI<0.5)"],
             "evidence_against": ["Toxicity limits clinical combinations"],
             "next_step": "Isobologram analysis: 4 BETi x 3 HDACi matrix"},
            {"id": "H3", "statement": "HEXIM1 serves as patient stratification biomarker for BETi trials", "confidence": 0.58,
             "evidence_for": ["CPI-0610 Phase I PD data"],
             "evidence_against": ["Small sample sizes"],
             "next_step": "Retrospective analysis of CPI-0610 Phase III MF data"},
            {"id": "H4", "statement": "HEXIM1-mimetic peptides can directly inhibit P-TEFb", "confidence": 0.35,
             "evidence_for": ["ARM domain structure solved", "Peptide hits in FP assay"],
             "evidence_against": ["Cell permeability unknown"],
             "next_step": "Stapled peptide library screen with cellular uptake assay"}
        ]
    })
}

fn replication_failures() -> Value {
    json!({
        "status": "ok",
        "failures": [
            {"experiment": "HEXIM1 overexpression alone as anti-tumor strategy",
             "expected": "Tumor growth inhibition", "observed": "Minimal effect without BETi co-treatment",
             "lesson": "HEXIM1 needs P-TEFb available (not already sequestered) to exert effect"},
            {"experiment": "7SK snRNA knockdown to release P-TEFb",
             "expected": "Phenocopy of BETi", "observed": "Cell death from transcriptional dysregulation",
             "lesson": "7SK/HEXIM1 complex is essential for viability"},
            {"experiment": "HEXIM1 as monotherapy biomarker in solid tumors",
             "expected": "HEXIM1 predicts BETi response", "observed": "No correlation in pancreatic cancer",
             "lesson": "Biomarker utility may be lineage-specific (hematologic > solid)"}
        ],
        "lessons_learned": [
            "HEXIM1 biology is context-dependent — AML ≠ solid tumors",
            "7SK/HEXIM1/P-TEFb equilibrium is tightly buffered — non-linear perturbations",
            "Always include HEXIM1-null controls when claiming BETi effects are HEXIM1-dependent"
        ]
    })
}

fn patent_landscape() -> Value {
    json!({
        "status": "ok",
        "white_space": [
            "Direct HEXIM1 activators (small molecules upregulating HEXIM1 independently of BET/HDAC)",
            "HEXIM1-mimetic stapled peptides targeting the P-TEFb interface",
            "Combination biomarker panels: HEXIM1 + MYC + BRD4 occupancy",
            "HEXIM1-based gene therapy for HIV reservoir elimination"
        ],
        "strategic_opportunities": [
            "Composition-of-matter on HEXIM1-mimetic peptides",
            "Method patent on HEXIM1/7SK ratio as P-TEFb activation diagnostic",
            "Biomarker method claims for HEXIM1 IHC scoring in myelofibrosis"
        ]
    })
}

fn experimental_protocols(args: &Value) -> Value {
    let assay = args.get("assay_type").and_then(|v| v.as_str()).unwrap_or("");
    let all = vec![
        json!({"name": "ChIP-seq for HEXIM1/7SK occupancy", "cell_lines": ["MV4-11","MOLM-13","K562"],
               "antibody": "Bethyl A303-113A", "crosslink": "1% formaldehyde 10min RT",
               "sonication": "Covaris E220, 200-500bp", "reads": "30M PE150 min"}),
        json!({"name": "RT-qPCR for HEXIM1 mRNA",
               "primer_fwd": "5'-AGAGCCTGAGCAGCGAGAAG-3'", "primer_rev": "5'-CTCCTTCATGGCCGTCTCCT-3'",
               "amplicon_bp": 142, "reference_genes": ["GAPDH","ACTB","18S rRNA"]}),
        json!({"name": "Western blot for HEXIM1 protein", "antibody": "Bethyl A303-113A (rabbit, 1:2000)",
               "lysate": "RIPA 30ug", "gel": "10% SDS-PAGE", "expected_band": "~41 kDa"}),
    ];

    let filtered: Vec<Value> = if assay.is_empty() {
        all
    } else {
        let q = assay.to_lowercase();
        all.into_iter()
            .filter(|p| p["name"].as_str().map_or(false, |n| n.to_lowercase().contains(&q)))
            .collect()
    };

    json!({"status": "ok", "protocols": filtered})
}

fn bet_inhibitors(args: &Value) -> Value {
    let compound = args.get("compound").and_then(|v| v.as_str()).unwrap_or("").to_lowercase();
    let all = vec![
        json!({"name":"JQ1","target":"BRD2/3/4","selectivity":"Pan-BET","kd_nM":50,
               "hexim1_effect":"2-5x upregulation in AML (24h)","clinical":"Tool compound"}),
        json!({"name":"I-BET151","target":"BRD2/3/4","selectivity":"Pan-BET","kd_nM":36,
               "hexim1_effect":"3-8x upregulation in MLL-fusion leukemia","clinical":"Preclinical"}),
        json!({"name":"OTX015 (Birabresib)","target":"BRD2/3/4","selectivity":"Pan-BET","kd_nM":92,
               "hexim1_effect":"Moderate upregulation in DLBCL","clinical":"Phase I (discontinued)"}),
        json!({"name":"ABBV-075 (Mivebresib)","target":"BRD2/3/4","selectivity":"Pan-BET","kd_nM":2,
               "hexim1_effect":"Potent HEXIM1 induction","clinical":"Phase I (AbbVie)"}),
        json!({"name":"CPI-0610 (Pelabresib)","target":"BRD2/3/4","selectivity":"Pan-BET, BRD4 pref","kd_nM":25,
               "hexim1_effect":"Upregulation in myelofibrosis","clinical":"Phase III (myelofibrosis)"}),
    ];

    let filtered: Vec<Value> = if compound.is_empty() {
        all
    } else {
        all.into_iter()
            .filter(|b| b["name"].as_str().map_or(false, |n| n.to_lowercase().contains(&compound)))
            .collect()
    };

    json!({
        "status": "ok",
        "inhibitors": if filtered.is_empty() { vec![json!({"note": "No match, showing all"})] } else { filtered },
        "hexim1_upregulation_evidence": "BET inhibitors upregulate HEXIM1 by displacing BRD4 from the HEXIM1 promoter, restoring P-TEFb to the inhibitory 7SK/HEXIM1 complex."
    })
}

fn hdac_inhibitors(args: &Value) -> Value {
    let compound = args.get("compound").and_then(|v| v.as_str()).unwrap_or("").to_lowercase();
    let all = vec![
        json!({"name":"Vorinostat (SAHA)","target":"Class I/II","ic50_nM":10,
               "hexim1_effect":"Promoter hyperacetylation → HEXIM1 induction","clinical":"FDA approved (CTCL, 2006)"}),
        json!({"name":"Panobinostat (LBH589)","target":"Class I/II/IV","ic50_nM":5,
               "hexim1_effect":"Strong HEXIM1 induction in MM","clinical":"FDA approved (MM, 2015)"}),
        json!({"name":"Romidepsin (FK228)","target":"HDAC1/2","ic50_nM":36,
               "hexim1_effect":"Moderate HEXIM1 upregulation","clinical":"FDA approved (CTCL/PTCL, 2009)"}),
        json!({"name":"Entinostat (MS-275)","target":"HDAC1/3","ic50_nM":240,
               "hexim1_effect":"HEXIM1 induction in breast cancer models","clinical":"Phase III (breast cancer)"}),
    ];

    let filtered: Vec<Value> = if compound.is_empty() {
        all
    } else {
        all.into_iter()
            .filter(|h| h["name"].as_str().map_or(false, |n| n.to_lowercase().contains(&compound)))
            .collect()
    };

    json!({
        "status": "ok",
        "inhibitors": filtered,
        "epigenetic_mechanism": "HDAC inhibitors induce HEXIM1 via promoter hyperacetylation — opening chromatin at the HEXIM1 locus."
    })
}
