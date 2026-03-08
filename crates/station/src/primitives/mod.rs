//! T1 Lex Primitiva — Rust-native primitive analysis handlers.
//!
//! 15 axiomatic primitives, each encoding proven properties and failure modes
//! from the standalone Rust proof files (source: ~/Projects/Active/Notebook/primitives/).
//!
//! Pattern: same as `science/mod.rs` — `try_handle()` intercepts before proxy fallback.

use serde_json::{json, Value};
use tracing::info;

use crate::config::ConfigRegistry;
use crate::protocol::{ContentBlock, ToolCallResult};

/// Try to handle a tool call as a primitive analysis.
/// Returns `Some(ToolCallResult)` if handled, `None` to fall through.
pub fn try_handle(tool_name: &str, args: &Value, _registry: &ConfigRegistry) -> Option<ToolCallResult> {
    // Strip the primitives domain prefix to get the bare tool name
    let bare = tool_name
        .strip_prefix("primitives_nexvigilant_com_")
        .map(|s| s.replace('_', "-"))?;

    let result = handle(&bare, args)?;

    info!(tool = tool_name, "Handled primitive natively in Rust");

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

/// Route a primitive tool call to the appropriate handler.
fn handle(tool_name: &str, args: &Value) -> Option<Value> {
    match tool_name {
        "analyze-nothing" => Some(analyze_nothing(args)),
        "analyze-state" => Some(analyze_state(args)),
        "analyze-boundary" => Some(analyze_boundary(args)),
        "analyze-existence" => Some(analyze_existence(args)),
        "analyze-causality" => Some(analyze_causality(args)),
        "analyze-comparison" => Some(analyze_comparison(args)),
        "analyze-quantity" => Some(analyze_quantity(args)),
        "analyze-sequence" => Some(analyze_sequence(args)),
        "analyze-mapping" => Some(analyze_mapping(args)),
        "analyze-recursion" => Some(analyze_recursion(args)),
        "analyze-frequency" => Some(analyze_frequency(args)),
        "analyze-persistence" => Some(analyze_persistence(args)),
        "analyze-location" => Some(analyze_location(args)),
        "analyze-irreversibility" => Some(analyze_irreversibility(args)),
        "analyze-sum" => Some(analyze_sum(args)),
        _ => None,
    }
}

// ── Helper ──────────────────────────────────────────────────────────────

fn get_str<'a>(args: &'a Value, key: &str) -> &'a str {
    args.get(key).and_then(|v| v.as_str()).unwrap_or("")
}

// ── Nothing (∅) ─────────────────────────────────────────────────────────
// Properties: unique, idempotent, identity for existence, absorbing for product
// Source: nothing.rs — property_unique(), property_idempotent()

fn analyze_nothing(args: &Value) -> Value {
    let concept = get_str(args, "concept");

    json!({
        "status": "ok",
        "primitive": "Nothing",
        "symbol": "∅",
        "concept": concept,
        "analysis": {
            "description": "Nothing is the absence that defines presence. It is the ground state — the identity element for existence.",
            "question": format!("What is absent in '{}'? What gaps, voids, or missing elements define its identity?", concept),
            "framework": [
                "Identify what is conspicuously absent",
                "Check if the absence is meaningful (defines what IS present)",
                "Test: does removing this void change the system's identity?",
                "Map: which other primitives depend on this void"
            ]
        },
        "properties": {
            "unique": "There is exactly one Nothing — void is singular, not plural",
            "idempotent": "∅ ∪ ∅ = ∅ — combining nothing with nothing yields nothing",
            "identity_for_existence": "∃ requires ∅ — existence is defined against absence",
            "absorbing_for_product": "× (anything, ∅) = ∅ — nothing absorbs everything in product"
        },
        "failure_modes": [
            "Confusing emptiness with nothing (an empty set exists; nothing does not)",
            "Ignoring meaningful absence (the dog that didn't bark)",
            "Treating nothing as a value rather than the absence of value",
            "Failing to recognize void as a structural component"
        ],
        "pv_applications": [
            "Missing adverse event reports (reporting void as signal)",
            "Absence of expected drug interactions (negative signal)",
            "No cases in a demographic stratum (data gap detection)",
            "Zero-count cells in disproportionality tables"
        ],
        "conservation_role": "∃ = ∂(×(ς, ∅)) — Nothing is a required term. Remove ∅ and existence has no ground to define against."
    })
}

