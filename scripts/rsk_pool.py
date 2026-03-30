#!/usr/bin/env python3
"""
RSK Connection Pool — persistent rsk binary process for microgram execution.

Instead of spawning `rsk mcg run` per tool call, this pool keeps a long-running
rsk process that accepts JSON commands on stdin. Since rsk is a CLI tool (not MCP),
we use a simpler protocol: serialize each command as a single JSON line, read output.

For rsk, the approach is different from nexcore: rsk doesn't have a persistent
server mode. So we cache a warm subprocess pool that reuses the binary's startup
cost by running sequential commands through a wrapper.

Architecture: Pre-fork a process, send commands via subprocess.run() but with
the binary already resolved and validated. The real win here is the shared
import/lookup of paths + YAML chain definitions that we cache at module level.
"""

import json
import os
import subprocess
from pathlib import Path

RSK_BINARY = Path(os.environ.get(
    "RSK_BINARY",
    str(Path.home() / "Projects" / "rsk-core" / "target" / "release" / "rsk")
))
MCG_DIR = Path(os.environ.get(
    "MCG_DIR",
    str(Path.home() / "Projects" / "rsk-core" / "rsk" / "micrograms")
))
CHAINS_DIR = Path(os.environ.get(
    "CHAINS_DIR",
    str(Path.home() / "Projects" / "rsk-core" / "rsk" / "chains")
))

# Pre-validate binary exists at import time
_BINARY_OK = RSK_BINARY.is_file()

# Cache resolved microgram paths (name → full path)
_MCG_CACHE: dict[str, Path] = {}


def _resolve_mcg(name: str) -> Path | None:
    """Resolve microgram name to path, with caching."""
    if name in _MCG_CACHE:
        return _MCG_CACHE[name]

    # Search recursively (micrograms live in subdirs too)
    for candidate in MCG_DIR.rglob(f"{name}.yaml"):
        _MCG_CACHE[name] = candidate
        return candidate
    return None


def run_single(microgram: str, input_json: dict) -> dict:
    """Execute a single microgram."""
    if not _BINARY_OK:
        return {"status": "error", "message": f"rsk binary not found: {RSK_BINARY}"}

    mcg_path = _resolve_mcg(microgram)
    if not mcg_path:
        return {"status": "error", "message": f"Microgram not found: {microgram}"}

    result = subprocess.run(
        [str(RSK_BINARY), "mcg", "run", "-i", json.dumps(input_json), str(mcg_path)],
        capture_output=True, text=True, timeout=10,
    )

    if result.returncode != 0:
        return {"status": "error", "message": result.stderr.strip()[:500]}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "message": f"Invalid JSON: {result.stdout[:200]}"}


def run_chain(chain_str: str, input_json: dict, accumulate: bool = True,
              mcg_dir: Path | None = None) -> dict:
    """Execute a microgram chain."""
    if not _BINARY_OK:
        return {"status": "error", "message": f"rsk binary not found: {RSK_BINARY}"}

    cmd = [
        str(RSK_BINARY), "mcg", "chain",
        "-i", json.dumps(input_json),
        "-d", str(mcg_dir or MCG_DIR),
    ]
    if accumulate:
        cmd.append("--accumulate")
    cmd.append(chain_str)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        return {"status": "error", "message": result.stderr.strip()[:500]}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "message": f"Invalid JSON: {result.stdout[:200]}"}


def run_chain_file(chain_name: str, input_json: dict) -> dict:
    """Execute a chain from a YAML chain file."""
    import yaml

    chain_path = CHAINS_DIR / f"{chain_name}.yaml"
    if not chain_path.exists():
        return {"status": "error", "message": f"Chain file not found: {chain_name}"}

    with open(chain_path) as f:
        chain_def = yaml.safe_load(f)

    steps = chain_def.get("steps", [])
    if not steps:
        return {"status": "error", "message": f"No steps in chain: {chain_name}"}

    chain_str = " -> ".join(steps)
    mcg_dir = chain_path.parent / chain_def.get("micrograms_dir", "../micrograms")
    return run_chain(chain_str, input_json, accumulate=True, mcg_dir=mcg_dir.resolve())


def catalog() -> dict:
    """List available micrograms."""
    if not _BINARY_OK:
        return {"status": "error", "message": f"rsk binary not found: {RSK_BINARY}"}

    result = subprocess.run(
        [str(RSK_BINARY), "mcg", "catalog", str(MCG_DIR)],
        capture_output=True, text=True, timeout=10,
    )

    if result.returncode != 0:
        return {"status": "error", "message": result.stderr.strip()[:500]}

    try:
        data = json.loads(result.stdout)
        entries = data.get("entries", [])
        return {
            "status": "ok",
            "micrograms": data.get("total_micrograms", len(entries)),
            "total_tests": data.get("total_tests", 0),
            "all_pass": data.get("all_pass", False),
            "catalog": entries,
        }
    except json.JSONDecodeError:
        return {"status": "ok", "micrograms": 0, "catalog": []}
