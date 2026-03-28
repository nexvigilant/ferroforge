//! DNA Computing — quaternary encoding, codon translation, sequence alignment.
//! Routes `dna_nexvigilant_com_*`. Delegates to `nexcore-dna`.

use nexcore_dna::{
    types::{Strand, Codon, Nucleotide, AminoAcid},
    codon_table::CodonTable,
    alignment::SequenceAligner,
    asm,
    cortex::{evolve, EvolutionConfig},
};
use serde_json::{Value, json};
use tracing::info;
use crate::protocol::{ContentBlock, ToolCallResult};

pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name.strip_prefix("dna_nexvigilant_com_")?.replace('_', "-");
    let result = match bare.as_str() {
        "translate-codon" => handle_translate_codon(args),
        "codon-degeneracy" => handle_codon_degeneracy(args),
        "align-sequences" => handle_align_sequences(args),
        "assemble" => handle_assemble(args),
        "evolve" => handle_evolve(args),
        "codon-table" => handle_codon_table(),
        _ => return None,
    };
    info!(tool = tool_name, "Handled natively (dna)");
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
    let mut o = v;
    if let Some(m) = o.as_object_mut() { m.insert("status".into(), json!("ok")); }
    o
}
fn err(msg: &str) -> Value { json!({ "status": "error", "error": msg }) }

fn parse_codon(s: &str) -> Option<Codon> {
    let chars: Vec<char> = s.to_uppercase().chars().collect();
    if chars.len() != 3 { return None; }
    let a = Nucleotide::from_char(chars[0]).ok()?;
    let b = Nucleotide::from_char(chars[1]).ok()?;
    let c = Nucleotide::from_char(chars[2]).ok()?;
    Some(Codon(a, b, c))
}

fn handle_translate_codon(args: &Value) -> Value {
    let codon_str = match args.get("codon").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing: codon"),
    };
    let codon = match parse_codon(codon_str) {
        Some(c) => c,
        None => return err("codon must be 3 nucleotides (A, T, G, C)"),
    };
    let table = CodonTable::standard();
    let aa = table.translate(&codon);
    let is_stop = matches!(aa, AminoAcid::Stop);
    let is_start = codon_str.to_uppercase() == "ATG";

    ok(json!({
        "codon": codon_str.to_uppercase(),
        "amino_acid": format!("{aa:?}"),
        "is_start": is_start,
        "is_stop": is_stop,
    }))
}

fn handle_codon_degeneracy(args: &Value) -> Value {
    let aa_str = match args.get("amino_acid").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing: amino_acid"),
    };

    // Try to parse amino acid from name or single letter
    let aa = match aa_str.to_uppercase().as_str() {
        "M" | "MET" | "METHIONINE" => AminoAcid::Met,
        "L" | "LEU" | "LEUCINE" => AminoAcid::Leu,
        "S" | "SER" | "SERINE" => AminoAcid::Ser,
        "R" | "ARG" | "ARGININE" => AminoAcid::Arg,
        "A" | "ALA" | "ALANINE" => AminoAcid::Ala,
        "G" | "GLY" | "GLYCINE" => AminoAcid::Gly,
        "P" | "PRO" | "PROLINE" => AminoAcid::Pro,
        "T" | "THR" | "THREONINE" => AminoAcid::Thr,
        "V" | "VAL" | "VALINE" => AminoAcid::Val,
        "I" | "ILE" | "ISOLEUCINE" => AminoAcid::Ile,
        "F" | "PHE" | "PHENYLALANINE" => AminoAcid::Phe,
        "Y" | "TYR" | "TYROSINE" => AminoAcid::Tyr,
        "C" | "CYS" | "CYSTEINE" => AminoAcid::Cys,
        "H" | "HIS" | "HISTIDINE" => AminoAcid::His,
        "Q" | "GLN" | "GLUTAMINE" => AminoAcid::Gln,
        "N" | "ASN" | "ASPARAGINE" => AminoAcid::Asn,
        "K" | "LYS" | "LYSINE" => AminoAcid::Lys,
        "D" | "ASP" | "ASPARTATE" | "ASPARTIC ACID" => AminoAcid::Asp,
        "E" | "GLU" | "GLUTAMATE" | "GLUTAMIC ACID" => AminoAcid::Glu,
        "W" | "TRP" | "TRYPTOPHAN" => AminoAcid::Trp,
        "*" | "STOP" | "TER" => AminoAcid::Stop,
        _ => return err(&format!("Unknown amino acid: {aa_str}")),
    };

    let table = CodonTable::standard();
    let deg = table.degeneracy(aa);
    let codons: Vec<String> = table.codons_for(aa).iter().map(|c| format!("{}{}{}", c.0, c.1, c.2)).collect();

    ok(json!({
        "amino_acid": format!("{aa:?}"),
        "degeneracy": deg,
        "codons": codons,
    }))
}