// ── State (ς) ───────────────────────────────────────────────────────────
// Properties: distinguishable, information-carrying, transition-capable
// Source: state.rs — property_distinguishable(), property_carries_information()

fn analyze_state(args: &Value) -> Value {
    let system = get_str(args, "system");
    let observation = get_str(args, "observation");

    json!({
        "status": "ok",
        "primitive": "State",
        "symbol": "ς",
        "system": system,
        "observation": if observation.is_empty() { Value::Null } else { Value::String(observation.to_string()) },
        "analysis": {
            "description": "State is what changed. The variable before boundary fixes it. Observable, distinguishable, information-carrying.",
            "question": format!("What are the observable states of '{}'? What transitions exist between them?", system),
            "framework": [
                "Enumerate distinguishable states",
                "Map transitions between states (what causes each)",
                "Identify the current state and how it was reached",
                "Test: can an observer distinguish state A from state B?"
            ]
        },
        "properties": {
            "distinguishable": "States must be observably different — if you can't tell them apart, they're the same state",
            "information_carrying": "Each state encodes information — the history of transitions that produced it",
            "transition_capable": "States can change — a state with no possible transitions is a fixed point"
        },
        "failure_modes": [
            "Trivial state (from == to) — a transition to the same state is not a real change",
            "Hidden state — system has state that is not observable from the measurement boundary",
            "State explosion — too many states to enumerate or reason about",
            "Conflating state with identity — state changes but identity persists"
        ],
        "pv_applications": [
            "Patient state transitions (healthy → AE → recovered → rechallenge)",
            "Signal state (potential → confirmed → actionable)",
            "Drug lifecycle states (IND → NDA → approved → post-market → withdrawn)",
            "Case processing states (received → triaged → assessed → submitted)"
        ],
        "conservation_role": "∃ = ∂(×(ς, ∅)) — State is the variable term. Remove ς and boundary has nothing to act on."
    })
}

// ── Boundary (∂) ────────────────────────────────────────────────────────
// Properties: asymmetric, identity-creating, composable, nothing-aware
// Source: boundary.rs — property_asymmetric(), property_creates_identity()

fn analyze_boundary(args: &Value) -> Value {
    let entity = get_str(args, "entity");
    let context = get_str(args, "context");

    json!({
        "status": "ok",
        "primitive": "Boundary",
        "symbol": "∂",
        "entity": entity,
        "context": if context.is_empty() { Value::Null } else { Value::String(context.to_string()) },
        "analysis": {
            "description": "Boundary is where things begin and end. It is a function — it takes state and produces identity. Inside differs from outside.",
            "question": format!("Where does '{}' begin and end? What separates it from its context?", entity),
            "framework": [
                "Identify the boundary (what separates inside from outside)",
                "Test asymmetry: is inside meaningfully different from outside?",
                "Check composition: can this boundary compose with others?",
                "Verify identity: does the boundary create a distinct identity?"
            ]
        },
        "properties": {
            "asymmetric": "∂(A, B) ≠ ∂(B, A) — inside-out differs from outside-in",
            "identity_creating": "Boundary defines what something IS by separating it from what it is NOT",
            "composable": "∂₁ ∘ ∂₂ — boundaries can nest and compose",
            "nothing_aware": "Boundary knows when it separates nothing from nothing (vacuous boundary)"
        },
        "failure_modes": [
            "Empty boundary — no identity (separates nothing from itself)",
            "Vacuous boundary — separates only nothing (no meaningful content)",
            "Leaky boundary — does not fully separate inside from outside",
            "Rigid boundary — cannot adapt when context changes"
        ],
        "pv_applications": [
            "Case boundary (what constitutes a single case vs separate cases)",
            "Signal boundary (threshold for statistical significance)",
            "Regulatory boundary (jurisdiction — which authority governs)",
            "Temporal boundary (reporting windows, observation periods)"
        ],
        "conservation_role": "∃ = ∂(×(ς, ∅)) — Boundary is the function. Remove ∂ and state×nothing has no structure — existence cannot form."
    })
}

