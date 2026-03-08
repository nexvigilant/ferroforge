#!/usr/bin/env python3
"""
Primitives Proxy — T1 Lex Primitiva concept analysis tools.

Usage:
    echo '{"tool": "analyze-nothing", "args": {"concept": "PV signal detection"}}' | python3 primitives_proxy.py

15 axiomatic primitives. Each tool analyzes a concept through one primitive
lens, returning structured decomposition with properties and failure modes.
Pure computation — no external APIs. Reads a single JSON object from stdin,
dispatches to the appropriate handler, writes JSON to stdout.
"""

import json
import sys

# ── Primitive definitions (source: T1-PRIMITIVES.md) ──

PRIMITIVES = {
    "nothing": {
        "name": "Nothing",
        "symbol": "∅",
        "tier": "ground-prime",
        "description": "Meaningful absence — what is missing defines what is present",
    },
    "state": {
        "name": "State",
        "symbol": "ς",
        "tier": "ground-prime",
        "description": "Observable condition at time t — what can change",
    },
    "boundary": {
        "name": "Boundary",
        "symbol": "∂",
        "tier": "ground-prime",
        "description": "Where things begin and end — creates identity",
    },
    "existence": {
        "name": "Existence",
        "symbol": "∃",
        "tier": "composite",
        "description": "Conservation law: ∃ = ∂(×(ς, ∅))",
    },
    "causality": {
        "name": "Causality",
        "symbol": "→",
        "tier": "operational-prime",
        "description": "Cause-effect chains — every function, every consequence",
    },
    "comparison": {
        "name": "Comparison",
        "symbol": "κ",
        "tier": "operational-prime",
        "description": "Equality, ordering, matching — the universal primitive",
    },
    "quantity": {
        "name": "Quantity",
        "symbol": "N",
        "tier": "dimensional-prime",
        "description": "What is countable — Peano construction: zero + successor",
    },
    "sequence": {
        "name": "Sequence",
        "symbol": "σ",
        "tier": "dimensional-prime",
        "description": "Ordering, dependencies, iteration — what comes before what",
    },
    "mapping": {
        "name": "Mapping",
        "symbol": "μ",
        "tier": "dimensional-prime",
        "description": "Transformation between domains — the bridge between worlds",
    },
    "recursion": {
        "name": "Recursion",
        "symbol": "ρ",
        "tier": "composite",
        "description": "Self-reference — does the structure contain itself?",
    },
    "frequency": {
        "name": "Frequency",
        "symbol": "ν",
        "tier": "composite",
        "description": "Rate, rhythm, repetition — how often does it occur?",
    },
    "persistence": {
        "name": "Persistence",
        "symbol": "π",
        "tier": "composite",
        "description": "What endures — state that survives its context",
    },
    "location": {
        "name": "Location",
        "symbol": "λ",
        "tier": "dimensional-prime",
        "description": "Address, reference, path — where is it?",
    },
    "irreversibility": {
        "name": "Irreversibility",
        "symbol": "∝",
        "tier": "composite",
        "description": "Entropy direction — can it be undone?",
    },
    "sum": {
        "name": "Sum",
        "symbol": "Σ",
        "tier": "composite",
        "description": "Disjoint union — which variant? Is enumeration complete?",
    },
}


def _base(primitive_key: str, args: dict, extra: dict) -> dict:
    """Build a standardized response for a primitive analysis."""
    p = PRIMITIVES[primitive_key]
    result = {
        "status": "ok",
        "primitive": p["name"],
        "symbol": p["symbol"],
        "tier": p["tier"],
        "description": p["description"],
        "properties": {
            "tier": p["tier"],
            "is_prime": "prime" in p["tier"],
            "conservation_role": _conservation_role(primitive_key),
        },
        "failure_modes": _failure_modes(primitive_key),
    }
    result.update(extra)
    return result


def _conservation_role(key: str) -> str:
    """Return the primitive's role in the conservation law ∃ = ∂(×(ς, ∅))."""
    roles = {
        "nothing": "input conservitor (∅ term)",
        "state": "input conservitor (ς term)",
        "boundary": "input conservitor (∂ operator)",
        "existence": "output conservitor (∃ result)",
    }
    return roles.get(key, "non-conservitor")


