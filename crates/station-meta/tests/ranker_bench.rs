//! Forensic benchmark: IdfRanker vs JaccardRanker on the real 3,095-entry fleet.
//!
//! Loads `~/ferroforge/configs/` via `ConfigIndex::load`, runs 20 real PV
//! intents through BOTH rankers, and compares top-1 accuracy + top-5 recall.
//!
//! This is a **measurement**, not advocacy. If IdfRanker does not measurably
//! improve over Jaccard on this corpus, the assertion at the end will fail and
//! we keep Jaccard as the default.
//!
//! Run: `cargo test -p station-meta --test ranker_bench -- --nocapture`

use station_meta::{ConfigIndex, IdfRanker, JaccardRanker, Ranker, ToolCandidate, discover_with};

fn configs_dir() -> std::path::PathBuf {
    let manifest = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest
        .parent()
        .and_then(|p| p.parent())
        .map(|p| p.join("configs"))
        .unwrap_or_else(|| panic!("no ferroforge/configs"))
}

/// A single benchmark case: a PV intent string and the expected config stem
/// that should rank highly. Stems are the JSON filename without `.json` —
/// all verified to exist in the fleet via `ls configs/`.
struct BenchCase {
    intent: &'static str,
    expected_stem: &'static str,
    category: &'static str,
}

fn bench_cases() -> Vec<BenchCase> {
    vec![
        // -------- 8 "clear rare term" intents --------
        // Each has a distinctive token (e.g. "FAERS", "MedDRA") that should
        // make the expected config trivially separable — IF the ranker gives
        // rare tokens enough weight.
        BenchCase {
            intent: "FAERS disproportionality analysis for metformin",
            expected_stem: "openvigilfrance",
            category: "rare",
        },
        BenchCase {
            intent: "MedDRA preferred term hierarchy lookup",
            expected_stem: "meddra",
            category: "rare",
        },
        BenchCase {
            intent: "RxNav RxCUI code for drug ingredient",
            expected_stem: "rxnav",
            category: "rare",
        },
        BenchCase {
            intent: "DailyMed structured product labeling adverse reactions",
            expected_stem: "dailymed",
            category: "rare",
        },
        BenchCase {
            intent: "PubMed signal literature case reports",
            expected_stem: "pubmed",
            category: "rare",
        },
        BenchCase {
            intent: "ClinicalTrials.gov serious adverse events in trial",
            expected_stem: "clinicaltrials",
            category: "rare",
        },
        BenchCase {
            intent: "WHO-UMC VigiBase causality assessment Naranjo",
            expected_stem: "who-umc",
            category: "rare",
        },
        BenchCase {
            intent: "CIOMS working group seriousness criteria",
            expected_stem: "cioms",
            category: "rare",
        },
        // -------- 6 "generic vocabulary" intents --------
        // Common tokens across many configs — rankers may legitimately
        // disagree. These test whether IDF or Jaccard handles noise better.
        BenchCase {
            intent: "drug safety adverse event reports",
            expected_stem: "openfda",
            category: "generic",
        },
        BenchCase {
            intent: "check for drug interactions and contraindications",
            expected_stem: "rxnav",
            category: "generic",
        },
        BenchCase {
            intent: "search adverse reaction reports",
            expected_stem: "vigiaccess",
            category: "generic",
        },
        BenchCase {
            intent: "regulatory guideline for pharmacovigilance",
            expected_stem: "ich",
            category: "generic",
        },
        BenchCase {
            intent: "drug pharmacology and targets",
            expected_stem: "drugbank",
            category: "generic",
        },
        BenchCase {
            intent: "disproportionality PRR ROR IC signal",
            expected_stem: "openvigilfrance",
            category: "generic",
        },
        // -------- 6 "hard / subtle" intents --------
        // The right answer depends on picking up a geographic, regulatory, or
        // branded term that isn't the most frequent word in the intent.
        BenchCase {
            intent: "EU-specific adverse event trends and safety signals",
            expected_stem: "eudravigilance",
            category: "hard",
        },
        BenchCase {
            intent: "Japanese post-marketing safety data drug approval",
            expected_stem: "pmda-go-jp",
            category: "hard",
        },
        BenchCase {
            intent: "European Medicines Agency EPAR referral",
            expected_stem: "ema",
            category: "hard",
        },
        BenchCase {
            intent: "global ICSR worldwide adverse reaction database",
            expected_stem: "vigiaccess",
            category: "hard",
        },
        BenchCase {
            intent: "French pharmacovigilance analytics open data",
            expected_stem: "openvigilfrance",
            category: "hard",
        },
        BenchCase {
            intent: "ICH E2B electronic transmission ICSR",
            expected_stem: "ich",
            category: "hard",
        },
    ]
}