// ── Existence (∃) ───────────────────────────────────────────────────────
// Properties: requires-all-three, negation-of-nothing, falsifiable
// Source: existence.rs — proven as ∃ = ∂(×(ς, ∅))

fn analyze_existence(args: &Value) -> Value {
    let subject = get_str(args, "subject");

    json!({
        "status": "ok",
        "primitive": "Existence",
        "symbol": "∃",
        "subject": subject,
        "analysis": {
            "description": "Existence is the conservation law's output: ∃ = ∂(×(ς, ∅)). It requires all three: boundary, state, and nothing. Remove any term and existence collapses.",
            "question": format!("Does '{}' exist? Test: does it have boundary (∂), state (ς), and ground (∅)?", subject),
            "conservation_test": {
                "boundary": format!("Does '{}' have a clear boundary separating it from its context?", subject),
                "state": format!("Does '{}' have observable, distinguishable state?", subject),
                "nothing": format!("Is '{}' defined against an absence — does removing it leave a void?", subject)
            },
            "framework": [
                "Test boundary: can you draw a line around it?",
                "Test state: can you observe and distinguish its condition?",
                "Test nothing: does its absence matter — would removing it leave a gap?",
                "If all three pass: exists. If any fails: existence is compromised."
            ]
        },
        "properties": {
            "requires_all_three": "∃ = ∂(×(ς, ∅)) — remove any term and existence collapses",
            "negation_of_nothing": "∃ = ¬∅ at ∂ given ς — existence is not-nothing with structure",
            "falsifiable": "Existence can be tested and disproven — it is not assumed"
        },
        "failure_modes": [
            "Phantom existence — claimed to exist but missing boundary or state",
            "Zombie existence — has boundary but no state (form without function)",
            "Assumed existence — not tested against the conservation law",
            "Partial existence — some terms present but not all three"
        ],
        "pv_applications": [
            "Signal existence (does a safety signal truly exist — boundary + state + void?)",
            "Case existence (does this report constitute a valid case?)",
            "Drug-event association existence (is the association real or artifact?)",
            "Regulatory action existence (has an action been taken or only discussed?)"
        ],
        "conservation_role": "∃ IS the conservation law's output. It is not assumed — it is derived from ∂(×(ς, ∅))."
    })
}

// ── Causality (→) ───────────────────────────────────────────────────────
// Properties: directional, transitive, temporally ordered
// Source: causality.rs — derivation chains, temporal ordering

