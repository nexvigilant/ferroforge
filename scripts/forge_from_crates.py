#!/usr/bin/env python3
"""
Forge from Crates — Generate Station configs from nexcore-mcp tool dispatch table.

Parses unified.rs + lib.rs to extract all 1,378 MCP tools, groups by domain,
and generates Station configs for uncovered domains. Rust-native proxy by default.

Usage:
  python3 forge_from_crates.py discover          # Show uncovered domains
  python3 forge_from_crates.py generate --dry-run # Preview what would be generated
  python3 forge_from_crates.py generate           # Generate all uncovered configs
  python3 forge_from_crates.py coverage           # Coverage summary
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

FERROFORGE = Path(__file__).parent.parent.resolve()
CONFIGS_DIR = FERROFORGE / "configs"
MCP_SRC = Path.home() / "Projects/Active/nexcore/crates/nexcore-mcp/src"


# ---------------------------------------------------------------------------
# Tool extraction
# ---------------------------------------------------------------------------

def extract_all_tools() -> list[dict]:
    """Extract tool names, descriptions, and module mappings from source."""
    unified = (MCP_SRC / "unified.rs").read_text()
    lib_text = (MCP_SRC / "lib.rs").read_text()

    # 1. All tool names from dispatch: "tool_name" =>
    tool_names = sorted(set(re.findall(r'"(\w+)"\s*=>', unified)))

    # 2. Descriptions from #[tool(description = "...")]
    #    Match: #[tool(description = "desc")] (async)? fn fn_name
    tool_descs = {}
    for m in re.finditer(
        r'#\[tool\(description\s*=\s*"([^"]+)"\)\]\s*(?:async\s+)?fn\s+(\w+)',
        lib_text
    ):
        tool_descs[m.group(2)] = m.group(1)

    # 3. Dispatch mappings: "tool_name" => typed(params, tools::module::function)
    dispatch_map = {}
    for m in re.finditer(
        r'"(\w+)"\s*=>\s*(?:typed|typed_async)\(params,\s*tools::(\w+)::(\w+)\)',
        unified
    ):
        dispatch_map[m.group(1)] = (m.group(2), m.group(3))

    # 4. Also get descriptions from /// doc comments on tool functions in tools/*.rs
    tools_dir = MCP_SRC / "tools"
    fn_docs = {}
    if tools_dir.exists():
        for rs in tools_dir.glob("*.rs"):
            if rs.name == "mod.rs":
                continue
            content = rs.read_text()
            # Match: /// doc comment\npub fn name  or  pub async fn name
            for m in re.finditer(
                r'///\s*(.+?)\n\s*pub\s+(?:async\s+)?fn\s+(\w+)',
                content
            ):
                fn_docs[m.group(2)] = m.group(1).strip()

    # Build tool list
    tools = []
    for name in tool_names:
        desc = ""
        module = ""

        if name in dispatch_map:
            mod_name, fn_name = dispatch_map[name]
            module = mod_name
            # Try descriptions in priority order
            desc = tool_descs.get(fn_name, "") or fn_docs.get(fn_name, "")

        if not desc:
            # Generate description from name
            desc = name.replace("_", " ").title()

        tools.append({"name": name, "description": desc, "module": module})

    return tools


# ---------------------------------------------------------------------------
# Domain grouping
# ---------------------------------------------------------------------------

# Two-segment prefixes that should stay together
TWO_SEGMENT_PREFIXES = {
    "pv_signal", "pv_axioms", "pv_control", "pv_pipeline", "pv_naranjo",
    "pv_who", "pv_chi", "pv_qbri", "pv_core", "pv_embeddings",
    "faers_etl", "faers_signal", "faers_drug", "faers_geographic",
    "faers_outcome", "faers_polypharmacy", "faers_reporter", "faers_seriousness",
    "faers_compare", "faers_search", "faers_disproportionality",
    "game_theory", "edit_distance", "code_tracker",
    "brain_artifact", "brain_session", "brain_coordination", "brain_recovery",
    "brain_sessions", "brain_db",
    "lex_primitiva", "node_hunt", "test_history", "signal_detect",
    "signal_batch", "molecular_weight", "harm_taxonomy", "harm_axiom",
    "graph_layout", "terminal_remote",
    "implicit_find", "implicit_get", "implicit_set", "implicit_patterns", "implicit_stats",
    "skill_chain", "skill_compile", "skill_execute", "skill_categories",
    "skill_orchestration", "skill_search", "skill_token", "skill_taxonomy",
    "skill_dependency", "skill_list", "skill_scan", "skill_get", "skill_validate",
    "stem_bio", "stem_chem", "stem_math", "stem_phys", "stem_spatial",
    "stem_stats", "stem_confidence", "stem_taxonomy", "stem_tier",
    "dot_dispatch", "dot_verify",
    "domain_primitives",
    "compilation_abstraction",
    "pv_signal_chart",
}

# Merge small groups into larger domain groups
MERGE_MAP = {
    # PV tools → group under pv.*
    "pv": "pv", "pv_signal": "pv", "pv_axioms": "pv", "pv_control": "pv",
    "pv_pipeline": "pv", "pv_naranjo": "pv", "pv_who": "pv", "pv_chi": "pv",
    "pv_qbri": "pv", "pv_core": "pv", "pv_embeddings": "pv",
    "pv_signal_chart": "pv",
    # FAERS tools → group under faers
    "faers": "faers", "faers_etl": "faers", "faers_signal": "faers",
    "faers_drug": "faers", "faers_geographic": "faers", "faers_outcome": "faers",
    "faers_polypharmacy": "faers", "faers_reporter": "faers",
    "faers_seriousness": "faers", "faers_compare": "faers",
    "faers_search": "faers", "faers_disproportionality": "faers",
    # Brain tools → group under brain
    "brain": "brain", "brain_artifact": "brain", "brain_session": "brain",
    "brain_coordination": "brain", "brain_recovery": "brain",
    "brain_sessions": "brain", "brain_db": "brain",
    # Implicit → brain
    "implicit": "brain", "implicit_find": "brain", "implicit_get": "brain",
    "implicit_set": "brain", "implicit_patterns": "brain", "implicit_stats": "brain",
    # Skill tools → group under skill
    "skill": "skill", "skill_chain": "skill", "skill_compile": "skill",
    "skill_execute": "skill", "skill_categories": "skill",
    "skill_orchestration": "skill", "skill_search": "skill",
    "skill_token": "skill", "skill_taxonomy": "skill",
    "skill_dependency": "skill", "skill_list": "skill",
    "skill_scan": "skill", "skill_get": "skill", "skill_validate": "skill",
    # STEM → group under stem
    "stem": "stem", "stem_bio": "stem", "stem_chem": "stem",
    "stem_math": "stem", "stem_phys": "stem", "stem_spatial": "stem",
    "stem_stats": "stem", "stem_confidence": "stem",
    "stem_taxonomy": "stem", "stem_tier": "stem",
    # Signal → group under signal
    "signal": "signal", "signal_detect": "signal", "signal_batch": "signal",
    # Primitive tools → group under primitive
    "primitive": "primitive", "lex_primitiva": "primitive",
    "domain_primitives": "primitive",
    # Harm → group under harm
    "harm": "harm", "harm_taxonomy": "harm", "harm_axiom": "harm",
    # Edit distance → edit_distance
    "edit_distance": "edit_distance",
    # VIZ tools
    "viz": "viz",
    # Compilation
    "compilation": "compilation", "compilation_abstraction": "compilation",
    # --- Body Systems (11 prefixes) ---
    "cardio": "body_systems", "circulatory": "body_systems",
    "respiratory": "body_systems", "digestive": "body_systems",
    "nervous": "body_systems", "muscular": "body_systems",
    "skeletal": "body_systems", "lymphatic": "body_systems",
    "urinary": "body_systems", "reproductive": "body_systems",
    "integumentary": "body_systems",
    # --- Learning & Education (3 prefixes) ---
    "learn": "learning", "lesson": "learning",
    # --- Molecular Biology (6 prefixes) ---
    "synapse": "molecular_biology", "transcriptase": "molecular_biology",
    "ribosome": "molecular_biology", "nmd": "molecular_biology",
    "endocytosis": "molecular_biology", "chemotaxis": "molecular_biology",
    # --- Pharmacokinetics (3 prefixes) ---
    "pk": "pharmacokinetics", "clearance": "pharmacokinetics",
    "drug": "pharmacokinetics",
    # --- Regulatory Intelligence (4 prefixes) ---
    "regulatory": "reg_intel", "ich": "reg_intel",
    "guidelines": "reg_intel", "fhir": "reg_intel",
    # --- Dev Toolchain (many small prefixes) ---
    "build": "devtools", "crate": "devtools", "docs": "devtools",
    "mcp": "devtools", "config": "devtools", "hook": "devtools",
    "tool": "devtools", "toolbox": "devtools", "command": "devtools",
    "help": "devtools", "analyze": "devtools", "audit": "devtools",
    "compare": "devtools", "compress": "devtools", "drop": "devtools",
    "mine": "devtools", "score": "devtools",
    # --- Governance & Principles (4 prefixes) ---
    "commandment": "governance", "principles": "governance",
    "ccim": "governance", "integrity": "governance",
    # --- Graph & Topology (5 prefixes) ---
    "graph": "graph_ops", "graph_layout": "graph_ops",
    "dag": "graph_ops", "topo": "graph_ops", "aggregate": "graph_ops",
    # --- Monitoring & Observability (4 prefixes) ---
    "monitoring": "ops_monitoring", "observability": "ops_monitoring",
    "sentinel": "ops_monitoring", "drift": "ops_monitoring",
    # --- Quality & Validation (5 prefixes) ---
    "quality": "quality_engine", "validify": "quality_engine",
    "rank": "quality_engine", "rate": "quality_engine",
    # --- Security (4 prefixes) ---
    "secure": "security", "dhs": "security", "fence": "security",
    # --- Government & Federal (7 prefixes) ---
    "fed": "government", "gsa": "government", "nsf": "government",
    "sba": "government", "ssa": "government", "sec": "government",
    "treasury": "government",
    # --- Temporal (2 prefixes) ---
    "chrono": "temporal",
    # --- Agent Intelligence (5 prefixes) ---
    "crew": "agent_intel", "hitl": "agent_intel",
    "model": "agent_intel", "reason": "agent_intel",
    "causality": "agent_intel",
    # --- Communication & Chat (3 prefixes) ---
    "comm": "comm_engine", "prompt": "comm_engine",
    # nexchat stays as its own domain
    # --- Foundry & Ghost (2 prefixes) ---
    "ghost": "foundry",
    # --- Organization & Management (3 prefixes) ---
    "organize": "org_mgmt", "pom": "org_mgmt", "prima": "org_mgmt",
    # --- Content & Brand (3 prefixes) ---
    "brand": "content", "declension": "content",
    # disney stays as its own domain
    # --- Code Analysis (3 prefixes) ---
    "code": "code_analysis", "code_tracker": "code_analysis", "ast": "code_analysis",
    # --- Antibody → immunity (already exists) ---
    "antibody": "immunity",
    # --- CCP & Retro → process_control ---
    "ccp": "process_control", "retro": "process_control",
    # --- CCCP → existing compliance merge ---
    "cccp": "compliance",
    # --- Compounding & Polymer ---
    "polymer": "compounding",
    # --- Adversarial & Antitransformer ---
    "antitransformer": "adversarial",
    # --- Caesura & Vocab → linguistics ---
    "caesura": "linguistics", "vocab": "linguistics",
    # --- Explore → frontier ---
    "explore": "frontier",
    # --- Dot ops (2 prefixes) ---
    "dot_dispatch": "dot_ops", "dot_verify": "dot_ops",
    # --- Game theory standalone ---
    "game_theory": "game_theory_standalone",
    # --- Entropy ---
    "entropy": "entropy_calc",
    # --- Nexcore meta ---
    "nexcore": "nexcore_meta",
    # --- API & HTTP ---
    "api": "api_ops",
    # --- Retrieval ---
    "retrieval": "retrieval",
    # --- Standalone prefixes (1-tool each, merge into nearest) ---
    "career": "ksb",
    "ca": "compliance",
    "get": "devtools",
    "primitives": "primitive",
    "adversarial": "adversarial",
    # --- MW (molecular weight standalone prefix) ---
    "mw": "mw",
    # --- Statemind ---
    "statemind": "statemind",
}


def group_tools(tools: list[dict]) -> dict[str, list[dict]]:
    """Group tools by domain prefix, merging related prefixes."""
    raw_groups = defaultdict(list)

    for tool in tools:
        name = tool["name"]
        parts = name.split("_")

        # Try 2-segment prefix
        if len(parts) >= 2:
            prefix2 = f"{parts[0]}_{parts[1]}"
            if prefix2 in TWO_SEGMENT_PREFIXES:
                raw_groups[prefix2].append(tool)
                continue

        raw_groups[parts[0]].append(tool)

    # Merge related groups
    merged = defaultdict(list)
    for prefix, group_tools_list in raw_groups.items():
        target = MERGE_MAP.get(prefix, prefix)
        merged[target].extend(group_tools_list)

    return dict(merged)


# ---------------------------------------------------------------------------
# Domain metadata
# ---------------------------------------------------------------------------

DOMAIN_META = {
    "pv": ("pv-compute.nexvigilant.com", "PV Compute Engine", "Signal detection (PRR/ROR/IC/EBGM), causality assessment (Naranjo/WHO-UMC), benefit-risk scoring, and PV pipeline orchestration"),
    "faers": ("faers.nexvigilant.com", "FAERS Intelligence", "FDA Adverse Event Reporting System — search, analytics, signal detection, geographic divergence, and polypharmacy analysis"),
    "brain": ("brain.nexvigilant.com", "Brain Working Memory", "Session management, artifact persistence, implicit learning, coordination, and recovery"),
    "guardian": ("guardian.nexvigilant.com", "Guardian Safety Engine", "Homeostatic safety monitoring — sensors, actuators, threat assessment, PV control loop"),
    "vigil": ("vigil.nexvigilant.com", "Vigil Command", "CAIO authority, health monitoring, memory search, event emission, and system control"),
    "skill": ("skills.nexvigilant.com", "Skill Engine", "Skill discovery, compilation, execution, chain lookup, taxonomy, and token analysis"),
    "stem": ("stem.nexvigilant.com", "STEM Computation", "Mathematics, physics, chemistry, biology, statistics, spatial analysis, and taxonomy"),
    "chemistry": ("chemistry.nexvigilant.com", "Chemistry Operations", "Reaction kinetics, equilibrium, thermodynamics, buffer capacity, and PV chemistry mappings"),
    "wolfram": ("wolfram.nexvigilant.com", "Wolfram Alpha", "Wolfram Alpha calculations — astronomy, chemistry, physics, finance, linguistics, and data lookup"),
    "viz": ("observatory.nexvigilant.com", "Observatory 3D Visualization", "Molecular rendering, network visualization, manifold sampling, spectral analysis, and force-field computation"),
    "forge": ("forge.nexvigilant.com", "Code Forge", "Code generation, scaffolding, compilation, quality scoring, and Nash equilibrium solving"),
    "signal": ("signal-detection.nexvigilant.com", "Signal Detection Pipeline", "Batch signal processing, threshold management, detection workflows, and fence validation"),
    "chem": ("chemivigilance.nexvigilant.com", "Chemivigilance", "Structural alerts, SMILES parsing, toxicity prediction, metabolite prediction, and molecular similarity"),
    "gcloud": ("gcloud.nexvigilant.com", "Google Cloud Operations", "Compute, storage, IAM, Cloud Run, secrets, and logging management"),
    "knowledge": ("knowledge.nexvigilant.com", "Knowledge Engine", "Knowledge ingestion, extraction, compression, querying, vault management, and concept compilation"),
    "foundation": ("foundation.nexvigilant.com", "Foundation Primitives", "Concept grep, fuzzy search, graph operations, Levenshtein distance, and hash utilities"),
    "epidemiology": ("epidemiology.nexvigilant.com", "Epidemiology", "Incidence rates, odds ratios, relative risk, Kaplan-Meier, NNT/NNH, and attributable fractions"),
    "mesh": ("mesh.nexvigilant.com", "MeSH Terminology", "Medical Subject Headings lookup, hierarchy navigation, PubMed enrichment, and cross-referencing"),
    "stoichiometry": ("stoichiometry.nexvigilant.com", "Stoichiometry", "Chemical equation balancing, encoding, decoding, isomer detection, and mass-state calculation"),
    "comb": ("combinatorics.nexvigilant.com", "Combinatorics", "Binomial, multinomial, Catalan numbers, derangements, Josephus problem, and grid paths"),
    "preemptive": ("preemptive-pv.nexvigilant.com", "Preemptive PV", "Gibbs free energy, noise analysis, intervention planning, severity assessment, and trajectory modeling"),
    "dna": ("dna.nexvigilant.com", "DNA Computation", "Codon tables, sequence alignment, translation, evolution simulation, and assembly"),
    "dtree": ("dtree.nexvigilant.com", "Decision Trees", "Training, prediction, pruning, feature importance, and export of decision tree models"),
    "dataframe": ("dataframe.nexvigilant.com", "DataFrame Operations", "Create, describe, filter, group-by, join, select, sort, and aggregate tabular data"),
    "relay": ("relay.nexvigilant.com", "Relay Verification", "Chain verification, core detection, fidelity composition, and PV pipeline relay tracking"),
    "edit_distance": ("edit-distance.nexvigilant.com", "Edit Distance", "Levenshtein compute, batch comparison, similarity scoring, and traceback alignment"),
    "zeta": ("zeta.nexvigilant.com", "Zeta Function", "Riemann zeta evaluation, zero finding, GUE comparison, and RH verification"),
    "tov": ("tov.nexvigilant.com", "Theory of Vigilance", "ToV axiom computation — epistemic trust, stability shells, signal strength, and grounded proofs"),
    "harm": ("harm-taxonomy.nexvigilant.com", "Harm Taxonomy", "Harm type classification (A-H), axiom connections, manifestation levels, and exhaustiveness verification"),
    "primitive": ("primitives.nexvigilant.com", "Primitives & Lex Primitiva", "T1 primitive scanning, validation, brain operations, Lex Primitiva composition and decomposition"),
    "algovigil": ("algovigilance.nexvigilant.com", "Algovigilance", "AI/ML safety — dedup batch processing, triage queue, decay management, and reinforcement"),
    "compliance": ("compliance.nexvigilant.com", "Compliance Assessment", "ICH catalog, exclusion checking, and regulatory compliance assessment"),
    "immunity": ("immunity.nexvigilant.com", "Immune System", "Antibody scanning, immunity proposals, and immune defense pattern detection"),
    "energy": ("energy.nexvigilant.com", "Energy Management", "Waste analysis, regime classification, energy charge computation, and temporal metrics"),
    "markov": ("markov.nexvigilant.com", "Markov Chains", "Markov chain analysis and data-driven chain construction"),
    "molecular_weight": ("molecular-weight.nexvigilant.com", "Molecular Weight", "Molecular weight computation, comparison, periodic table, and transfer prediction"),
    "marketing": ("marketing.nexvigilant.com", "Marketing Intelligence", "Capability discovery, quick demos, value chain analysis, and onboarding"),
    "edu": ("education.nexvigilant.com", "PV Education", "Agent training, competency evaluation, and educational assessment"),
    "pharma": ("pharma.nexvigilant.com", "Pharma Intelligence", "Drug profiles, boxed warnings, pipeline tracking, and competitive analysis"),
    "cloud": ("cloud.nexvigilant.com", "Cloud Infrastructure", "Anomaly detection, autoscaling, deployment, monitoring, and cost optimization"),
    "kellnr": ("kellnr.nexvigilant.com", "Kellnr Crate Registry", "Private crate registry — package management, dependency graphs, and signal analysis"),
    "fda": ("fda.nexvigilant.com", "FDA Intelligence", "FDA guidance, risk assessment, metrics, and bridge evaluation"),
    "openfda": ("openfda.nexvigilant.com", "OpenFDA Analytics", "Device events, drug labels, recalls, and adverse event search"),
    "nlm": ("nlm.nexvigilant.com", "NLM NotebookLM", "Notebook management, source operations, and knowledge synthesis"),
    "insight": ("insight.nexvigilant.com", "Insight Engine", "Compression, decompression, gap analysis, and insight mining"),
    "anatomy": ("anatomy.nexvigilant.com", "Anatomy System", "Blast radius analysis, coverage mapping, and system anatomy"),
    "audio": ("audio.nexvigilant.com", "Audio Processing", "Codec catalog, noise analysis, synthesis, and audio pipeline"),
    "cognition": ("cognition.nexvigilant.com", "Cognitive Analysis", "Pattern analysis, reasoning evaluation, and cognitive load assessment"),
    "trial": ("trial.nexvigilant.com", "Clinical Trials", "Adaptive design, safety monitoring, endpoint analysis, and trial management"),
    "trust": ("trust.nexvigilant.com", "Trust Engine", "Trust decisions, calibration, evidence weighting, and confidence scoring"),
    "pipeline": ("pipeline.nexvigilant.com", "Signal Pipeline", "Batch compute, priority routing, enrichment, and pipeline orchestration"),
    "highway": ("highway.nexvigilant.com", "Highway Safety", "Route integrity, classification, safety verification, and CAP-019 compliance"),
    "word": ("word.nexvigilant.com", "Word Processing", "Alignment, formatting, analysis, and document operations"),
    "compilation": ("compilation.nexvigilant.com", "Compilation Space", "Abstraction levels, space analysis, and compilation optimization"),
    "rust": ("rust-dev.nexvigilant.com", "Rust Development", "Borrow checking, lifetime analysis, ownership patterns, and Rust guidance"),
    "registry": ("registry.nexvigilant.com", "Registry Operations", "Assessment, validation, and registry management"),
    "engram": ("engram.nexvigilant.com", "Engram Memory", "Source-based retrieval, pattern storage, and memory consolidation"),
    "jeopardy": ("jeopardy.nexvigilant.com", "Jeopardy Analysis", "Board control, value analysis, and strategic decision-making"),
    "sos": ("sos.nexvigilant.com", "SOS System", "System audit, health checks, and operational readiness"),
    "adventure": ("adventure.nexvigilant.com", "Adventure Engine", "Skill development, milestone tracking, and gamified learning"),
    "telemetry": ("telemetry.nexvigilant.com", "Telemetry Intelligence", "Source analysis, governance crossref, evolution snapshots, and Intel reports"),
    "watchtower": ("watchtower.nexvigilant.com", "Watchtower Monitoring", "Session analysis, symbol audit, Gemini stats, and unified monitoring"),
    "cargo": ("cargo.nexvigilant.com", "Cargo Build", "Build, test, clippy, fmt, and dependency tree operations"),
    "git": ("git.nexvigilant.com", "Git Operations", "Status, diff, log, branch, checkout, commit, push, and stash"),
    "cytokine": ("cytokine.nexvigilant.com", "Cytokine Signaling", "Cytokine emission, families, and immune signaling status"),
    "hormone": ("hormone.nexvigilant.com", "Hormone System", "Hormonal stimulus-response, modifiers, and status monitoring"),
    "flywheel": ("flywheel.nexvigilant.com", "Flywheel Engine", "Cascade execution, event flow, and flywheel velocity tracking"),
    "jupyter": ("jupyter.nexvigilant.com", "Jupyter Operations", "Kernel management, notebook execution, and pipeline orchestration"),
    "cep": ("cep.nexvigilant.com", "Concept Extraction", "Primitive extraction, classification, domain translation, and pipeline execution"),
    "cortex": ("cortex.nexvigilant.com", "Cortex AI Models", "Model management, inference, and AI model orchestration"),
    "reddit": ("reddit.nexvigilant.com", "Reddit Integration", "Authentication, subreddit monitoring, and social signal extraction"),
    "oracle": ("oracle.nexvigilant.com", "Oracle Knowledge", "Knowledge ingestion, prediction, and oracle consultation"),
    "grounded": ("grounded.nexvigilant.com", "Grounded Reasoning", "Composition, decomposition, and grounded analysis"),
    "compound": ("compound.nexvigilant.com", "Compound Registry", "Chemical compound registration, caching, and detection"),
    "gsheets": ("gsheets.nexvigilant.com", "Google Sheets", "Spreadsheet operations — append, read, create, and formula execution"),
    "station": ("station.nexvigilant.com", "Station Management", "Tool addition, configuration, and station operations"),
    "frontier": ("frontier.nexvigilant.com", "Exploration Frontier", "Mission launch, discovery recording, and frontier tracking"),
    "node_hunt": ("node-hunt.nexvigilant.com", "Node Hunter", "Isolated node detection, dependency scanning, and orphan identification"),
    "perplexity": ("perplexity.nexvigilant.com", "Perplexity Search", "Competitive analysis, regulatory search, and research queries"),
    "user": ("user.nexvigilant.com", "User Management", "Authentication, profile management, and user operations"),
    "measure": ("measure.nexvigilant.com", "Measurement Engine", "Comparison, impact assessment, and metric tracking"),
    "validation": ("validation.nexvigilant.com", "Validation Engine", "Test classification, domain validation, and quality checks"),
    "transform": ("transform.nexvigilant.com", "Transform Engine", "Profile management, plan compilation, segmentation, and fidelity scoring"),
    "health": ("health.nexvigilant.com", "Health Assessment", "Impact measurement, signal validation, and health scoring"),
    # --- Body Systems (11 prefixes merged) ---
    "body_systems": ("body-systems.nexvigilant.com", "Body Systems", "Organ system modeling — cardiovascular, circulatory, respiratory, digestive, nervous, muscular, skeletal, lymphatic, urinary, reproductive, and integumentary"),
    # --- Learning & Education (3 prefixes merged) ---
    "learning": ("learning.nexvigilant.com", "Learning Engine", "Learning DAG resolution, lesson planning, competency progression, and educational content management"),
    # --- Claude AI Platform ---
    "claude": ("claude-ai.nexvigilant.com", "Claude AI Platform", "Claude.ai project management, conversation search, organization listing, and message operations"),
    # --- Molecular Biology (6 prefixes merged) ---
    "molecular_biology": ("molecular-biology.nexvigilant.com", "Molecular Biology", "Synaptic signaling, transcriptase activity, ribosome assembly, nonsense-mediated decay, endocytosis, and chemotaxis modeling"),
    # --- Pharmacokinetics (3 prefixes merged) ---
    "pharmacokinetics": ("pharmacokinetics.nexvigilant.com", "Pharmacokinetics", "PK modeling, drug clearance computation, ADME parameters, and drug interaction profiling"),
    # --- Regulatory Intelligence (4 prefixes merged) ---
    "reg_intel": ("reg-intel.nexvigilant.com", "Regulatory Intelligence", "ICH guideline lookup, regulatory primitive extraction, FHIR interoperability, and guideline search"),
    # --- PVDSL ---
    "pvdsl": ("pvdsl.nexvigilant.com", "PV Domain-Specific Language", "PVDSL compilation, evaluation, execution, and function reference"),
    # --- Dev Toolchain (10 prefixes merged) ---
    "devtools": ("devtools.nexvigilant.com", "Developer Toolchain", "Build orchestration, crate scaffolding, documentation generation, MCP server management, config validation, hook testing, tool discovery, and CLI help"),
    # --- Governance & Principles (4 prefixes merged) ---
    "governance": ("governance.nexvigilant.com", "Governance Engine", "Commandment enforcement, principle lookup, CCIM evaluation, and integrity analysis"),
    # --- Graph & Topology (5 prefixes merged) ---
    "graph_ops": ("graph-ops.nexvigilant.com", "Graph Operations", "Graph layout, DAG topological sort, topology analysis, aggregate computation, and network structure analysis"),
    # --- Monitoring & Observability (4 prefixes merged) ---
    "ops_monitoring": ("ops-monitoring.nexvigilant.com", "Operations Monitoring", "Drift detection, sentinel alerting, observability metrics, and system monitoring dashboards"),
    # --- Quality & Validation (5 prefixes merged) ---
    "quality_engine": ("quality-engine.nexvigilant.com", "Quality Engine", "Quality scoring, validation checks, ranking algorithms, rate computation, and validify gate assessment"),
    # --- Security & Compliance (4 prefixes merged) ---
    "security": ("security.nexvigilant.com", "Security Operations", "Security scanning, access control, DHS boundary verification, and fence perimeter validation"),
    # --- Government & Federal (7 prefixes merged) ---
    "government": ("government.nexvigilant.com", "Government Intelligence", "Federal budget analysis, GSA procurement, NSF research funding, SBA agent allocation, SSA state integrity, SEC market audit, and Treasury analysis"),
    # --- Temporal & Chronology (2 prefixes merged) ---
    "temporal": ("temporal.nexvigilant.com", "Temporal Analysis", "Chronological tracking, temporal metrics, time-series analysis, and sequence ordering"),
    # --- Agent Intelligence (5 prefixes merged) ---
    "agent_intel": ("agent-intel.nexvigilant.com", "Agent Intelligence", "Crew orchestration, human-in-the-loop coordination, state machine reasoning, model selection, and causal inference"),
    # --- Communication & Chat (3 prefixes merged) ---
    "comm_engine": ("comm-engine.nexvigilant.com", "Communication Engine", "Protocol recommendation, message routing, chat operations, and prompt engineering"),
    # --- Assembly & Low-Level (1 prefix) ---
    "asm": ("asm.nexvigilant.com", "Assembly Engine", "Assembly instruction analysis, register allocation, opcode mapping, and low-level computation modeling"),
    # --- Foundry & Ghost (2 prefixes merged) ---
    "foundry": ("foundry.nexvigilant.com", "Foundry Intelligence", "Artifact validation, cascade verification, inference rendering, VDAG ordering, and ghost pattern detection"),
    # --- Organization & Management (3 prefixes merged) ---
    "org_mgmt": ("org-mgmt.nexvigilant.com", "Organization Management", "Organizational structuring, POM dependency management, and prima facie assessment"),
    # --- Content & Brand (3 prefixes merged) ---
    "content": ("content.nexvigilant.com", "Content Engine", "Brand decomposition, semantic tiering, declension analysis, and creative content generation"),
    # --- Vault & Storage ---
    "vault": ("vault.nexvigilant.com", "Vault Storage", "Encrypted vault management, secure storage, retrieval, and access control"),
    # --- Code Analysis (3 prefixes merged) ---
    "code_analysis": ("code-analysis.nexvigilant.com", "Code Analysis", "AST querying, code change tracking, static analysis, and implementor search"),
    # --- Vigilance Domain (1 prefix — distinct from vigil) ---
    "vigilance": ("vigilance-domain.nexvigilant.com", "Vigilance Domain", "Harm type classification, risk scoring, safety margin computation, and ToV mapping"),
    # --- Value Assessment (1 prefix) ---
    "value": ("value.nexvigilant.com", "Value Assessment", "Baseline creation, PV value mapping, signal detection, and signal type classification"),
    # --- CCP & Retro (2 prefixes merged) ---
    "process_control": ("process-control.nexvigilant.com", "Process Control", "Critical control point management, retrospective analysis, and process verification"),
    # --- NCBI & Life Sciences (1 prefix) ---
    "ncbi": ("ncbi.nexvigilant.com", "NCBI Life Sciences", "NCBI database querying, genomic data retrieval, and bioinformatics integration"),
    # --- Clinical Validation (1 prefix — CTVP) ---
    "ctvp": ("ctvp.nexvigilant.com", "Clinical Trial Validation", "Five-problem protocol scoring, phase listing, and CTVP validation assessment"),
    # --- Compounding & Polymer (2 prefixes merged) ---
    "compounding": ("compounding.nexvigilant.com", "Compounding Engine", "Capability compounding, polymer chain composition, and compound growth tracking"),
    # --- Adversarial & Antitransformer (2 prefixes merged) ---
    "adversarial": ("adversarial.nexvigilant.com", "Adversarial Analysis", "Adversarial testing, antitransformer validation, and robustness assessment"),
    # --- Caesura & Linguistics ---
    "linguistics": ("linguistics.nexvigilant.com", "Linguistic Analysis", "Caesura detection, vocabulary lookup, skill-word mapping, and linguistic pattern analysis"),
    # --- KSB Competency ---
    "ksb": ("ksb.nexvigilant.com", "KSB Competency", "Knowledge-skill-behavior assessment, integrity calibration, and competency framework evaluation"),
    # --- Pharos Reporting ---
    "pharos": ("pharos.nexvigilant.com", "Pharos Reporting", "Pharos intelligence reports, status monitoring, and analysis pipeline execution"),
    # --- Explore & Frontier (merge explore into frontier) ---
    # (explore merges into frontier via MERGE_MAP)
    # --- Disney Creative ---
    "disney": ("disney.nexvigilant.com", "Disney Creative", "Character narrative analysis, episode overview, storyline arcs, and creative content intelligence"),
    # --- Phenotype & Molecular ---
    "phenotype": ("phenotype.nexvigilant.com", "Phenotype Analysis", "Phenotype classification, molecular characterization, and genotype-phenotype correlation"),
    # --- Voila Rendering ---
    "voila": ("voila.nexvigilant.com", "Voila Rendering", "Notebook rendering, interactive dashboard deployment, and Voila server management"),
    # --- Lab & Experimentation ---
    "lab": ("lab.nexvigilant.com", "Lab Operations", "Batch experiments, comparison studies, reaction modeling, and laboratory pipeline execution"),
    # --- Molecular (standalone, not molecular_weight) ---
    "molecular": ("molecular.nexvigilant.com", "Molecular Analysis", "Molecular property computation, weight estimation, structural analysis, and molecular comparison"),
    # --- Diagram & Visual ---
    "diagram": ("diagram.nexvigilant.com", "Diagram Rendering", "Diagram generation, visual rendering, and structural visualization"),
    # --- Phase4 Post-Market ---
    "phase4": ("phase4.nexvigilant.com", "Phase 4 Surveillance", "Post-marketing surveillance, real-world evidence collection, and safety signal monitoring"),
    # --- Dot Dispatch & Verify (2 prefixes merged) ---
    "dot_ops": ("dot-ops.nexvigilant.com", "Dot Operations", "Highway dispatch manifests and highway verification operations"),
    # --- Test History ---
    "test_history": ("test-history.nexvigilant.com", "Test History", "Flaky test detection, test result querying, and historical test analysis"),
    # --- NexChat ---
    "nexchat": ("nexchat.nexvigilant.com", "NexChat", "Real-time chat operations, message handling, and conversational AI integration"),
    # --- Statemind ---
    "statemind": ("statemind.nexvigilant.com", "Statemind Engine", "State machine reasoning, mind-state tracking, and cognitive state management"),
    # --- Entropy ---
    "entropy_calc": ("entropy-calc.nexvigilant.com", "Entropy Calculator", "Information entropy computation, Shannon entropy, and disorder measurement"),
    # --- Game Theory (standalone tools not in forge) ---
    "game_theory_standalone": ("game-theory-standalone.nexvigilant.com", "Game Theory", "Nash equilibrium computation for standalone game-theoretic analysis"),
    # --- Singleton utility tools (merged into devtools via MERGE_MAP) ---
    # analyze, audit, career, command, compare, compress, config, drop, help, mine, score, toolbox
    # are all merged into devtools
    # --- Nexcore meta ---
    "nexcore_meta": ("nexcore-meta.nexvigilant.com", "NexCore Meta", "NexCore health probes, system status, and meta-information endpoints"),
    # --- API & HTTP ---
    "api_ops": ("api-ops.nexvigilant.com", "API Operations", "API health checks, route listing, and HTTP request handling"),
    # --- Retrieval & Search ---
    "retrieval": ("retrieval.nexvigilant.com", "Retrieval Engine", "Information retrieval, search operations, and knowledge recall"),
    # --- MW (Molecular Weight standalone) ---
    "mw": ("mw.nexvigilant.com", "Molecular Weight Tools", "Molecular weight computation, comparison, periodic table lookup, and property analysis"),
    # --- QBR (benefit-risk) ---
    "qbr": ("qbr.nexvigilant.com", "Quantitative Benefit-Risk", "QBR scoring, benefit-risk computation, and therapeutic window analysis"),
    # --- Visual ---
    "visual": ("visual.nexvigilant.com", "Visual Intelligence", "Visual rendering, image analysis, and graphical output generation"),
    # --- SQI (signal quality) ---
    "sqi": ("sqi.nexvigilant.com", "Signal Quality Index", "Signal quality measurement, index computation, and quality assessment"),
}

# Private domains (dev/ops tools, not PV-facing)
PRIVATE_DOMAINS = {
    "cargo.nexvigilant.com", "git.nexvigilant.com", "npm.nexvigilant.com",
    "gcloud.nexvigilant.com", "github.nexvigilant.com", "hooks.nexvigilant.com",
    "config.nexvigilant.com", "ast.nexvigilant.com", "crate-dev.nexvigilant.com",
    "daemon.nexvigilant.com", "test-history.nexvigilant.com",
    "node-hunt.nexvigilant.com", "diagram.nexvigilant.com",
    "jupyter.nexvigilant.com", "reddit.nexvigilant.com",
    "gsheets.nexvigilant.com", "nlm.nexvigilant.com",
    "user.nexvigilant.com", "cortex.nexvigilant.com",
    "station.nexvigilant.com", "kellnr.nexvigilant.com",
    "devtools.nexvigilant.com", "code-analysis.nexvigilant.com",
    "dot-ops.nexvigilant.com", "nexcore-meta.nexvigilant.com",
    "api-ops.nexvigilant.com",
}


def get_existing_domains() -> set[str]:
    domains = set()
    for f in CONFIGS_DIR.glob("*.json"):
        c = json.load(open(f))
        domains.add(c["domain"])
    return domains


def tool_to_config(tool: dict) -> dict:
    """Convert tool dict to Station config tool entry."""
    name = tool["name"].replace("_", "-")
    return {
        "name": name,
        "description": tool["description"],
        "parameters": [],  # Rust-native tools get params from typed structs
        "outputSchema": {
            "type": "object",
            "properties": {"status": {"type": "string", "description": "ok | error"}},
            "required": ["status"]
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    }


def generate_config(prefix: str, tools: list[dict]) -> dict | None:
    """Generate Station config for a domain group."""
    if prefix not in DOMAIN_META:
        return None

    domain, title, description = DOMAIN_META[prefix]

    return {
        "domain": domain,
        "url_pattern": "/*",
        "title": title,
        "description": description,
        "tools": [tool_to_config(t) for t in sorted(tools, key=lambda t: t["name"])],
        "proxy": "rust-native",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_discover(args):
    print("Extracting from nexcore-mcp source...")
    tools = extract_all_tools()
    groups = group_tools(tools)
    existing = get_existing_domains()

    covered = []
    uncovered = []

    for prefix in sorted(groups.keys(), key=lambda k: -len(groups[k])):
        n = len(groups[prefix])
        if prefix in DOMAIN_META:
            domain = DOMAIN_META[prefix][0]
            if domain in existing:
                covered.append((prefix, domain, n))
            else:
                uncovered.append((prefix, domain, n))
        else:
            uncovered.append((prefix, f"({prefix}).nexvigilant.com", n))

    print(f"\n{len(tools)} tools, {len(groups)} domain groups\n")

    print(f"Already in Station ({len(covered)} groups):")
    for pfx, dom, n in covered:
        print(f"  {dom:45s} {n:4d} tools")

    print(f"\nUncovered ({len(uncovered)} groups, {sum(n for _, _, n in uncovered)} tools):")
    for pfx, dom, n in uncovered:
        priv = " [private]" if dom in PRIVATE_DOMAINS else ""
        mapped = "✓" if pfx in DOMAIN_META else "?"
        print(f"  {mapped} {dom:43s} {n:4d} tools{priv}")


def cmd_generate(args):
    print("Extracting from nexcore-mcp source...")
    tools = extract_all_tools()
    groups = group_tools(tools)
    existing = get_existing_domains()

    generated = 0
    total_tools = 0
    skipped_no_meta = []

    for prefix in sorted(groups.keys(), key=lambda k: -len(groups[k])):
        if prefix not in DOMAIN_META:
            skipped_no_meta.append((prefix, len(groups[prefix])))
            continue

        domain, title, _ = DOMAIN_META[prefix]
        if domain in existing and not args.overwrite:
            continue

        is_private = domain in PRIVATE_DOMAINS
        config = generate_config(prefix, groups[prefix])
        if not config:
            continue

        if is_private:
            config["private"] = True

        # Filename
        fname = domain.replace(".nexvigilant.com", "") + ".json"
        config_path = CONFIGS_DIR / fname

        if args.dry_run:
            priv = " [private]" if is_private else ""
            print(f"  WOULD {fname:40s} {len(config['tools']):4d} tools{priv}")
        else:
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
                f.write("\n")
            priv = " [private]" if is_private else ""
            print(f"  WROTE {fname:40s} {len(config['tools']):4d} tools{priv}")

        generated += 1
        total_tools += len(config["tools"])

    action = "Would generate" if args.dry_run else "Generated"
    print(f"\n{action} {generated} configs, {total_tools} tools")

    if skipped_no_meta:
        print(f"\nSkipped {len(skipped_no_meta)} unmapped prefixes ({sum(n for _, n in skipped_no_meta)} tools):")
        for pfx, n in sorted(skipped_no_meta, key=lambda x: -x[1])[:15]:
            print(f"  {pfx:25s} {n:4d} tools")


def cmd_coverage(args):
    tools = extract_all_tools()
    groups = group_tools(tools)
    existing = get_existing_domains()

    covered = sum(len(v) for k, v in groups.items()
                  if k in DOMAIN_META and DOMAIN_META[k][0] in existing)
    total = len(tools)
    pct = (covered / total * 100) if total else 0

    print(f"MCP tools: {total}")
    print(f"Station coverage: {covered}/{total} ({pct:.0f}%)")
    print(f"Existing configs: {len(list(CONFIGS_DIR.glob('*.json')))}")


def main():
    parser = argparse.ArgumentParser(description="Forge from Crates")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("discover", help="Show uncovered tool domains")

    gen = sub.add_parser("generate", help="Generate configs for uncovered domains")
    gen.add_argument("--overwrite", action="store_true")
    gen.add_argument("--dry-run", action="store_true")

    sub.add_parser("coverage", help="Coverage summary")

    args = parser.parse_args()
    if args.command == "discover":
        cmd_discover(args)
    elif args.command == "generate":
        cmd_generate(args)
    elif args.command == "coverage":
        cmd_coverage(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
