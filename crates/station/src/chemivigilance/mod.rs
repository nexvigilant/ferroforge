//! Chemivigilance — Rust-native handler for NexVigilant Station.
//!
//! Routes `chemivigilance_nexvigilant_com_*` tool calls to nexcore-chemivigilance,
//! nexcore-molcore, nexcore-qsar, and nexcore-structural-alerts.

use nexcore_chemivigilance::pipeline::{ChemivigilanceConfig, generate_safety_brief};
use nexcore_molcore::arom::detect_aromaticity;
use nexcore_molcore::descriptor::calculate_descriptors;
use nexcore_molcore::fingerprint::{dice, morgan_fingerprint, tanimoto};
use nexcore_molcore::graph::MolGraph;
use nexcore_molcore::ring::find_sssr;
use nexcore_molcore::smiles::parse;
use nexcore_molcore::substruct::{count_matches, has_substructure};
use nexcore_structural_alerts::{AlertLibrary, scan_smiles};
use serde_json::{Value, json};
use tracing::info;

use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("chemivigilance_nexvigilant_com_")?
        .replace('_', "-");

    let result = match bare.as_str() {
        "parse-smiles" => handle_parse_smiles(args),
        "descriptors" => handle_descriptors(args),
        "fingerprint" => handle_fingerprint(args),
        "similarity" => handle_similarity(args),
        "structural-alerts" => handle_structural_alerts(args),
        "predict-toxicity" => handle_predict_toxicity(args),
        "predict-metabolites" => handle_predict_metabolites(args),
        "safety-brief" => handle_safety_brief(args),
        "substructure" => handle_substructure(args),
        "alert-library" => handle_alert_library(args),
        "ring-scan" => handle_ring_scan(args),
        "aromaticity" => handle_aromaticity(args),
        "molecular-formula" => handle_molecular_formula(args),
        _ => return None,
    };

    info!(tool = tool_name, "Handled natively (chemivigilance)");

    Some(ToolCallResult {
        content: vec![ContentBlock::Text {
            text: serde_json::to_string_pretty(&result).unwrap_or_default(),
        }],
        is_error: if result.get("status").and_then(|s| s.as_str()) == Some("error") {
            Some(true)
        } else {
            None
        },
    })
}

fn ok(v: Value) -> Value {
    let mut obj = v;
    if let Some(map) = obj.as_object_mut() {
        map.insert("status".into(), json!("ok"));
    }
    obj
}

fn err(msg: &str) -> Value {
    json!({ "status": "error", "error": msg })
}

fn get_str<'a>(args: &'a Value, key: &str) -> Option<&'a str> {
    args.get(key).and_then(|v| v.as_str())
}

fn parse_mol(smiles: &str) -> Result<MolGraph, Value> {
    let mol = parse(smiles).map_err(|e| err(&format!("SMILES parse failed: {e}")))?;
    Ok(MolGraph::from_molecule(mol))
}

fn handle_parse_smiles(args: &Value) -> Value {
    let smiles = match get_str(args, "smiles") {
        Some(v) => v,
        None => return err("missing required parameter: smiles"),
    };
    let graph = match parse_mol(smiles) {
        Ok(g) => g,
        Err(e) => return e,
    };
    let components = graph.connected_components();

    ok(json!({
        "smiles": smiles,
        "atom_count": graph.atom_count(),
        "bond_count": graph.bond_count(),
        "connected_components": components.len(),
        "valid": true,
    }))
}

fn handle_descriptors(args: &Value) -> Value {
    let smiles = match get_str(args, "smiles") {
        Some(v) => v,
        None => return err("missing required parameter: smiles"),
    };
    let graph = match parse_mol(smiles) {
        Ok(g) => g,
        Err(e) => return e,
    };
    let d = calculate_descriptors(&graph);

    ok(json!({
        "smiles": smiles,
        "molecular_weight": d.molecular_weight,
        "logp": d.logp,
        "tpsa": d.tpsa,
        "hba": d.hba,
        "hbd": d.hbd,
        "rotatable_bonds": d.rotatable_bonds,
        "num_rings": d.num_rings,
        "num_aromatic_rings": d.num_aromatic_rings,
        "heavy_atom_count": d.heavy_atom_count,
        "lipinski_ro5": {
            "mw_ok": d.molecular_weight <= 500.0,
            "logp_ok": d.logp <= 5.0,
            "hba_ok": d.hba <= 10,
            "hbd_ok": d.hbd <= 5,
            "passes": d.molecular_weight <= 500.0 && d.logp <= 5.0
                   && d.hba <= 10 && d.hbd <= 5,
        },
    }))
}