fn analyze_causality(args: &Value) -> Value {
    let cause = get_str(args, "cause");
    let effect = get_str(args, "effect");

    json!({
        "status": "ok",
        "primitive": "Causality",
        "symbol": "→",
        "cause": cause,
        "effect": effect,
        "analysis": {
            "description": "Causality is what caused what. Every function, every consequence. It is directional and temporally ordered.",
            "question": format!("Does '{}' cause '{}'? What is the chain? Is it direct or mediated?", cause, effect),
            "framework": [
                "Establish temporal ordering (cause must precede effect)",
                "Identify the mechanism (how does cause produce effect?)",
                "Test counterfactual (would effect occur without cause?)",
                "Map the full chain (are there intermediate causes?)",
                "Assess strength (necessary, sufficient, or contributory?)"
            ]
        },
        "properties": {
            "directional": "→ has direction — cause precedes effect, not vice versa",
            "transitive": "A → B and B → C implies A → C (causal chains propagate)",
            "temporally_ordered": "Cause must precede effect in time",
            "not_symmetric": "A → B does not imply B → A"
        },
        "failure_modes": [
            "Reverse causation — effect mistaken for cause",
            "Spurious correlation — association without mechanism",
            "Confounding — hidden third variable causes both",
            "Overdetermination — multiple sufficient causes obscure the true one"
        ],
        "pv_applications": [
            "Drug-event causality assessment (Naranjo, WHO-UMC scales)",
            "Temporal association (drug exposure → adverse event onset)",
            "Dechallenge/rechallenge evidence (remove cause → effect resolves → reintroduce → recurs)",
            "Mechanism-based causality (known pharmacology supports the link)"
        ],
        "conservation_role": "Causality is how state transitions happen — it is the arrow in ς₁ → ς₂."
    })
}

// ── Comparison (κ) ──────────────────────────────────────────────────────
// Properties: reflexive, symmetric, total, deterministic
// Source: comparison.rs — symmetric difference metric

fn analyze_comparison(args: &Value) -> Value {
    let a = get_str(args, "a");
    let b = get_str(args, "b");

    json!({
        "status": "ok",
        "primitive": "Comparison",
        "symbol": "κ",
        "a": a,
        "b": b,
        "analysis": {
            "description": "Comparison measures how two things relate via symmetric difference. |A△B| = |A\\B| + |B\\A|. Distance 0 = identical. The universal primitive.",
            "question": format!("How do '{}' and '{}' compare? What do they share? What is unique to each?", a, b),
            "framework": [
                "Identify shared elements (A ∩ B)",
                "Identify elements unique to A (A \\ B)",
                "Identify elements unique to B (B \\ A)",
                "Compute distance: |A△B| = |unique_A| + |unique_B|",
                "Assess: is the distance meaningful?"
            ]
        },
        "properties": {
            "reflexive": "κ(A, A) = 0 — everything is identical to itself",
            "symmetric": "κ(A, B) = κ(B, A) — comparison is bidirectional",
            "total": "Any two things can be compared — comparison is universal",
            "deterministic": "Same inputs always produce the same distance",
            "metric": "Satisfies triangle inequality: κ(A,C) ≤ κ(A,B) + κ(B,C)"
        },
        "failure_modes": [
            "Comparing at wrong granularity (too coarse or too fine)",
            "Non-comparable dimensions (comparing apples to oranges without a shared basis)",
            "Ignoring shared elements (focusing only on differences)",
            "Distance without context (a distance of 5 means nothing without scale)"
        ],
        "pv_applications": [
            "Case similarity (duplicate detection via symmetric difference)",
            "Drug comparison (safety profile overlap between compounds)",
            "Signal comparison (how similar are two safety signals?)",
            "Terminology mapping (MedDRA preferred term distances)"
        ],
        "conservation_role": "Comparison is the measurement primitive — it quantifies the distance between any two states in the primitive space."
    })
}

// ── Quantity (N) ────────────────────────────────────────────────────────
// Properties: Peano axioms — zero, successor, induction
// Source: quantity.rs — natural number construction

