#!/usr/bin/env python3
"""
NexVigilant Station — Unified MCP Tool Dispatcher

Reads a JSON envelope from stdin, parses the domain prefix from the tool name,
and routes to the correct proxy script. Returns the proxy's JSON output on stdout.

Input envelope (stdin):
    {"tool": "api_fda_gov_search_adverse_events", "arguments": {"drug_name": "aspirin"}}

Output (stdout):
    <JSON from proxy script, or stub response for unmapped domains>

Usage:
    echo '{"tool": "api_fda_gov_search_adverse_events", "arguments": {"drug_name": "aspirin"}}' | python3 dispatch.py
    python3 dispatch.py --test
"""

import json
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Domain routing map
# Key   : prefix that appears at the start of the tool name (trailing _ included)
# Value : proxy script filename (relative to this script's directory)
# ---------------------------------------------------------------------------
DOMAIN_ROUTES: dict[str, str] = {
    # ── Live API proxies (7) ──
    "api_fda_gov_":                "openfda_proxy.py",
    "clinicaltrials_gov_":         "clinicaltrials_proxy.py",
    "dailymed_nlm_nih_gov_":       "dailymed_proxy.py",
    "rxnav_nlm_nih_gov_":          "rxnav_proxy.py",
    "pubmed_ncbi_nlm_nih_gov_":    "pubmed_proxy.py",
    "open-vigil_fr_":              "openvigil_proxy.py",
    "accessdata_fda_gov_":             "accessdata_proxy.py",
    # ── Routed stubs (9) — proxy scripts return stub envelopes ──
    "www_ema_europa_eu_":              "ema_proxy.py",
    "eudravigilance_ema_europa_eu_":   "eudravigilance_proxy.py",
    "vigiaccess_org_":                 "vigiaccess_proxy.py",
    "go_drugbank_com_":                "drugbank_proxy.py",
    "meddra_org_":                     "meddra_proxy.py",
    "ich_org_":                        "ich_proxy.py",
    "cioms_ch_":                       "cioms_proxy.py",
    "who-umc_org_":                    "who_umc_proxy.py",
    "www_fda_gov_":                    "fda_safety_proxy.py",
}

# Ordered by prefix length (longest first) so that more-specific prefixes win
# when two prefixes share a common stem (e.g. future sub-domain variants).
_SORTED_ROUTES: list[tuple[str, str]] = sorted(
    DOMAIN_ROUTES.items(), key=lambda kv: len(kv[0]), reverse=True
)

SCRIPTS_DIR = Path(__file__).parent.resolve()


# ---------------------------------------------------------------------------
# Core routing logic
# ---------------------------------------------------------------------------

def resolve_route(tool_name: str) -> tuple[str | None, str]:
    """
    Return (proxy_script_path, unprefixed_tool_name).

    If no domain prefix matches, proxy_script_path is None and the original
    tool name is returned unchanged.
    """
    for prefix, script_file in _SORTED_ROUTES:
        if tool_name.startswith(prefix):
            unprefixed = tool_name[len(prefix):].replace("_", "-")
            proxy_path = str(SCRIPTS_DIR / script_file)
            return proxy_path, unprefixed
    return None, tool_name