def _failure_modes(key: str) -> list[str]:
    """Return characteristic failure modes for a primitive."""
    modes = {
        "nothing": [
            "Ignoring absence — treating missing data as non-informative",
            "Void blindness — decomposition that skips Phase V",
        ],
        "state": [
            "Inferred state — claiming state without measurement (Gate 2)",
            "State conflation — treating different observations as same state",
        ],
        "boundary": [
            "Boundary mismatch — measuring at wrong boundary (Gate 3)",
            "Fuzzy boundary — identity unclear, inside/outside indistinct",
        ],
        "existence": [
            "Existence without conservation — missing ∅, ς, or ∂ term",
            "Premature existence claim — asserting before all terms verified",
        ],
        "causality": [
            "Post hoc fallacy — temporal sequence assumed as causation",
            "Causal chain truncation — stopping before root cause",
        ],
        "comparison": [
            "Apophenia — seeing patterns in coincidence (Gate 5)",
            "Wrong comparator — comparing against inappropriate baseline",
        ],
        "quantity": [
            "Unmeasured quantifiers — '3x faster' without two numbers (Gate 2)",
            "Count boundary error — counting at wrong granularity",
        ],
        "sequence": [
            "Dependency cycle — circular ordering that cannot terminate",
            "Order blindness — treating parallel steps as sequential",
        ],
        "mapping": [
            "Domain leak — source semantics contaminating target",
            "Incomplete mapping — gaps in the transformation",
        ],
        "recursion": [
            "Infinite recursion — no base case or stopping criterion",
            "False fixpoint — claiming convergence before reaching it",
        ],
        "frequency": [
            "Sampling bias — measuring frequency at unrepresentative interval",
            "Rate conflation — confusing instantaneous and average rates",
        ],
        "persistence": [
            "Persistence without verification (π without ν)",
            "Stale persistence — stored state diverged from reality",
        ],
        "location": [
            "Dangling reference — address that points to nothing",
            "Location conflation — confusing logical and physical address",
        ],
        "irreversibility": [
            "False reversibility — assuming undo exists when it doesn't",
            "Premature commitment — irreversible action without verification",
        ],
        "sum": [
            "Non-exhaustive enumeration — missing variant",
            "Overlapping variants — cases that aren't disjoint",
        ],
    }
    return modes.get(key, [])


# ── Tool handlers ──


def analyze_nothing(args: dict) -> dict:
    concept = args.get("concept", "").strip()
    if not concept:
        return {"status": "error", "message": "concept is required"}
    return _base("nothing", args, {
        "concept": concept,
        "voids_detected": [
            f"What is absent in '{concept}' that would change its nature if present?",
            f"What does '{concept}' assume exists but does not verify?",
            f"What is the symmetric difference between expected and observed in '{concept}'?",
        ],
    })


def analyze_state(args: dict) -> dict:
    system = args.get("system", "").strip()
    if not system:
        return {"status": "error", "message": "system is required"}
    observation = args.get("observation", "")
    return _base("state", args, {
        "system": system,
        "states": [
            {"name": "initial", "description": f"Starting condition of {system}"},
            {"name": "current", "description": f"Observable condition of {system} now"},
            {"name": "target", "description": f"Desired condition of {system}"},
        ],
        "transitions": [
            f"{system}: initial → current (what changed?)",
            f"{system}: current → target (what must change?)",
        ],
    })


def analyze_boundary(args: dict) -> dict:
    entity = args.get("entity", "").strip()
    if not entity:
        return {"status": "error", "message": "entity is required"}
    context = args.get("context", "environment")
    return _base("boundary", args, {
        "entity": entity,
        "boundaries": [
            {"type": "identity", "description": f"What makes {entity} distinct from {context}"},
            {"type": "interface", "description": f"How {entity} communicates across its boundary"},
            {"type": "constraint", "description": f"What {entity}'s boundary prevents"},
        ],
        "identity": f"{entity} is defined by what its boundary excludes",
    })


def analyze_existence(args: dict) -> dict:
    subject = args.get("subject", "").strip()
    if not subject:
        return {"status": "error", "message": "subject is required"}
    return _base("existence", args, {
        "subject": subject,
        "exists": True,
        "conservation": {
            "law": "∃ = ∂(×(ς, ∅))",
            "void_term": f"What is absent in {subject}?",
            "state_term": f"What is the observable state of {subject}?",
            "boundary_term": f"What boundary creates {subject}'s identity?",
            "verdict": "All three terms required for existence to hold",
        },
    })


def analyze_causality(args: dict) -> dict:
    cause = args.get("cause", "").strip()
    effect = args.get("effect", "").strip()
    if not cause or not effect:
        return {"status": "error", "message": "cause and effect are required"}
    return _base("causality", args, {
        "cause": cause,
        "effect": effect,
        "chain": [
            {"step": 1, "from": cause, "to": effect, "mechanism": "direct"},
            {"step": 2, "test": "temporal", "question": f"Does {cause} precede {effect}?"},
            {"step": 3, "test": "intervention", "question": f"Does removing {cause} prevent {effect}?"},
            {"step": 4, "test": "mechanism", "question": f"Is there a plausible pathway from {cause} to {effect}?"},
        ],
    })


def analyze_comparison(args: dict) -> dict:
    a = args.get("a", "").strip()
    b = args.get("b", "").strip()
    if not a or not b:
        return {"status": "error", "message": "a and b are required"}
    return _base("comparison", args, {
        "a": a,
        "b": b,
        "shared": [f"Both {a} and {b} exist in the same domain"],
        "unique_a": [f"Properties unique to {a}"],
        "unique_b": [f"Properties unique to {b}"],
        "distance": 0,
    })