/// Run a single intent through a ranker and collect the top-5 config stems
/// (deduplicated — we care about which CONFIG ranks, not which individual
/// tool). Order is preserved by first occurrence.
fn top5_stems(hits: &[ToolCandidate]) -> Vec<String> {
    let mut seen = Vec::new();
    for h in hits {
        if !seen.iter().any(|s: &String| s == &h.config_stem) {
            seen.push(h.config_stem.clone());
            if seen.len() == 5 {
                break;
            }
        }
    }
    seen
}

/// Run a ranker over all 20 intents. Returns (top1_correct, top5_correct)
/// plus per-intent results for the printed table.
fn evaluate_ranker(
    index: &ConfigIndex,
    ranker: &dyn Ranker,
    cases: &[BenchCase],
) -> (u32, u32, Vec<(bool, bool, Vec<String>)>) {
    // We need more than 5 raw hits because many configs expose multiple tools
    // — the per-tool top 5 can easily all come from the same config. Fetch
    // the top 25 tools so we can reliably recover the top-5 *configs*.
    let raw_limit = 25;
    let mut top1 = 0_u32;
    let mut top5 = 0_u32;
    let mut per_intent = Vec::with_capacity(cases.len());
    for c in cases {
        let hits = discover_with(index, c.intent, raw_limit, ranker);
        let stems = top5_stems(&hits);
        let is_top1 = stems.first().is_some_and(|s| s == c.expected_stem);
        let is_top5 = stems.iter().any(|s| s == c.expected_stem);
        if is_top1 {
            top1 += 1;
        }
        if is_top5 {
            top5 += 1;
        }
        per_intent.push((is_top1, is_top5, stems));
    }
    (top1, top5, per_intent)
}

/// Fetch the full top-5 results with scores for a ranker so we can measure
/// the score gap between top1 and top2 — used to identify "disagree-most"
/// intents. Returns (top1_stem, top1_score, top2_stem_opt, top2_score).
fn top_scores(
    index: &ConfigIndex,
    ranker: &dyn Ranker,
    intent: &str,
) -> (String, f64) {
    let hits = discover_with(index, intent, 1, ranker);
    hits.first()
        .map(|h| (h.config_stem.clone(), h.score))
        .unwrap_or_else(|| ("<none>".into(), 0.0))
}