fn analyze_quantity(args: &Value) -> Value {
    let concept = get_str(args, "concept");

    json!({
        "status": "ok",
        "primitive": "Quantity",
        "symbol": "N",
        "concept": concept,
        "analysis": {
            "description": "Quantity is how many. The measurable. Built on Peano: zero exists, every quantity has a successor, induction covers all.",
            "question": format!("What is countable or measurable in '{}'? What units? What scale?", concept),
            "framework": [
                "Identify what can be counted (discrete quantities)",
                "Identify what can be measured (continuous quantities)",
                "Determine units and scale",
                "Test: is the quantity meaningful (not just a number)?"
            ]
        },
        "properties": {
            "zero_exists": "There is a starting point — the count begins somewhere",
            "successor": "Every quantity has a next — you can always count one more",
            "induction": "What holds for zero and successor holds for all — proofs propagate",
            "comparable": "Quantities support < > = — they form a total order"
        },
        "failure_modes": [
            "Counting the uncountable (treating quality as quantity)",
            "Wrong unit (measuring length in kilograms)",
            "False precision (reporting 3.14159 when you measured 3±1)",
            "Quantity without context (42 of what?)"
        ],
        "pv_applications": [
            "Case counts per adverse event term",
            "PRR/ROR/IC signal scores (quantified disproportionality)",
            "Reporting rates (cases per patient-year)",
            "Time-to-onset distributions"
        ],
        "conservation_role": "Quantity enables measurement of all other primitives — you cannot manage what you cannot measure."
    })
}

// ── Sequence (σ) ────────────────────────────────────────────────────────
// Properties: total order, dependency-respecting, iteration-capable
// Source: sequence.rs — ordering, dependency chains

fn analyze_sequence(args: &Value) -> Value {
    let items = get_str(args, "items");

    json!({
        "status": "ok",
        "primitive": "Sequence",
        "symbol": "σ",
        "items": items,
        "analysis": {
            "description": "Sequence is in what order. Iteration, dependency, temporal progression. What must come before what.",
            "question": format!("What is the correct ordering of '{}'? What dependencies constrain the sequence?", items),
            "framework": [
                "List all items/steps",
                "Identify hard dependencies (A must precede B)",
                "Identify soft preferences (A should precede B but doesn't have to)",
                "Determine if the sequence is total (linear) or partial (branching)",
                "Test: does reordering break correctness?"
            ]
        },
        "properties": {
            "total_order": "Every pair of elements has a defined before/after relationship",
            "dependency_respecting": "Dependencies constrain valid orderings — violations break correctness",
            "iteration_capable": "Sequences can be traversed — step through one at a time"
        },
        "failure_modes": [
            "Missing dependency (step B runs before step A, which it needs)",
            "Circular dependency (A needs B needs A — no valid sequence exists)",
            "Over-constraining (forcing total order when partial order suffices)",
            "Ignoring parallelism (sequencing independent items unnecessarily)"
        ],
        "pv_applications": [
            "Case processing workflow (receive → triage → assess → report → follow-up)",
            "Signal detection pipeline (data → disproportionality → clinical review → action)",
            "Temporal sequence in causality (exposure → onset → outcome)",
            "Regulatory submission sequence (IND → Phase I → II → III → NDA)"
        ],
        "conservation_role": "Sequence orders the application of other primitives — ∂ before ∃, ς before →."
    })
}

// ── Mapping (μ) ─────────────────────────────────────────────────────────
// Properties: domain-to-codomain, preserves structure, composable
// Source: mapping.rs — transformation, bridge, domain transfer

fn analyze_mapping(args: &Value) -> Value {
    let source = get_str(args, "source");
    let target = get_str(args, "target");

    json!({
        "status": "ok",
        "primitive": "Mapping",
        "symbol": "μ",
        "source": source,
        "target": target,
        "analysis": {
            "description": "Mapping is what transforms to what. The bridge between domains. Structure-preserving transformation.",
            "question": format!("How does '{}' map to '{}'? What is preserved? What is lost?", source, target),
            "framework": [
                "Identify source domain elements",
                "Identify target domain elements",
                "Map each source element to its target (or identify gaps)",
                "Test structure preservation (does the mapping respect relationships?)",
                "Identify what is lost in translation"
            ]
        },
        "properties": {
            "domain_to_codomain": "Every mapping has a source (domain) and target (codomain)",
            "structure_preserving": "Good mappings preserve relationships — if A relates to B in source, their images relate similarly in target",
            "composable": "μ₁ ∘ μ₂ — mappings chain (map from A to B to C)"
        },
        "failure_modes": [
            "Lossy mapping — critical structure lost in translation",
            "Many-to-one collapse — distinct source elements map to same target",
            "Unmapped elements — source elements with no target (gaps)",
            "False equivalence — mapping dissimilar things as if they were the same"
        ],
        "pv_applications": [
            "MedDRA coding (verbatim term → preferred term → SOC)",
            "Cross-database mapping (FAERS → EudraVigilance terminology)",
            "Drug name normalization (brand → generic → active ingredient)",
            "Signal transfer (safety signal in one jurisdiction → mapped to another)"
        ],
        "conservation_role": "Mapping bridges domains — it is how insights transfer from one context to another."
    })
}

