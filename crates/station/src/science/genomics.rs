//! Genomics & Expression Mining — NCBI GEO and PubMed handlers.

use serde_json::{json, Value};
use tracing::info;

use super::http;

const NCBI_BASE: &str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils";

/// Route a genomics tool call.
pub fn handle(tool_name: &str, args: &Value) -> Option<Value> {
    match tool_name {
        "mine-geo-expression" => Some(mine_geo(args)),
        "search-geo-datasets" => Some(search_geo(args)),
        "get-expression-profile" => Some(expression_profile(args)),
        "search-variants" => Some(search_variants(args)),
        "get-pathway-enrichment" => Some(pathway_enrichment(args)),
        "search-protein-interactions" => Some(protein_interactions(args)),
        "search-literature" | "search-articles" => Some(search_literature(args)),
        _ => None,
    }
}

/// Public entry point for PubMed search — used by targets::get_target_safety.
pub fn pubmed_search(query: &str, max_results: u64) -> Value {
    info!(query, "PubMed search");
    let encoded = urlencoding(query);
    let url = format!(
        "{NCBI_BASE}/esearch.fcgi?db=pubmed&term={encoded}&retmax={max_results}&retmode=json&sort=relevance"
    );
    let data = http::get_json(&url);

    if data.get("error").is_some() {
        return json!({"status": "error", "message": data["error"]});
    }

    let ids: Vec<String> = data.pointer("/esearchresult/idlist")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|v| v.as_str().map(String::from)).take(10).collect())
        .unwrap_or_default();

    if ids.is_empty() {
        return json!({"status": "ok", "query": query, "count": 0, "articles": []});
    }

    let count = data.pointer("/esearchresult/count")
        .and_then(|v| v.as_str())
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(0);

    // Fetch summaries
    let id_str = ids.join(",");
    let summary_url = format!("{NCBI_BASE}/esummary.fcgi?db=pubmed&id={id_str}&retmode=json");
    let summaries = http::get_json(&summary_url);

    let articles: Vec<Value> = ids.iter().filter_map(|pid| {
        let rec = summaries.pointer(&format!("/result/{pid}"))?;
        let authors: Vec<&str> = rec.get("authors")
            .and_then(|a| a.as_array())
            .map(|arr| arr.iter()
                .filter_map(|a| a.get("name").and_then(|n| n.as_str()))
                .take(3)
                .collect())
            .unwrap_or_default();

        Some(json!({
            "pmid": pid,
            "title": rec.get("title").and_then(|t| t.as_str()).unwrap_or(""),
            "authors": authors.join(", "),
            "journal": rec.get("source").and_then(|s| s.as_str()).unwrap_or(""),
            "year": rec.get("pubdate").and_then(|d| d.as_str()).map(|s| &s[..4.min(s.len())]).unwrap_or(""),
        }))
    }).collect();

    json!({"status": "ok", "query": query, "count": count, "articles": articles})
}

fn mine_geo(args: &Value) -> Value {
    let treatment = args.get("treatment").and_then(|v| v.as_str()).unwrap_or("HEXIM1");
    let query = if treatment == "HEXIM1" {
        "HEXIM1 expression".to_string()
    } else {
        format!("HEXIM1 {treatment}")
    };
    geo_search(&query)
}

fn search_geo(args: &Value) -> Value {
    let query = args.get("query")
        .or_else(|| args.get("gene"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if query.is_empty() {
        return json!({"status": "error", "message": "Provide 'query' parameter"});
    }
    geo_search(query)
}

fn expression_profile(args: &Value) -> Value {
    let gene = args.get("gene").and_then(|v| v.as_str()).unwrap_or("");
    if gene.is_empty() {
        return json!({"status": "error", "message": "Provide 'gene' parameter"});
    }
    geo_search(&format!("{gene} expression profiling tissue"))
}

fn search_variants(args: &Value) -> Value {
    let gene = args.get("gene").and_then(|v| v.as_str()).unwrap_or("");
    if gene.is_empty() {
        return json!({"status": "error", "message": "Provide 'gene' parameter"});
    }
    pubmed_search(&format!("{gene} variant ClinVar pathogenic"), 10)
}

fn pathway_enrichment(args: &Value) -> Value {
    let gene = args.get("gene")
        .or_else(|| args.get("gene_list"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if gene.is_empty() {
        return json!({"status": "error", "message": "Provide 'gene' parameter"});
    }
    pubmed_search(&format!("{gene} pathway enrichment KEGG Reactome"), 10)
}

fn protein_interactions(args: &Value) -> Value {
    let gene = args.get("gene")
        .or_else(|| args.get("protein"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if gene.is_empty() {
        return json!({"status": "error", "message": "Provide 'gene' parameter"});
    }
    pubmed_search(&format!("{gene} protein-protein interaction STRING BioGRID"), 10)
}

fn search_literature(args: &Value) -> Value {
    let query = args.get("query").and_then(|v| v.as_str()).unwrap_or("");
    let limit = args.get("limit").and_then(|v| v.as_u64()).unwrap_or(10);
    if query.is_empty() {
        return json!({"status": "error", "message": "Provide 'query' parameter"});
    }
    pubmed_search(query, limit)
}

fn geo_search(query: &str) -> Value {
    info!(query, "GEO search");
    let encoded = urlencoding(query);
    let url = format!("{NCBI_BASE}/esearch.fcgi?db=gds&term={encoded}&retmax=10&retmode=json");
    let data = http::get_json(&url);

    if data.get("error").is_some() {
        return json!({"status": "error", "message": data["error"]});
    }

    let ids: Vec<String> = data.pointer("/esearchresult/idlist")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|v| v.as_str().map(String::from)).take(10).collect())
        .unwrap_or_default();

    if ids.is_empty() {
        return json!({"status": "ok", "query": query, "count": 0, "datasets": []});
    }

    let count = data.pointer("/esearchresult/count")
        .and_then(|v| v.as_str())
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(0);

    let id_str = ids.join(",");
    let summary_url = format!("{NCBI_BASE}/esummary.fcgi?db=gds&id={id_str}&retmode=json");
    let summaries = http::get_json(&summary_url);

    let datasets: Vec<Value> = ids.iter().filter_map(|gid| {
        let rec = summaries.pointer(&format!("/result/{gid}"))?;
        Some(json!({
            "gds_id": gid,
            "accession": rec.get("accession").and_then(|a| a.as_str()).unwrap_or(""),
            "title": rec.get("title").and_then(|t| t.as_str()).unwrap_or(""),
            "summary": rec.get("summary").and_then(|s| s.as_str()).map(|s| &s[..200.min(s.len())]).unwrap_or(""),
            "platform": rec.get("gpl").and_then(|p| p.as_str()).unwrap_or(""),
            "samples": rec.get("n_samples").and_then(|n| n.as_u64()).unwrap_or(0),
        }))
    }).collect();

    json!({"status": "ok", "query": query, "count": count, "datasets": datasets})
}

fn urlencoding(s: &str) -> String {
    s.replace(' ', "%20").replace('&', "%26").replace('=', "%3D")
}