def call_proxy(proxy_path: str, tool_name: str, arguments: dict) -> dict:
    """
    Invoke proxy_path as a subprocess, passing a JSON envelope on stdin.
    Returns the parsed JSON response dict.

    The proxy receives:
        {"tool": "<unprefixed_tool_name>", "arguments": {...}}

    The proxy must write a single JSON object to stdout and exit 0.
    """
    payload = json.dumps({"tool": tool_name, "arguments": arguments})
    try:
        result = subprocess.run(
            [sys.executable, proxy_path],
            input=payload,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        return {
            "status": "error",
            "error": f"Proxy script not found: {proxy_path}",
            "tool": tool_name,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error": f"Proxy timed out after 30 s: {proxy_path}",
            "tool": tool_name,
        }

    if result.returncode != 0:
        return {
            "status": "error",
            "error": f"Proxy exited {result.returncode}",
            "stderr": result.stderr.strip(),
            "tool": tool_name,
        }

    raw_stdout = result.stdout.strip()
    if not raw_stdout:
        return {
            "status": "error",
            "error": "Proxy returned empty output",
            "tool": tool_name,
        }

    try:
        return json.loads(raw_stdout)
    except json.JSONDecodeError as exc:
        return {
            "status": "error",
            "error": f"Proxy returned invalid JSON: {exc}",
            "raw_output": raw_stdout[:500],
            "tool": tool_name,
        }


def stub_response(tool_name: str, arguments: dict) -> dict:
    """
    Return a structured stub for tool names with no registered domain prefix.
    This allows the dispatch layer to degrade gracefully while new proxies
    are being developed.
    """
    return {
        "status": "stub",
        "message": (
            f"No proxy registered for tool '{tool_name}'. "
            "Add an entry to DOMAIN_ROUTES in dispatch.py and create the "
            "corresponding proxy script."
        ),
        "tool": tool_name,
        "arguments": arguments,
        "registered_domains": list(DOMAIN_ROUTES.keys()),
    }


# ---------------------------------------------------------------------------
# Main dispatch entry point
# ---------------------------------------------------------------------------

def dispatch(envelope: dict) -> dict:
    """
    Route a single tool-call envelope to the correct proxy.
    Returns a response dict ready for JSON serialisation.
    """
    tool_name = envelope.get("tool", "")
    arguments = envelope.get("arguments", {})

    if not tool_name:
        return {
            "status": "error",
            "error": "Envelope missing required field 'tool'",
        }

    proxy_path, unprefixed = resolve_route(tool_name)

    if proxy_path is None:
        return stub_response(tool_name, arguments)

    if not Path(proxy_path).exists():
        # Proxy is registered but the file has not been created yet.
        return {
            "status": "stub",
            "message": (
                f"Proxy '{Path(proxy_path).name}' is registered for this domain "
                "but has not been implemented yet."
            ),
            "tool": unprefixed,
            "full_tool": tool_name,
            "arguments": arguments,
        }

    return call_proxy(proxy_path, unprefixed, arguments)


def main_stdin() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        out = {"status": "error", "error": "Empty input on stdin"}
    else:
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            out = {"status": "error", "error": f"Invalid JSON on stdin: {exc}"}
        else:
            out = dispatch(envelope)

    sys.stdout.write(json.dumps(out, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Smoke test (--test flag)
# ---------------------------------------------------------------------------

SMOKE_TEST_CASES: list[dict] = [
    {
        "label": "openFDA — domain prefix resolves to openfda_proxy.py",
        "envelope": {"tool": "api_fda_gov_search_adverse_events", "arguments": {"drug_name": "aspirin"}},
        "expect_domain": "api_fda_gov_",
    },
    {
        "label": "ClinicalTrials — registered proxy",
        "envelope": {"tool": "clinicaltrials_gov_get_serious_adverse_events", "arguments": {"nct_id": "NCT00000001"}},
        "expect_domain": "clinicaltrials_gov_",
    },
    {
        "label": "DailyMed — registered proxy",
        "envelope": {"tool": "dailymed_nlm_nih_gov_get_drug_label", "arguments": {"drug_name": "ibuprofen"}},
        "expect_domain": "dailymed_nlm_nih_gov_",
    },
    {
        "label": "RxNav — registered proxy",
        "envelope": {"tool": "rxnav_nlm_nih_gov_get_rxcui", "arguments": {"drug_name": "metformin"}},
        "expect_domain": "rxnav_nlm_nih_gov_",
    },
    {
        "label": "PubMed — registered proxy",
        "envelope": {"tool": "pubmed_ncbi_nlm_nih_gov_search_articles", "arguments": {"query": "aspirin adverse events"}},
        "expect_domain": "pubmed_ncbi_nlm_nih_gov_",
    },
    {
        "label": "OpenVigil — registered proxy",
        "envelope": {"tool": "open-vigil_fr_compute_disproportionality", "arguments": {"drug": "metformin", "event": "lactic acidosis"}},
        "expect_domain": "open-vigil_fr_",
    },
    {
        "label": "VigiAccess — routed stub (no proxy script yet)",
        "envelope": {"tool": "vigiaccess_org_search_reports", "arguments": {"drug_name": "warfarin"}},
        "expect_domain": "vigiaccess_org_",
    },
    {
        "label": "EMA — routed stub",
        "envelope": {"tool": "www_ema_europa_eu_search_medicines", "arguments": {"query": "metformin"}},
        "expect_domain": "www_ema_europa_eu_",
    },
    {
        "label": "DrugBank — routed stub",
        "envelope": {"tool": "go_drugbank_com_get_drug_info", "arguments": {"drug_name": "metformin"}},
        "expect_domain": "go_drugbank_com_",
    },
    {
        "label": "MedDRA — routed stub",
        "envelope": {"tool": "meddra_org_search_terms", "arguments": {"query": "lactic acidosis"}},
        "expect_domain": "meddra_org_",
    },
    {
        "label": "WHO-UMC — routed stub",
        "envelope": {"tool": "who-umc_org_search_vigibase", "arguments": {"drug": "metformin"}},
        "expect_domain": "who-umc_org_",
    },
    {
        "label": "Unknown domain — should return stub",
        "envelope": {"tool": "unknown_domain_search", "arguments": {"query": "test"}},
        "expect_domain": None,
    },
    {
        "label": "Missing tool field — should return error",
        "envelope": {"arguments": {"drug_name": "warfarin"}},
        "expect_domain": "error",
    },
]


def run_smoke_tests() -> None:
    print("NexVigilant Station — Dispatcher Smoke Test")
    print("=" * 60)

    passed = 0
    failed = 0

    for case in SMOKE_TEST_CASES:
        label = case["label"]
        envelope = case["envelope"]
        expect_domain = case["expect_domain"]

        # Resolve route without calling the proxy
        tool_name = envelope.get("tool", "")
        proxy_path, unprefixed = resolve_route(tool_name)

        # Determine expected outcome
        if expect_domain == "error":
            result = dispatch(envelope)
            ok = result.get("status") == "error"
            outcome = f"status={result.get('status')} (expected error)"
        elif expect_domain is None:
            # Expect stub (no registered proxy)
            ok = proxy_path is None
            outcome = f"proxy={'none (correct)' if ok else proxy_path}"
        else:
            expected_script = DOMAIN_ROUTES.get(expect_domain, "")
            ok = proxy_path is not None and expected_script in proxy_path
            outcome = f"proxy={Path(proxy_path).name if proxy_path else 'none'}"

        # Exercise the full dispatch path to verify no exceptions
        try:
            result = dispatch(envelope)
            status = result.get("status", "unknown")
        except Exception as exc:  # noqa: BLE001
            ok = False
            status = f"EXCEPTION: {exc}"

        symbol = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1

        print(f"  [{symbol}] {label}")
        print(f"         route: {outcome}  |  dispatch status: {status}")

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(SMOKE_TEST_CASES)} cases")

    if failed > 0:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_smoke_tests()
    else:
        main_stdin()
