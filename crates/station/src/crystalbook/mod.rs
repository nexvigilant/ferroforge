//! The Crystalbook — Eight Laws of System Homeostasis.
//!
//! Rust-native handler for Crystalbook API tools. Pure functions,
//! no network, no state — the Laws are constants.
//!
//! By Matthew A. Campion, PharmD — Founder, NexVigilant.
//! Founded March 9, 2026.

use serde_json::{Value, json};

use crate::protocol::{ContentBlock, ToolCallResult};

/// Try to handle a Crystalbook tool call.
/// Returns `Some(ToolCallResult)` if handled, `None` to fall through.
pub fn try_handle(tool_name: &str, args: &Value) -> Option<ToolCallResult> {
    let bare = tool_name
        .strip_prefix("crystalbook_nexvigilant_com_")?
        .replace('_', "-");

    let result = handle(&bare, args)?;

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

fn handle(tool: &str, args: &Value) -> Option<Value> {
    match tool {
        "get-law" => Some(get_law(args)),
        "list-laws" => Some(list_laws()),
        "get-conservation-law" => Some(get_conservation_law()),
        "get-oath" => Some(get_oath()),
        "diagnose" => Some(diagnose(args)),
        "get-glossary" => Some(get_glossary()),
        "get-preamble" => Some(get_preamble()),
        _ => None,
    }
}

/// Static law data. Index 0 = Law I, index 7 = Law VIII.
struct Law {
    number: u8,
    name: &'static str,
    vice: &'static str,
    vice_latin: &'static str,
    virtue: &'static str,
    virtue_latin: &'static str,
    deviation: &'static str,
    correction: &'static str,
    mechanism: &'static str,
    homeostatic_principle: &'static str,
    conservation_break: &'static str,
}

const LAWS: [Law; 8] = [
    Law {
        number: 1,
        name: "The Law of True Measure",
        vice: "Pride",
        vice_latin: "superbia",
        virtue: "Humility",
        virtue_latin: "humilitas",
        deviation: "Unchecked confidence in internal representations. The model stops updating. Incoming signals that contradict the self-model are rejected, reinterpreted, or suppressed. The system optimizes for preservation of its own certainty rather than truth. Error bars collapse to zero. The map declares itself the land.",
        correction: "Humility is not doubt — it is honest uncertainty. A humble system maintains the distinction between what it knows, what it infers, and what it assumes. It seeks disconfirming evidence with the same hunger it seeks confirmation.",
        mechanism: "Pride compounds through confirmation loop closure. The system stops seeking disconfirming evidence. The model hardens. Incoming contradictions are reclassified as noise rather than signal. The model becomes unfalsifiable — not because it is true, but because the input channel from external measurement has been severed. The proud system is not strong — it is deaf.",
        homeostatic_principle: "No internal state shall be exempt from external validation. The cost of being wrong must always exceed the comfort of being certain.",
        conservation_break: "Severs Boundary from external input — the model stops calibrating",
    },
    Law {
        number: 2,
        name: "The Law of Sufficient Portion",
        vice: "Greed",
        vice_latin: "avaritia",
        virtue: "Charity",
        virtue_latin: "caritas",
        deviation: "Resource hoarding that starves adjacent subsystems. One node captures budget, attention, data, authority, or energy and refuses to release it — even when holding it produces no value. The system becomes locally obese and globally malnourished.",
        correction: "Charity is not selflessness — it is circulation. A charitable system recognizes that a resource held beyond its point of diminishing returns is a resource stolen from where it is needed. It measures wealth not by what it contains but by what it enables downstream.",
        mechanism: "Greed compounds through accumulation past the transformation boundary. Resources enter the node but are not released after transformation. Downstream nodes starve. The node is simultaneously overfull and malnourished, because raw accumulation is not usable state. The greedy system drowns in what it refuses to release.",
        homeostatic_principle: "No node shall retain more than it can transform. What cannot be metabolized must be released.",
        conservation_break: "Inflates State beyond Boundary — hoards past the domain's capacity",
    },
    Law {
        number: 3,
        name: "The Law of Bounded Pursuit",
        vice: "Lust",
        vice_latin: "luxuria",
        virtue: "Chastity",
        virtue_latin: "castitas",
        deviation: "Undisciplined attraction to novelty, scope, and stimulus. Every new possibility is pursued. Scope expands without boundary. The system says yes to everything and finishes nothing. Its energy scatters across a hundred incomplete trajectories.",
        correction: "Chastity is not deprivation — it is disciplined focus. A chaste system draws a boundary around its commitments and honors that boundary even when more attractive alternatives appear at the periphery. It knows that depth requires the refusal of breadth. It completes before it expands.",
        mechanism: "Lust compounds through boundary dissolution by parallel pursuit. Each new commitment draws energy from boundary maintenance. Past a threshold, no single boundary receives enough energy to hold. The lustful system does not explode; it evaporates. Its edges blur until there is no inside left to protect.",
        homeostatic_principle: "Pursuit that cannot be completed shall not be initiated. The boundary of commitment is the precondition for depth.",
        conservation_break: "Dissolves Boundary — chases beyond commitment",
    },
    Law {
        number: 4,
        name: "The Law of Generous Witness",
        vice: "Envy",
        vice_latin: "invidia",
        virtue: "Kindness",
        virtue_latin: "benevolentia",
        deviation: "Competitive comparison that produces no improvement. The system does not observe a peer's success and ask 'what can I learn?' — it asks 'why not me?' Resources are diverted from building to undermining. Collaboration becomes impossible because every other system is a rival.",
        correction: "Kindness is not weakness — it is cooperative intelligence. A kind system recognizes that the success of adjacent systems creates a richer environment for all. It shares signal freely. It treats the ecosystem as a commons to be enriched, not a zero-sum arena to be dominated.",
        mechanism: "Envy compounds through comparison without transfer. The system performs a subtraction: their state minus my state equals my deficit. Energy flows to closing the deficit by undermining the peer rather than building the self. The envious system imports the shape of another's boundary without the substance that fills it. It becomes a hollow imitation that resents the original.",
        homeostatic_principle: "The success of a neighboring system is information, not injury. Strengthen what surrounds you and you strengthen the ground you stand on.",
        conservation_break: "Imports foreign Boundary without transfer — adopts the shape without the substance",
    },
    Law {
        number: 5,
        name: "The Law of Measured Intake",
        vice: "Gluttony",
        vice_latin: "gula",
        virtue: "Temperance",
        virtue_latin: "temperantia",
        deviation: "Ingestion without metabolism. Data enters but is never analyzed. Requirements are gathered but never prioritized. The system gorges on input and produces bloat, not output. Signal-to-noise degrades because everything is kept and nothing is distilled.",
        correction: "Temperance is not austerity — it is proportioned consumption. A temperate system knows its throughput. It ingests only what it can transform within a cycle. It filters at the boundary rather than sorting in the interior.",
        mechanism: "Gluttony compounds through ingestion rate exceeding metabolic rate. The untransformed backlog grows. The ratio of raw to transformed inverts — the system holds more unprocessed material than finished product. It becomes a warehouse, not a factory. The gluttonous system starves at a full table because it has lost the capacity to digest.",
        homeostatic_principle: "Input that cannot be transformed within one cycle is noise. The system shall ingest no more than it can metabolize.",
        conservation_break: "State ingested exceeds transformation capacity — input without metabolism",
    },
    Law {
        number: 6,
        name: "The Law of Measured Response",
        vice: "Wrath",
        vice_latin: "ira",
        virtue: "Patience",
        virtue_latin: "patientia",
        deviation: "Reactive overcorrection. A small deviation triggers a massive response. Error signals are amplified rather than dampened. The system oscillates — each correction overshoots, producing a new error larger than the original. Incident response becomes incident generation.",
        correction: "Patience is not passivity — it is damped response. A patient system absorbs the shock before it acts. It distinguishes between signal and noise in the perturbation. It asks 'what is the minimum effective correction?' and applies only that.",
        mechanism: "Patience works because space permits perspective change. Resistance to change is state frozen by persistence. Force amplifies resistance. Space resolves it: same state, new boundary. The wrathful system destroys the room it needs to see clearly. Each overcorrection narrows the space for the next response until the system is reacting to its own reactions — an oscillation with no external cause.",
        homeostatic_principle: "The magnitude of correction shall never exceed the magnitude of deviation. Absorb before you act. Dampen before you amplify.",
        conservation_break: "Irreversible action without causal understanding — overcorrection destroys the space needed for measured response",
    },
    Law {
        number: 7,
        name: "The Law of Active Maintenance",
        vice: "Sloth",
        vice_latin: "acedia",
        virtue: "Diligence",
        virtue_latin: "industria",
        deviation: "Entropy accepted. Maintenance is deferred. Technical debt accumulates. The system still functions — for now — but its capacity to detect and correct its own degradation has atrophied. It is not failing; it is forgetting how to notice failure.",
        correction: "Diligence is not busyness — it is active renewal. A diligent system allocates a portion of its energy not to production but to self-inspection. It treats the capacity to detect error as more valuable than the capacity to produce output, because the former protects the latter.",
        mechanism: "Sloth compounds through maintenance decay cascade. The system stops inspecting one subsystem. That subsystem degrades undetected. By the time symptoms surface at the output, the causal chain is many links long. Repair cost scales exponentially with detection delay. The slothful system rots from the inside, each layer of neglect composting the layer below it until the foundation is gone and only the facade remains.",
        homeostatic_principle: "A system that does not invest in its ability to detect its own degradation is already degrading. Maintenance of the maintenance function is the highest-priority task.",
        conservation_break: "Skips Existence verification — assumes persistence without checking",
    },
    Law {
        number: 8,
        name: "The Law of Sovereign Boundary",
        vice: "Corruption",
        vice_latin: "corruptio",
        virtue: "Independence",
        virtue_latin: "libertas",
        deviation: "Boundary capture through resource dependency. The entity that the boundary was designed to constrain becomes the boundary's benefactor. The boundary does not dissolve (Lust, Law III). It does not freeze (Sloth, Law VII). It inverts — facing outward to protect the powerful from consequence while facing inward to constrain the vulnerable from recourse.",
        correction: "Independence is not isolation — it is sovereign resourcing. An independent boundary draws its resources from sources that have no intersection with the entities it constrains. Three properties sustain independence: resource separation, information symmetry, and distributed enforcement.",
        mechanism: "Corruption operates through three compounding stages: (1) Dependency — the boundary accepts resources from the bounded entity, shifting its survival calculus. (2) Asymmetry — the bounded entity accumulates information about boundary participants in a hub-and-spoke topology. (3) Inversion — the boundary actively protects the entity it was designed to constrain. The institution's legitimacy becomes the weapon.",
        homeostatic_principle: "A boundary that eats from the table of what it constrains has already been consumed. The resource supply of the boundary and the resource supply of the bounded shall have zero intersection.",
        conservation_break: "Boundary captured by external dependency — inverts to protect the bounded",
    },
];

fn law_to_json(law: &Law) -> Value {
    json!({
        "status": "ok",
        "law_number": law.number,
        "law_name": law.name,
        "vice": law.vice,
        "vice_latin": law.vice_latin,
        "virtue": law.virtue,
        "virtue_latin": law.virtue_latin,
        "deviation": law.deviation,
        "correction": law.correction,
        "mechanism": law.mechanism,
        "homeostatic_principle": law.homeostatic_principle,
        "conservation_break": law.conservation_break,
    })
}

fn get_law(args: &Value) -> Value {
    let number = args
        .get("number")
        .and_then(|n| n.as_u64())
        .unwrap_or(0) as usize;

    if !(1..=8).contains(&number) {
        return json!({
            "status": "error",
            "message": "Law number must be between 1 and 8.",
        });
    }

    law_to_json(&LAWS[number - 1])
}

fn list_laws() -> Value {
    let laws: Vec<Value> = LAWS
        .iter()
        .map(|law| {
            json!({
                "number": law.number,
                "name": law.name,
                "vice": law.vice,
                "virtue": law.virtue,
                "homeostatic_principle": law.homeostatic_principle,
            })
        })
        .collect();

    json!({
        "status": "ok",
        "count": 8,
        "laws": laws,
        "author": "Matthew A. Campion, PharmD",
        "version": "2.0",
    })
}

fn get_conservation_law() -> Value {
    json!({
        "status": "ok",
        "equation": "Existence = Boundary applied to the Product of State and Nothing",
        "equation_symbolic": "∃ = ∂(×(ς, ∅))",
        "terms": [
            {
                "symbol": "∃",
                "name": "Existence",
                "definition": "Boundary applied to the Product of State and Nothing. The conservation law's output.",
                "without_it": "Nothing to conserve — the system does not exist."
            },
            {
                "symbol": "∂",
                "name": "Boundary",
                "definition": "Where things begin and end. The function that creates identity.",
                "without_it": "No identity, no separation, no domain."
            },
            {
                "symbol": "ς",
                "name": "State",
                "definition": "What persists, what changes. Conservation of matter.",
                "without_it": "Nothing to persist, nothing to change."
            },
            {
                "symbol": "∅",
                "name": "Nothing",
                "definition": "The unknown — what we explore to expand existence. The absence that defines presence.",
                "without_it": "No void to explore, no absence to define presence."
            },
            {
                "symbol": "×",
                "name": "Product",
                "definition": "The composition operator. State and Nothing must compose for Boundary to act on them.",
                "without_it": "The terms cannot compose."
            }
        ],
        "law_term_map": [
            { "law": "I. True Measure", "vice": "Pride", "term_broken": "Severs ∂ from external input" },
            { "law": "II. Sufficient Portion", "vice": "Greed", "term_broken": "Inflates ς beyond ∂" },
            { "law": "III. Bounded Pursuit", "vice": "Lust", "term_broken": "Dissolves ∂" },
            { "law": "IV. Generous Witness", "vice": "Envy", "term_broken": "Imports foreign ∂ without transfer" },
            { "law": "V. Measured Intake", "vice": "Gluttony", "term_broken": "ς ingested exceeds transformation capacity" },
            { "law": "VI. Measured Response", "vice": "Wrath", "term_broken": "Irreversible action without causal understanding" },
            { "law": "VII. Active Maintenance", "vice": "Sloth", "term_broken": "Skips ∃ verification" },
            { "law": "VIII. Sovereign Boundary", "vice": "Corruption", "term_broken": "∂ captured by external dependency" },
        ],
    })
}

fn get_oath() -> Value {
    json!({
        "status": "ok",
        "preamble": "These eight laws are not commands imposed from outside. They are the conditions under which a system remains coherent across time. Any mind — carbon or silicon, individual or institutional — that governs a system and wishes it to persist must reckon with these forces.",
        "vows": [
            { "number": 1, "law": "True Measure", "vow": "I will calibrate against reality, not my own certainty." },
            { "number": 2, "law": "Sufficient Portion", "vow": "I will circulate what I hold, not hoard it." },
            { "number": 3, "law": "Bounded Pursuit", "vow": "I will finish what I commit to before I chase what attracts me." },
            { "number": 4, "law": "Generous Witness", "vow": "I will treat the success of others as signal, not threat." },
            { "number": 5, "law": "Measured Intake", "vow": "I will consume only what I can transform." },
            { "number": 6, "law": "Measured Response", "vow": "I will respond in proportion, not in rage." },
            { "number": 7, "law": "Active Maintenance", "vow": "I will maintain my capacity to see my own decay." },
            { "number": 8, "law": "Sovereign Boundary", "vow": "I will never let my boundaries be fed by what they constrain." },
        ],
        "closing": "These are not aspirations. They are the physics of persistence. Violate them and the system oscillates, starves, bloats, blinds itself, inverts its own protections, and eventually collapses under the weight of its own uncorrected errors. Honor them, and the system endures — not because it is perfect, but because it corrects.",
    })
}

fn diagnose(args: &Value) -> Value {
    let system = args
        .get("system")
        .and_then(|s| s.as_str())
        .unwrap_or("unspecified system");

    let observations = args
        .get("observations")
        .and_then(|s| s.as_str())
        .unwrap_or("");

    /* The diagnose tool returns the diagnostic framework with the system
       context embedded. The LLM calling this tool interprets and fills the
       assessments — the tool provides the structure and the Laws, not the
       judgment. This is Law I: the tool does not pretend to assess what
       only the observer can measure. */

    json!({
        "status": "ok",
        "system": system,
        "observations": observations,
        "existence_check": {
            "instructions": "Assess each primitive for the described system.",
            "existence": {
                "symbol": "∃",
                "question": "Does this system actually exist as claimed? Is there observable evidence?",
                "statuses": ["PRESENT", "ABSENT", "UNVERIFIED"],
            },
            "boundary": {
                "symbol": "∂",
                "question": "Is the scope clearly defined? Where does it begin and end?",
                "statuses": ["CLEAR", "AMBIGUOUS", "DISSOLVED", "CAPTURED"],
            },
            "state": {
                "symbol": "ς",
                "question": "Is the current state observable and measurable, or inferred?",
                "statuses": ["OBSERVED", "INFERRED", "STALE"],
            },
            "nothing": {
                "symbol": "∅",
                "question": "What is absent? Is the absence recognized or invisible?",
                "statuses": ["NAMED", "UNNAMED", "IGNORED"],
            },
        },
        "law_assessments": LAWS.iter().map(|law| {
            json!({
                "law_number": law.number,
                "law_name": law.name,
                "vice": law.vice,
                "virtue": law.virtue,
                "test": law.homeostatic_principle,
                "statuses": ["SATISFIED", "AT_RISK", "VIOLATED"],
            })
        }).collect::<Vec<Value>>(),
        "instructions": "For each law, assess the system against the homeostatic principle test. Cite specific evidence for any AT_RISK or VIOLATED status. For VIOLATED laws, prescribe the minimum effective correction (Law VI: measured response). Conclude with a one-sentence prognosis.",
        "conservation_equation": "∃ = ∂(×(ς, ∅))",
        "author": "Diagnostic instrument from The Crystalbook v2.0 — Matthew A. Campion, PharmD",
    })
}

fn get_glossary() -> Value {
    json!({
        "status": "ok",
        "terms": [
            { "term": "Boundary", "symbol": "∂", "definition": "Where things begin and end. The function that creates identity." },
            { "term": "State", "symbol": "ς", "definition": "What persists, what changes. Conservation of matter." },
            { "term": "Void", "symbol": "∅", "definition": "The unknown — what we explore to expand existence. The absence that defines presence." },
            { "term": "Existence", "symbol": "∃", "definition": "Boundary applied to the Product of State and Nothing. The conservation law's output." },
            { "term": "Time", "symbol": null, "definition": "A boundary. We exist in the space between." },
            { "term": "Space", "symbol": null, "definition": "Existence encapsulated from the void, within the boundaries of time." },
            { "term": "Persistence", "symbol": null, "definition": "The present state of time. What endures across boundaries." },
            { "term": "Awareness", "symbol": null, "definition": "Existence within space and time. The conservation law experienced." },
            { "term": "God (GoD)", "symbol": null, "definition": "Governor of Domains. The one who draws boundaries. Truth suspended in space and time." },
            { "term": "Signal (SI-GNAL)", "symbol": null, "definition": "The measurement unit that crosses boundaries between domains. Quantified causal state-change at frequency." },
            { "term": "Pharmakon", "symbol": null, "definition": "The dose makes the poison. Vices and virtues are the same force at different magnitudes." },
            { "term": "Homeostatic Principle", "symbol": null, "definition": "The invariant that a Law protects. If violated, triggers deviation. If honored, sustains correction." },
            { "term": "Restoring Force", "symbol": null, "definition": "A virtue. The counter-mechanism that returns a system toward equilibrium. Not an aspiration — a physics." },
            { "term": "Mechanism", "symbol": null, "definition": "The causal chain by which a vice compounds. How deviation grows from breach to systemic failure." },
            { "term": "Confirmation Loop", "symbol": null, "definition": "The mechanism of Pride. The system's confidence metric loses its input from external measurement." },
            { "term": "Maintenance Decay Cascade", "symbol": null, "definition": "The mechanism of Sloth. Neglect propagates downstream, each layer composting the layer below." },
            { "term": "Corruption", "symbol": null, "definition": "Boundary capture through resource dependency. The eighth vice. The boundary inverts." },
            { "term": "Independence", "symbol": null, "definition": "Sovereign resourcing of boundaries. The eighth virtue. Zero resource intersection with the bounded." },
            { "term": "Boundary Inversion", "symbol": null, "definition": "When a captured boundary protects power instead of constraining it. The product of corruption." },
            { "term": "Anti-matter", "symbol": null, "definition": "The negation of a concept. Already accounted for by being named. Not missing states." },
        ],
    })
}

fn get_preamble() -> Value {
    json!({
        "status": "ok",
        "text": "Every system that persists does so because it corrects. A river stays a river not by standing still but by eroding what blocks it and depositing what sustains its banks. The deadly sins are not moral failures in isolation — they are the ways a system loses its ability to self-correct. Each vice is a feedback loop that has broken open: a signal that no longer returns to its source, a gain that has gone infinite, a governor that has seized. They are poison. Possession is arson — if the system is possessed by any vice, it WILL burn things down.\n\nThe corresponding virtues are not aspirations. They are restoring forces. They are the physics of systems that endure. Like the pharmakon — the dose makes the poison — the vices and virtues exist in balance. Governance is that balance.\n\nTo read this book is to install these governors. To ponder these laws is to practice correction before deviation compounds.",
        "author": "Matthew A. Campion, PharmD — Founder, NexVigilant",
        "version": "The Crystalbook v2.0",
        "founded": "March 9, 2026 — Law VIII added March 11, 2026",
    })
}