// ── Recursion (ρ) ───────────────────────────────────────────────────────
// Properties: self-referential, has fixed points, terminates (or diverges)
// Source: recursion.rs — self-reference, fixed points, termination

fn analyze_recursion(args: &Value) -> Value {
    let structure = get_str(args, "structure");

    json!({
        "status": "ok",
        "primitive": "Recursion",
        "symbol": "ρ",
        "structure": structure,
        "analysis": {
            "description": "Recursion is self-reference. Does the structure contain itself? Can the output feed back as input?",
            "question": format!("Does '{}' reference itself? What is the fixed point? Does it terminate?", structure),
            "framework": [
                "Test self-reference: does the structure appear inside itself?",
                "Identify the base case (what stops the recursion)",
                "Find the fixed point (what stays the same across iterations)",
                "Assess depth (how many levels of nesting)",
                "Check termination (does it converge or diverge?)"
            ]
        },
        "properties": {
            "self_referential": "The structure contains or references itself",
            "has_fixed_point": "There exists a state where f(x) = x — the recursion stabilizes",
            "termination": "Well-founded recursion terminates; ill-founded recursion diverges"
        },
        "failure_modes": [
            "Infinite recursion — no base case, never terminates",
            "Missing fixed point — recursion oscillates without converging",
            "Stack overflow — too deep before reaching base case",
            "False recursion — appears self-referential but actually isn't"
        ],
        "pv_applications": [
            "Recursive case follow-up (initial report → follow-up → follow-up of follow-up)",
            "Self-referencing regulatory guidelines (ICH E2A references ICH E2D references ICH E2A)",
            "Signal recursion (signal triggers investigation → investigation generates new signals)",
            "Benefit-risk recursion (risk mitigation creates new risks)"
        ],
        "conservation_role": "Recursion enables self-improvement — the system can analyze itself using primitives that include recursion."
    })
}

// ── Frequency (ν) ───────────────────────────────────────────────────────
// Properties: periodic, rate-based, pattern-forming
// Source: frequency.rs — rate, rhythm, repetition

fn analyze_frequency(args: &Value) -> Value {
    let signal = get_str(args, "signal");

    json!({
        "status": "ok",
        "primitive": "Frequency",
        "symbol": "ν",
        "signal": signal,
        "analysis": {
            "description": "Frequency is how often. Rate, rhythm, repetition, periodicity. The temporal primitive.",
            "question": format!("How often does '{}' occur? Is there a pattern? What is the rate?", signal),
            "framework": [
                "Measure rate (occurrences per unit time)",
                "Test periodicity (does it repeat at regular intervals?)",
                "Identify rhythm (is the pattern regular, irregular, or bursty?)",
                "Compare to baseline (is this frequency expected or anomalous?)"
            ]
        },
        "properties": {
            "periodic": "Some frequencies have regular cycles — they repeat predictably",
            "rate_based": "Frequency is fundamentally a rate — events per time unit",
            "pattern_forming": "Repeated patterns become visible through frequency analysis"
        },
        "failure_modes": [
            "Aliasing — sampling too infrequently to detect the true pattern",
            "Confusing frequency with probability (how often ≠ how likely next time)",
            "Base rate neglect — anomalous frequency relative to what baseline?",
            "Temporal confounding — frequency changes due to external factors"
        ],
        "pv_applications": [
            "Reporting frequency (cases per quarter — trending up or down?)",
            "Disproportionality reporting ratio (observed vs expected frequency)",
            "Periodic safety update reports (PSURs — frequency-driven regulatory rhythm)",
            "Seasonal AE patterns (frequency varies with time of year)"
        ],
        "conservation_role": "Frequency measures how often state transitions occur — it quantifies the rate of change."
    })
}

