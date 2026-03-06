//! Drug Target Intelligence — live API handlers for ChEMBL, UniProt, PDB.

use serde_json::{json, Value};
use tracing::info;

use super::http;

const CHEMBL_BASE: &str = "https://www.ebi.ac.uk/chembl/api/data";
const UNIPROT_BASE: &str = "https://rest.uniprot.org/uniprotkb";
const PDB_SEARCH: &str = "https://search.rcsb.org/rcsbsearch/v2/query";
const PDB_DATA: &str = "https://data.rcsb.org/rest/v1/core/entry";

/// Route a drug target tool call.
pub fn handle(tool_name: &str, args: &Value) -> Option<Value> {
    match tool_name {
        "search-targets" => Some(search_targets(args)),
        "get-target-profile" => Some(get_target_profile(args)),
        "get-crystal-structures" => Some(get_crystal_structures(args)),
        "search-clinical-candidates" => Some(search_clinical_candidates(args)),
        "get-target-safety" => Some(get_target_safety(args)),
        "compute-target-score" => Some(compute_target_score()),
        _ => None,
    }
}

fn search_targets(args: &Value) -> Value {
    let query = args.get("query")
        .or_else(|| args.get("gene"))
        .and_then(|v| v.as_str())
        .unwrap_or("");

    if query.is_empty() {
        return json!({"status": "error", "message": "Provide 'query' parameter"});
    }

    info!(query, "ChEMBL target search");
    let url = format!("{CHEMBL_BASE}/target/search.json?q={}&limit=5&format=json",
        urlencoding(query));
    let data = http::get_json(&url);

    if data.get("error").is_some() {
        return json!({"status": "error", "message": data["error"]});
    }

    let targets: Vec<Value> = data.get("targets")
        .and_then(|t| t.as_array())
        .map(|arr| arr.iter().take(5).map(|t| json!({
            "chembl_id": t["target_chembl_id"],
            "pref_name": t["pref_name"],
            "organism": t["organism"],
            "target_type": t["target_type"],
        })).collect())
        .unwrap_or_default();

    json!({"status": "ok", "query": query, "targets": targets})
}