fn handle_align_sequences(args: &Value) -> Value {
    let query_str = match args.get("query").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing: query"),
    };
    let target_str = match args.get("target").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing: target"),
    };
    let method = args.get("method").and_then(|v| v.as_str()).unwrap_or("local");

    let query = match Strand::parse(query_str) {
        Ok(s) => s,
        Err(e) => return err(&format!("Invalid query sequence: {e}")),
    };
    let target = match Strand::parse(target_str) {
        Ok(s) => s,
        Err(e) => return err(&format!("Invalid target sequence: {e}")),
    };

    let aligner = SequenceAligner {
        match_score: args.get("match_score").and_then(|v| v.as_i64()).unwrap_or(2) as i32,
        mismatch_score: args.get("mismatch_score").and_then(|v| v.as_i64()).unwrap_or(-1) as i32,
        gap_penalty: args.get("gap_penalty").and_then(|v| v.as_i64()).unwrap_or(-2) as i32,
    };

    let result = match method {
        "global" => aligner.needleman_wunsch(&query, &target),
        _ => aligner.smith_waterman(&query, &target),
    };

    ok(json!({
        "score": result.score,
        "aligned_query": result.aligned_query,
        "aligned_target": result.aligned_target,
        "identity": (result.identity * 10000.0).round() / 10000.0,
        "method": if method == "global" { "Needleman-Wunsch (global)" } else { "Smith-Waterman (local)" },
    }))
}

fn handle_assemble(args: &Value) -> Value {
    let source = match args.get("source").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing: source"),
    };

    match asm::assemble(source) {
        Ok(program) => {
            let code_len = program.code.len() / 3; // codons = instructions
            ok(json!({
                "instruction_count": code_len,
                "data_size": program.data.len(),
                "program_dna": program.code.to_string(),
            }))
        },
        Err(e) => err(&format!("Assembly failed: {e}")),
    }
}

fn handle_evolve(args: &Value) -> Value {
    let seeds: Vec<String> = match args.get("seeds").and_then(|v| v.as_array()) {
        Some(arr) => arr.iter().filter_map(|v| v.as_str().map(String::from)).collect(),
        None => return err("missing: seeds (array of strings)"),
    };
    let target = match args.get("target").and_then(|v| v.as_str()) {
        Some(s) => s,
        None => return err("missing: target"),
    };

    let seed_refs: Vec<&str> = seeds.iter().map(|s| s.as_str()).collect();
    let config = EvolutionConfig {
        generations: args.get("generations").and_then(|v| v.as_u64()).unwrap_or(100) as usize,
        population_size: args.get("population_size").and_then(|v| v.as_u64()).unwrap_or(50) as usize,
        mutation_rate: args.get("mutation_rate").and_then(|v| v.as_f64()).unwrap_or(0.01),
        crossover_rate: 0.7,
        tournament_size: 3,
        elitism: 1,
    };

    let result = evolve(&seed_refs, target, config);

    ok(json!({
        "best_fitness": (result.best.fitness * 10000.0).round() / 10000.0,
        "best_word": result.best.word,
        "generations_run": result.generations.len(),
        "converged": result.converged_at.is_some(),
        "converged_at": result.converged_at,
    }))
}

fn handle_codon_table() -> Value {
    let table = CodonTable::standard();
    let bases = ["A", "T", "G", "C"];
    let mut codons = serde_json::Map::new();

    for &b1 in &bases {
        for &b2 in &bases {
            for &b3 in &bases {
                let codon_str = format!("{b1}{b2}{b3}");
                if let Some(codon) = parse_codon(&codon_str) {
                    let aa = table.translate(&codon);
                    codons.insert(codon_str, json!(format!("{aa:?}")));
                }
            }
        }
    }

    ok(json!({
        "codons": codons,
        "total": 64,
        "source": "Standard Genetic Code",
    }))
}