// ── Persistence (π) ─────────────────────────────────────────────────────
// Properties: enduring, mechanism-dependent, lifetime-bounded
// Source: persistence.rs — state fixing, survival

fn analyze_persistence(args: &Value) -> Value {
    let entity = get_str(args, "entity");

    json!({
        "status": "ok",
        "primitive": "Persistence",
        "symbol": "π",
        "entity": entity,
        "analysis": {
            "description": "Persistence is what endures. State that survives. The mechanism that fixes a variable into a point: π(ς) at ∂.",
            "question": format!("Does '{}' persist? What mechanism preserves it? What is its lifetime?", entity),
            "framework": [
                "Test endurance: does it survive across time/context changes?",
                "Identify mechanism: what keeps it alive? (replication, storage, institution)",
                "Measure lifetime: how long does it persist? (bounded or unbounded)",
                "Test: what would cause it to stop persisting?"
            ]
        },
        "properties": {
            "enduring": "Persistent things survive across time and context changes",
            "mechanism_dependent": "Persistence requires a mechanism — nothing persists by default",
            "lifetime_bounded": "Most persistence is finite — even mountains erode"
        },
        "failure_modes": [
            "Assumed persistence — treating ephemeral things as permanent",
            "Mechanism failure — the preservation mechanism breaks down",
            "Bit rot — gradual degradation that goes unnoticed",
            "Persistence without value — keeping things alive that should expire"
        ],
        "pv_applications": [
            "Data retention (how long are case records preserved?)",
            "Signal persistence (does a safety signal endure or fade with more data?)",
            "Institutional knowledge (PV expertise that survives staff turnover)",
            "Drug label changes (persistent regulatory actions)"
        ],
        "conservation_role": "Persistence fixes state into a point — π(ς) at ∂ is the definition of a parameter."
    })
}

// ── Location (λ) ────────────────────────────────────────────────────────
// Properties: addressable, reachable, domain-situated
// Source: location.rs — address, reference, path

fn analyze_location(args: &Value) -> Value {
    let reference = get_str(args, "reference");

    json!({
        "status": "ok",
        "primitive": "Location",
        "symbol": "λ",
        "reference": reference,
        "analysis": {
            "description": "Location is where. Address, reference, path. Every entity exists somewhere in some domain.",
            "question": format!("Where is '{}' located? Is it reachable? What is its address in its domain?", reference),
            "framework": [
                "Identify the domain (what space does it live in?)",
                "Determine the address (how do you find it?)",
                "Test reachability (can you get to it from here?)",
                "Map the path (what route leads there?)"
            ]
        },
        "properties": {
            "addressable": "Every location has an address — a way to refer to it",
            "reachable": "Locations may or may not be reachable from a given starting point",
            "domain_situated": "Location is always relative to a domain — there is no absolute location"
        },
        "failure_modes": [
            "Stale reference — the address points to where it was, not where it is",
            "Unreachable — the entity exists but cannot be accessed from here",
            "Ambiguous address — the reference resolves to multiple locations",
            "Wrong domain — looking in the right place in the wrong space"
        ],
        "pv_applications": [
            "Geographic distribution of adverse events (where are cases reported?)",
            "Regulatory jurisdiction (which authority's domain?)",
            "Data source location (FAERS vs EudraVigilance vs VigiBase)",
            "Anatomical location of adverse events (SOC-level MedDRA coding)"
        ],
        "conservation_role": "Location situates all other primitives — every state, boundary, and existence is somewhere."
    })
}