fn get_target_profile(args: &Value) -> Value {
    let accession = args.get("uniprot_id")
        .or_else(|| args.get("accession"))
        .and_then(|v| v.as_str())
        .unwrap_or("");

    if accession.is_empty() {
        // Fall back to gene search via ChEMBL
        let gene = args.get("gene")
            .or_else(|| args.get("target"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if gene.is_empty() {
            return json!({"status": "error", "message": "Provide uniprot_id or gene"});
        }
        return search_targets(&json!({"query": gene}));
    }

    info!(accession, "UniProt lookup");
    let url = format!("{UNIPROT_BASE}/{accession}.json");
    let data = http::get_json(&url);

    if data.get("error").is_some() {
        return json!({"status": "error", "message": data["error"]});
    }

    let genes: Vec<String> = data.get("genes")
        .and_then(|g| g.as_array())
        .map(|arr| arr.iter()
            .filter_map(|g| g.get("geneName").and_then(|n| n.get("value")).and_then(|v| v.as_str()))
            .map(String::from)
            .collect())
        .unwrap_or_default();

    let functions: Vec<String> = data.get("comments")
        .and_then(|c| c.as_array())
        .map(|arr| arr.iter()
            .filter(|c| c.get("commentType").and_then(|t| t.as_str()) == Some("FUNCTION"))
            .flat_map(|c| c.get("texts").and_then(|t| t.as_array()).into_iter().flatten())
            .filter_map(|t| t.get("value").and_then(|v| v.as_str()).map(String::from))
            .take(3)
            .collect())
        .unwrap_or_default();

    let protein_name = data.pointer("/proteinDescription/recommendedName/fullName/value")
        .and_then(|v| v.as_str())
        .unwrap_or("Unknown");

    json!({
        "status": "ok",
        "accession": accession,
        "protein_name": protein_name,
        "gene_names": genes,
        "organism": data.pointer("/organism/scientificName").and_then(|v| v.as_str()).unwrap_or(""),
        "length": data.pointer("/sequence/length").and_then(|v| v.as_u64()).unwrap_or(0),
        "function": functions,
    })
}

fn get_crystal_structures(args: &Value) -> Value {
    let query = args.get("query")
        .or_else(|| args.get("target"))
        .or_else(|| args.get("gene"))
        .and_then(|v| v.as_str())
        .unwrap_or("");

    if query.is_empty() {
        return json!({"status": "error", "message": "Provide 'query' parameter"});
    }

    info!(query, "PDB structure search");
    let search_body = json!({
        "query": {
            "type": "terminal",
            "service": "full_text",
            "parameters": {"value": query}
        },
        "return_type": "entry",
        "request_options": {
            "results_content_type": ["experimental"],
            "paginate": {"start": 0, "rows": 5}
        }
    });

    let data = http::post_json(PDB_SEARCH, &search_body);

    if data.get("error").is_some() {
        return json!({"status": "error", "message": data["error"]});
    }

    let entries: Vec<Value> = data.get("result_set")
        .and_then(|r| r.as_array())
        .map(|arr| arr.iter().take(5).filter_map(|hit| {
            let pdb_id = hit.get("identifier")?.as_str()?;
            let entry = http::get_json(&format!("{PDB_DATA}/{pdb_id}"));
            if entry.get("error").is_some() { return None; }

            let resolution = entry.pointer("/rcsb_entry_info/resolution_combined")
                .and_then(|r| r.as_array())
                .and_then(|a| a.first())
                .and_then(|v| v.as_f64());

            let method = entry.get("exptl")
                .and_then(|e| e.as_array())
                .and_then(|a| a.first())
                .and_then(|m| m.get("method"))
                .and_then(|v| v.as_str())
                .unwrap_or("");

            Some(json!({
                "pdb_id": pdb_id,
                "title": entry.pointer("/struct/title").and_then(|v| v.as_str()).unwrap_or(""),
                "method": method,
                "resolution_angstrom": resolution,
            }))
        }).collect())
        .unwrap_or_default();

    json!({
        "status": "ok",
        "query": query,
        "count": data.get("total_count").and_then(|v| v.as_u64()).unwrap_or(0),
        "structures": entries,
    })
}

fn search_clinical_candidates(args: &Value) -> Value {
    let target = args.get("target_chembl_id")
        .or_else(|| args.get("target"))
        .and_then(|v| v.as_str())
        .unwrap_or("");

    if target.is_empty() {
        return json!({"status": "error", "message": "Provide target_chembl_id"});
    }

    let limit = args.get("limit").and_then(|v| v.as_u64()).unwrap_or(10);

    info!(target, "ChEMBL activity search");
    let url = format!("{CHEMBL_BASE}/activity.json?target_chembl_id={target}&limit={limit}&format=json");
    let data = http::get_json(&url);

    if data.get("error").is_some() {
        return json!({"status": "error", "message": data["error"]});
    }

    let activities: Vec<Value> = data.get("activities")
        .and_then(|a| a.as_array())
        .map(|arr| arr.iter().take(limit as usize).map(|a| json!({
            "molecule_chembl_id": a["molecule_chembl_id"],
            "molecule_name": a["molecule_pref_name"],
            "activity_type": a["standard_type"],
            "value": a["standard_value"],
            "units": a["standard_units"],
            "assay_type": a["assay_type"],
        })).collect())
        .unwrap_or_default();

    json!({"status": "ok", "target": target, "activities": activities})
}

fn get_target_safety(args: &Value) -> Value {
    let gene = args.get("gene")
        .or_else(|| args.get("target"))
        .and_then(|v| v.as_str())
        .unwrap_or("");

    if gene.is_empty() {
        return json!({"status": "error", "message": "Provide 'gene' parameter"});
    }

    // Use PubMed E-utilities for safety literature
    let query = format!("{gene} safety liability toxicity knockout phenotype");
    super::genomics::pubmed_search(&query, 10)
}

fn compute_target_score() -> Value {
    json!({
        "status": "ok",
        "message": "Target druggability scoring — assess these factors:",
        "factors": [
            "1. Protein family (kinase=high, GPCR=high, PPI=low)",
            "2. Crystal structure availability (PDB entries)",
            "3. Active clinical candidates (ChEMBL Phase II+)",
            "4. Genetic validation (CRISPR KO phenotype, GWAS)",
            "5. Safety of target modulation (essential gene?)",
            "6. Tissue expression selectivity (GTEx)"
        ],
        "workflow": "search-targets → get-target-profile → get-crystal-structures → search-clinical-candidates → get-target-safety"
    })
}

/// Minimal URL encoding for query parameters.
fn urlencoding(s: &str) -> String {
    s.replace(' ', "%20").replace('&', "%26").replace('=', "%3D")
}
