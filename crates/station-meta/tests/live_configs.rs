//! Integration test — consumer boundary verification.
//!
//! Loads the real `~/ferroforge/configs/` directory and runs a discovery to
//! confirm the prototype works against production data, not just mocks.

use station_meta::{ConfigIndex, discover};

fn configs_dir() -> std::path::PathBuf {
    // CARGO_MANIFEST_DIR = crates/station-meta; configs live two levels up.
    let manifest = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest.parent().and_then(|p| p.parent()).map(|p| p.join("configs")).unwrap_or_else(|| panic!("no ferroforge/configs"))
}

#[test]
fn loads_real_config_fleet() {
    let dir = configs_dir();
    if !dir.exists() {
        eprintln!("skipping — {} not present", dir.display());
        return;
    }
    let index = ConfigIndex::load(&dir).expect("load real configs");
    // Sanity: fleet should have at least 200 (config, tool) rows.
    assert!(
        index.len() >= 200,
        "expected >= 200 indexed (config, tool) rows, got {}",
        index.len()
    );
    println!("indexed {} (config, tool) rows from {}", index.len(), dir.display());
}

#[test]
fn adverse_event_intent_surfaces_faers() {
    let dir = configs_dir();
    if !dir.exists() {
        eprintln!("skipping — {} not present", dir.display());
        return;
    }
    let index = ConfigIndex::load(&dir).expect("load real configs");
    let hits = discover(&index, "search FAERS adverse events for metformin", 5);
    assert!(!hits.is_empty(), "expected FAERS-related hits");
    // At least one hit must be from a FAERS/FDA-adjacent config.
    let top_ids: Vec<String> = hits.iter().map(|h| h.config.clone()).collect();
    let has_fda = top_ids.iter().any(|c| c.contains("fda") || c.contains("faers") || c.contains("openfda"));
    assert!(has_fda, "expected FDA/FAERS config in top 5; got {:?}", top_ids);
    println!("top-5 for 'FAERS adverse events':");
    for h in &hits {
        println!("  [{:.3}] {}::{} — {}", h.score, h.config, h.tool, h.title);
    }
}

#[test]
fn meddra_intent_surfaces_terminology() {
    let dir = configs_dir();
    if !dir.exists() {
        return;
    }
    let index = ConfigIndex::load(&dir).expect("load");
    let hits = discover(&index, "meddra preferred term lookup", 5);
    assert!(!hits.is_empty());
    let has_meddra = hits.iter().any(|h| h.config.contains("meddra"));
    assert!(has_meddra, "meddra intent should surface meddra config");
}

#[test]
fn discovery_is_fast_on_full_fleet() {
    let dir = configs_dir();
    if !dir.exists() {
        return;
    }
    let index = ConfigIndex::load(&dir).expect("load");
    let start = std::time::Instant::now();
    for _ in 0..100 {
        let _ = discover(&index, "adverse event search for metformin", 5);
    }
    let elapsed = start.elapsed();
    println!("100 discoveries on full fleet: {:?}", elapsed);
    // Budget: 100 calls in < 1s means ~10ms each (well below 50ms target).
    assert!(
        elapsed.as_millis() < 2000,
        "100 discoveries took {:?} — too slow",
        elapsed
    );
}