fn handle_fingerprint(args: &Value) -> Value {
    let smiles = match get_str(args, "smiles") {
        Some(v) => v,
        None => return err("missing required parameter: smiles"),
    };
    let graph = match parse_mol(smiles) {
        Ok(g) => g,
        Err(e) => return e,
    };
    let radius = args.get("radius").and_then(|v| v.as_u64()).unwrap_or(2).min(255) as u8;
    let nbits = args.get("nbits").and_then(|v| v.as_u64()).unwrap_or(2048) as usize;
    let fp = morgan_fingerprint(&graph, radius, nbits);
    let set_bits: Vec<usize> = (0..fp.size).filter(|&i| fp.get(i)).take(256).collect();

    ok(json!({
        "smiles": smiles,
        "radius": radius,
        "nbits": nbits,
        "popcount": fp.popcount(),
        "density": fp.popcount() as f64 / nbits.max(1) as f64,
        "set_bits_sample": set_bits,
    }))
}

fn handle_similarity(args: &Value) -> Value {
    let smiles_a = match get_str(args, "smiles_a") {
        Some(v) => v,
        None => return err("missing required parameter: smiles_a"),
    };
    let smiles_b = match get_str(args, "smiles_b") {
        Some(v) => v,
        None => return err("missing required parameter: smiles_b"),
    };
    let ga = match parse_mol(smiles_a) {
        Ok(g) => g,
        Err(e) => return e,
    };
    let gb = match parse_mol(smiles_b) {
        Ok(g) => g,
        Err(e) => return e,
    };
    let fp_a = morgan_fingerprint(&ga, 2, 2048);
    let fp_b = morgan_fingerprint(&gb, 2, 2048);
    let tan = tanimoto(&fp_a, &fp_b);
    let dic = dice(&fp_a, &fp_b);

    ok(json!({
        "smiles_a": smiles_a,
        "smiles_b": smiles_b,
        "tanimoto": tan,
        "dice": dic,
        "interpretation": if tan > 0.85 {
            "High similarity — likely same scaffold"
        } else if tan > 0.5 {
            "Moderate similarity — related scaffolds"
        } else {
            "Low similarity — distinct structures"
        },
    }))
}

fn handle_structural_alerts(args: &Value) -> Value {
    let smiles = match get_str(args, "smiles") {
        Some(v) => v,
        None => return err("missing required parameter: smiles"),
    };
    let library = AlertLibrary::default();
    let alerts = match scan_smiles(smiles, &library) {
        Ok(a) => a,
        Err(e) => return err(&format!("Structural alert scan failed: {e}")),
    };

    let alert_list: Vec<Value> = alerts
        .iter()
        .map(|a| {
            json!({
                "name": a.alert.name,
                "category": format!("{:?}", a.alert.category),
                "description": a.alert.description,
                "match_count": a.match_count,
            })
        })
        .collect();

    ok(json!({
        "smiles": smiles,
        "alert_count": alerts.len(),
        "alerts": alert_list,
        "verdict": if alerts.is_empty() { "CLEAN" } else { "ALERTS_FOUND" },
    }))
}

fn handle_predict_toxicity(args: &Value) -> Value {
    let smiles = match get_str(args, "smiles") {
        Some(v) => v,
        None => return err("missing required parameter: smiles"),
    };
    // scan_smiles to get alert count for QSAR input
    let library = AlertLibrary::default();
    let alert_count = scan_smiles(smiles, &library)
        .map(|a| a.len())
        .unwrap_or(0);

    match nexcore_qsar::predict::predict_from_smiles(smiles, alert_count, 0) {
        Ok(pred) => ok(json!({
            "smiles": smiles,
            "structural_alert_count": alert_count,
            "predictions": pred,
        })),
        Err(e) => err(&format!("QSAR prediction failed: {e}")),
    }
}