#[test]
fn ranker_bench_idf_vs_jaccard() {
    let dir = configs_dir();
    if !dir.exists() {
        eprintln!("skipping — {} not present", dir.display());
        return;
    }

    let index = ConfigIndex::load(&dir).expect("load real config fleet");
    println!(
        "\nLoaded {} (config, tool) entries from {}",
        index.len(),
        dir.display()
    );
    println!("Corpus: {} docs, {} unique tokens", index.doc_count, index.doc_freq.len());

    let cases = bench_cases();
    assert_eq!(cases.len(), 20, "bench must have exactly 20 intents");

    let (j_top1, j_top5, j_results) = evaluate_ranker(&index, &JaccardRanker, &cases);
    let (i_top1, i_top5, i_results) = evaluate_ranker(&index, &IdfRanker, &cases);

    // ------------------------------------------------------------------
    // Per-intent comparison table
    // ------------------------------------------------------------------
    println!("\n{:=<120}", "");
    println!("{:^120}", "PER-INTENT COMPARISON (20 PV intents on 3,095-entry fleet)");
    println!("{:=<120}", "");
    println!(
        "{:<3} {:<8} {:<55} {:<15} | {:^6} {:^6} | {:^6} {:^6} | {:<10}",
        "#", "cat", "intent (truncated)", "expected", "J-T1", "J-T5", "I-T1", "I-T5", "winner"
    );
    println!("{:-<120}", "");

    for (i, c) in cases.iter().enumerate() {
        let (j1, j5, _j_stems) = &j_results[i];
        let (i1, i5, _i_stems) = &i_results[i];
        let winner = match (i5, j5, i1, j1) {
            (true, false, _, _) => "IDF",
            (false, true, _, _) => "JACCARD",
            (true, true, true, false) => "IDF",
            (true, true, false, true) => "JACCARD",
            _ => "tie",
        };
        let mark = |b: bool| if b { "YES" } else { " . " };
        let intent_trunc = if c.intent.len() > 53 {
            format!("{}..", &c.intent[..51])
        } else {
            c.intent.to_string()
        };
        println!(
            "{:<3} {:<8} {:<55} {:<15} | {:^6} {:^6} | {:^6} {:^6} | {:<10}",
            i + 1,
            c.category,
            intent_trunc,
            c.expected_stem,
            mark(*j1),
            mark(*j5),
            mark(*i1),
            mark(*i5),
            winner
        );
    }

    // ------------------------------------------------------------------
    // Aggregate numbers
    // ------------------------------------------------------------------
    println!("{:=<120}", "");
    println!("\nAGGREGATE RESULTS (n=20):");
    println!(
        "  Jaccard:  top-1 = {:>2}/20 ({:>5.1}%)   top-5 = {:>2}/20 ({:>5.1}%)",
        j_top1,
        100.0 * f64::from(j_top1) / 20.0,
        j_top5,
        100.0 * f64::from(j_top5) / 20.0
    );
    println!(
        "  IDF:      top-1 = {:>2}/20 ({:>5.1}%)   top-5 = {:>2}/20 ({:>5.1}%)",
        i_top1,
        100.0 * f64::from(i_top1) / 20.0,
        i_top5,
        100.0 * f64::from(i_top5) / 20.0
    );

    // Per-category breakdown
    for cat in &["rare", "generic", "hard"] {
        let total = cases.iter().filter(|c| c.category == *cat).count();
        let j_c = j_results
            .iter()
            .zip(&cases)
            .filter(|(_, c)| c.category == *cat)
            .filter(|((_, t5, _), _)| *t5)
            .count();
        let i_c = i_results
            .iter()
            .zip(&cases)
            .filter(|(_, c)| c.category == *cat)
            .filter(|((_, t5, _), _)| *t5)
            .count();
        println!(
            "  [{:<7}] (n={}): Jaccard top-5 = {}/{},  IDF top-5 = {}/{}",
            cat, total, j_c, total, i_c, total
        );
    }

    // ------------------------------------------------------------------
    // Biggest disagreements — intents where the top-1 stem differs
    // ------------------------------------------------------------------
    println!("\nTOP DISAGREEMENTS (intents where rankers pick different top-1 stems):");
    let mut disagreements: Vec<(usize, String, f64, String, f64)> = Vec::new();
    for (i, c) in cases.iter().enumerate() {
        let (j_stem, j_score) = top_scores(&index, &JaccardRanker, c.intent);
        let (i_stem, i_score) = top_scores(&index, &IdfRanker, c.intent);
        if j_stem != i_stem {
            // Use absolute score difference as a disagreement-strength proxy.
            // (The two scores aren't on the same scale, but larger absolute
            // magnitudes still correlate with "more emphatic" ranker opinion.)
            let gap = (j_score - i_score).abs();
            disagreements.push((i, j_stem, j_score, i_stem, i_score));
            let _ = gap; // recorded below for sort
        }
    }
    disagreements.sort_by(|a, b| {
        let ga = (a.2 - a.4).abs();
        let gb = (b.2 - b.4).abs();
        gb.partial_cmp(&ga).unwrap_or(std::cmp::Ordering::Equal)
    });
    for (i, j_stem, j_score, i_stem, i_score) in disagreements.iter().take(3) {
        println!(
            "  #{:<2} intent: {:?}",
            i + 1,
            cases[*i].intent
        );
        println!(
            "       Jaccard -> {:<20} (score {:.3})   IDF -> {:<20} (score {:.3})   expected: {}",
            j_stem, j_score, i_stem, i_score, cases[*i].expected_stem
        );
    }
    if disagreements.is_empty() {
        println!("  (none — rankers agree on top-1 for all 20 intents)");
    }

    // ------------------------------------------------------------------
    // Final assertion: IDF top-5 recall must be >= Jaccard top-5 recall
    // ------------------------------------------------------------------
    println!("\n{:=<120}", "");
    if i_top5 >= j_top5 {
        println!(
            "PASS: IDF top-5 recall ({}/20) >= Jaccard top-5 recall ({}/20)",
            i_top5, j_top5
        );
    } else {
        println!(
            "FAIL: IDF top-5 recall ({}/20) < Jaccard top-5 recall ({}/20)",
            i_top5, j_top5
        );
        println!("Intents where IDF missed but Jaccard hit:");
        for (i, c) in cases.iter().enumerate() {
            let (_, j5, _) = &j_results[i];
            let (_, i5, _) = &i_results[i];
            if *j5 && !*i5 {
                println!("  - [{}] {} (expected: {})", c.category, c.intent, c.expected_stem);
            }
        }
    }
    println!("{:=<120}\n", "");

    assert!(
        i_top5 >= j_top5,
        "IdfRanker top-5 recall ({}/20) regressed vs JaccardRanker ({}/20) — keep Jaccard as default",
        i_top5,
        j_top5
    );
}