def analyze_quantity(args: dict) -> dict:
    concept = args.get("concept", "").strip()
    if not concept:
        return {"status": "error", "message": "concept is required"}
    return _base("quantity", args, {
        "concept": concept,
        "quantities": [
            {"what": f"Count of {concept}", "measurable": True, "unit": "instances"},
            {"what": f"Magnitude of {concept}", "measurable": True, "unit": "domain-specific"},
        ],
    })


def analyze_sequence(args: dict) -> dict:
    items = args.get("items", "").strip()
    if not items:
        return {"status": "error", "message": "items is required"}
    parts = [x.strip() for x in items.split(",") if x.strip()]
    return _base("sequence", args, {
        "items": items,
        "ordered": parts if parts else [items],
        "dependencies": [
            {"from": parts[i], "to": parts[i + 1], "type": "sequential"}
            for i in range(len(parts) - 1)
        ] if len(parts) > 1 else [],
    })


def analyze_mapping(args: dict) -> dict:
    source = args.get("source", "").strip()
    target = args.get("target", "").strip()
    if not source or not target:
        return {"status": "error", "message": "source and target are required"}
    return _base("mapping", args, {
        "source": source,
        "target": target,
        "mappings": [
            {"from": source, "to": target, "type": "structural", "confidence": 0.5},
        ],
        "shared": [f"Common structure between {source} and {target}"],
        "gaps": [f"What exists in {source} with no equivalent in {target}"],
    })


def analyze_recursion(args: dict) -> dict:
    structure = args.get("structure", "").strip()
    if not structure:
        return {"status": "error", "message": "structure is required"}
    return _base("recursion", args, {
        "structure": structure,
        "self_referential": False,
        "depth": 0,
        "fixed_point": f"The point where decomposing {structure} yields {structure} again",
    })


def analyze_frequency(args: dict) -> dict:
    signal = args.get("signal", "").strip()
    if not signal:
        return {"status": "error", "message": "signal is required"}
    return _base("frequency", args, {
        "signal": signal,
        "frequencies": [
            {"pattern": signal, "rate": "unknown", "period": "unknown", "regularity": "to be measured"},
        ],
    })


def analyze_persistence(args: dict) -> dict:
    entity = args.get("entity", "").strip()
    if not entity:
        return {"status": "error", "message": "entity is required"}
    return _base("persistence", args, {
        "entity": entity,
        "endures": True,
        "mechanism": f"Storage or memory mechanism preserving {entity}",
        "lifetime": "unknown — requires measurement",
    })


def analyze_location(args: dict) -> dict:
    reference = args.get("reference", "").strip()
    if not reference:
        return {"status": "error", "message": "reference is required"}
    return _base("location", args, {
        "reference": reference,
        "address": f"Location of {reference} in its domain",
        "reachable": True,
        "domain": "context-dependent",
    })


def analyze_irreversibility(args: dict) -> dict:
    action = args.get("action", "").strip()
    if not action:
        return {"status": "error", "message": "action is required"}
    return _base("irreversibility", args, {
        "action": action,
        "reversible": False,
        "entropy_delta": "positive (increases disorder)",
        "consequence": f"Once {action} occurs, the prior state cannot be recovered",
    })


def analyze_sum(args: dict) -> dict:
    variants = args.get("variants", "").strip()
    if not variants:
        return {"status": "error", "message": "variants is required"}
    parts = [x.strip() for x in variants.split(",") if x.strip()]
    return _base("sum", args, {
        "variants": variants,
        "cases": [
            {"variant": v, "index": i, "disjoint": True}
            for i, v in enumerate(parts)
        ] if parts else [{"variant": variants, "index": 0, "disjoint": True}],
        "exhaustive": False,
    })


TOOL_DISPATCH = {
    "analyze-nothing": analyze_nothing,
    "analyze-state": analyze_state,
    "analyze-boundary": analyze_boundary,
    "analyze-existence": analyze_existence,
    "analyze-causality": analyze_causality,
    "analyze-comparison": analyze_comparison,
    "analyze-quantity": analyze_quantity,
    "analyze-sequence": analyze_sequence,
    "analyze-mapping": analyze_mapping,
    "analyze-recursion": analyze_recursion,
    "analyze-frequency": analyze_frequency,
    "analyze-persistence": analyze_persistence,
    "analyze-location": analyze_location,
    "analyze-irreversibility": analyze_irreversibility,
    "analyze-sum": analyze_sum,
}


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        result = {"status": "error", "message": "No input received on stdin"}
        print(json.dumps(result))
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        result = {"status": "error", "message": f"Invalid JSON input: {exc}"}
        print(json.dumps(result))
        sys.exit(1)

    tool_name = payload.get("tool", "").strip()
    args = payload.get("arguments", payload.get("args", {}))

    if tool_name not in TOOL_DISPATCH:
        known = list(TOOL_DISPATCH.keys())
        result = {
            "status": "error",
            "message": f"Unknown tool '{tool_name}'. Known tools: {known}",
        }
        print(json.dumps(result))
        sys.exit(1)

    handler = TOOL_DISPATCH[tool_name]
    result = handler(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