fn handle_predict_metabolites(args: &Value) -> Value {
    let smiles = match get_str(args, "smiles") {
        Some(v) => v,
        None => return err("missing required parameter: smiles"),
    };
    match nexcore_metabolite::predict::predict_from_smiles(smiles) {
        Ok(tree) => ok(json!({
            "smiles": smiles,
            "metabolite_tree": format!("{tree:?}"),
        })),
        Err(e) => err(&format!("Metabolite prediction failed: {e}")),
    }
}

fn handle_safety_brief(args: &Value) -> Value {
    let smiles = match get_str(args, "smiles") {
        Some(v) => v,
        None => return err("missing required parameter: smiles"),
    };
    let config = ChemivigilanceConfig::default();
    match generate_safety_brief(smiles, &config) {
        Ok(brief) => ok(json!({
            "smiles": smiles,
            "brief": format!("{brief:?}"),
        })),
        Err(e) => err(&format!("Safety brief generation failed: {e}")),
    }
}

fn handle_substructure(args: &Value) -> Value {
    let smiles = match get_str(args, "smiles") {
        Some(v) => v,
        None => return err("missing required parameter: smiles"),
    };
    let query = match get_str(args, "query") {
        Some(v) => v,
        None => return err("missing required parameter: query"),
    };
    let graph = match parse_mol(smiles) {
        Ok(g) => g,
        Err(e) => return e,
    };
    let query_graph = match parse_mol(query) {
        Ok(g) => g,
        Err(e) => return e,
    };
    let found = has_substructure(&graph, &query_graph);
    let count = count_matches(&graph, &query_graph);

    ok(json!({
        "smiles": smiles,
        "query": query,
        "found": found,
        "match_count": count,
    }))
}

fn handle_alert_library(_args: &Value) -> Value {
    let lib = AlertLibrary::default();
    let alerts: Vec<Value> = lib
        .alerts()
        .iter()
        .map(|a| {
            json!({
                "name": a.name,
                "category": format!("{:?}", a.category),
                "description": a.description,
            })
        })
        .collect();

    ok(json!({
        "alert_count": alerts.len(),
        "alerts": alerts,
    }))
}

fn handle_ring_scan(args: &Value) -> Value {
    let smiles = match get_str(args, "smiles") {
        Some(v) => v,
        None => return err("missing required parameter: smiles"),
    };
    let graph = match parse_mol(smiles) {
        Ok(g) => g,
        Err(e) => return e,
    };
    let rings = find_sssr(&graph);

    ok(json!({
        "smiles": smiles,
        "ring_count": rings.len(),
        "rings": rings.iter().map(|r| json!({
            "size": r.len(),
            "atoms": r,
        })).collect::<Vec<_>>(),
    }))
}

fn handle_aromaticity(args: &Value) -> Value {
    let smiles = match get_str(args, "smiles") {
        Some(v) => v,
        None => return err("missing required parameter: smiles"),
    };
    let graph = match parse_mol(smiles) {
        Ok(g) => g,
        Err(e) => return e,
    };
    let aromatic_rings = detect_aromaticity(&graph);

    ok(json!({
        "smiles": smiles,
        "aromatic_ring_count": aromatic_rings.len(),
        "aromatic_rings": aromatic_rings.iter().map(|r| json!({
            "atoms": r.atoms,
            "pi_electrons": r.pi_electrons,
        })).collect::<Vec<_>>(),
    }))
}

fn handle_molecular_formula(args: &Value) -> Value {
    let smiles = match get_str(args, "smiles") {
        Some(v) => v,
        None => return err("missing required parameter: smiles"),
    };
    let graph = match parse_mol(smiles) {
        Ok(g) => g,
        Err(e) => return e,
    };
    let d = calculate_descriptors(&graph);

    ok(json!({
        "smiles": smiles,
        "molecular_weight": d.molecular_weight,
        "heavy_atom_count": d.heavy_atom_count,
    }))
}