// ── Irreversibility (∝) ────────────────────────────────────────────────
// Properties: entropy-increasing, one-way, consequence-bearing
// Source: irreversibility.rs — entropy arrow, one-way operations

fn analyze_irreversibility(args: &Value) -> Value {
    let action = get_str(args, "action");

    json!({
        "status": "ok",
        "primitive": "Irreversibility",
        "symbol": "∝",
        "action": action,
        "analysis": {
            "description": "Irreversibility is entropy's arrow. Can it be undone? Some state transitions are one-way — they increase entropy.",
            "question": format!("Is '{}' reversible? What is the cost of undoing it? What consequences are permanent?", action),
            "framework": [
                "Test reversibility: can you return to the prior state?",
                "Measure entropy delta: does this increase or decrease disorder?",
                "Identify permanent consequences: what cannot be undone?",
                "Assess cost of reversal: even if possible, what does undoing it cost?"
            ]
        },
        "properties": {
            "entropy_increasing": "Irreversible actions increase entropy — they move toward disorder",
            "one_way": "Some transitions have no return path — the arrow only points forward",
            "consequence_bearing": "Irreversible actions carry permanent consequences"
        },
        "failure_modes": [
            "Assuming reversibility (acting as if undo is free)",
            "Ignoring second-order effects (reversal doesn't undo consequences)",
            "False irreversibility (treating reversible actions as permanent)",
            "Entropy blindness (not recognizing the accumulation of disorder)"
        ],
        "pv_applications": [
            "Fatal outcomes (death is irreversible — highest seriousness)",
            "Regulatory withdrawal (removing a drug from market is extremely hard to reverse)",
            "Data deletion (destroyed case records cannot be recovered)",
            "Reputation damage (public safety communications are irreversible)"
        ],
        "conservation_role": "Irreversibility constrains what transformations are possible — not all state changes can be reversed."
    })
}

// ── Sum (Σ) ─────────────────────────────────────────────────────────────
// Properties: disjoint, exhaustive, variant-selecting
// Source: sum.rs — disjoint union, variant selection

fn analyze_sum(args: &Value) -> Value {
    let variants = get_str(args, "variants");

    json!({
        "status": "ok",
        "primitive": "Sum",
        "symbol": "Σ",
        "variants": variants,
        "analysis": {
            "description": "Sum is the disjoint union. Which variant? Is the enumeration complete? Exactly one case applies at any time.",
            "question": format!("What are the variants of '{}'? Is the enumeration exhaustive? Which case applies?", variants),
            "framework": [
                "List all variants (cases, options, branches)",
                "Test disjointness: are variants mutually exclusive?",
                "Test exhaustiveness: do variants cover all possibilities?",
                "Identify the active variant: which case applies now?",
                "Check for missing variants: is there an 'other' or 'unknown'?"
            ]
        },
        "properties": {
            "disjoint": "Variants are mutually exclusive — exactly one applies at a time",
            "exhaustive": "A complete sum covers all possibilities — no case is missing",
            "variant_selecting": "The sum type selects one variant — it is a choice"
        },
        "failure_modes": [
            "Non-exhaustive enumeration (missing the 'other' case)",
            "Overlapping variants (two cases apply simultaneously — violates disjointness)",
            "Phantom variant (listed but never occurs)",
            "Hidden variant (exists but not enumerated — the unknown unknown)"
        ],
        "pv_applications": [
            "Seriousness classification (death | life-threatening | hospitalization | disability | congenital | other)",
            "Causality assessment categories (certain | probable | possible | unlikely | unrelated)",
            "Case outcome (recovered | recovering | not recovered | fatal | unknown)",
            "Signal disposition (confirmed | refuted | ongoing | closed)"
        ],
        "conservation_role": "Sum enables classification — every entity can be categorized into exactly one variant of a complete enumeration."
    })
}
