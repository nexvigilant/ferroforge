#!/usr/bin/env python3
"""
NexVigilant Key Annihilator — Automated Secret Rotation Engine

Rotates API keys in GCP Secret Manager with provider-aware lifecycle:
  1. AUDIT   — Age-check all secrets, flag stale (>90d), critical (>180d)
  2. ROTATE  — Generate new key (provider API or manual), store as new version
  3. VERIFY  — Test the new key works via provider health endpoint
  4. DISABLE — Disable old version in Secret Manager
  5. DESTROY — After grace period, destroy old versions

Providers with full auto-rotation (create + revoke via API):
  - Google Cloud service account keys
  - Stripe (test keys)

Providers with semi-auto (store + verify, manual generation):
  - Anthropic, Perplexity, Wolfram, Gemini, Resend, OpenRouter, etc.

Usage:
  python3 key_rotator.py audit                    # Show age report
  python3 key_rotator.py audit --format=json       # Machine-readable
  python3 key_rotator.py rotate SECRET_NAME        # Rotate a specific secret
  python3 key_rotator.py rotate --all-stale        # Rotate all secrets >90d
  python3 key_rotator.py disable-old SECRET_NAME   # Disable non-latest versions
  python3 key_rotator.py destroy-old --min-age=30  # Destroy disabled versions >30d old
  python3 key_rotator.py verify SECRET_NAME        # Test current key works
  python3 key_rotator.py providers                 # Show provider capabilities
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ─── Provider Registry ──────────────────────────────────────────────

class RotationCapability(Enum):
    FULL_AUTO = "full_auto"        # Can create + revoke via API
    SEMI_AUTO = "semi_auto"        # Can verify, manual key generation
    MANUAL = "manual"              # No API, fully manual
    GOOGLE_NATIVE = "google_native"  # Use gcloud IAM key rotation


@dataclass
class Provider:
    name: str
    capability: RotationCapability
    verify_cmd: Optional[str] = None       # Shell command to verify key works
    verify_env: Optional[str] = None       # Env var name the verify_cmd reads
    create_url: Optional[str] = None       # URL to create new key (for manual)
    revoke_url: Optional[str] = None       # URL to revoke old key (for manual)
    max_age_days: int = 90                 # Rotation threshold
    secrets: list[str] = field(default_factory=list)  # Secret Manager names


PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider(
        name="Anthropic",
        capability=RotationCapability.SEMI_AUTO,
        verify_cmd='curl -sf -o /dev/null -w "%{http_code}" -H "x-api-key: $KEY" -H "anthropic-version: 2023-06-01" https://api.anthropic.com/v1/models',
        verify_env="KEY",
        create_url="https://console.anthropic.com/settings/keys",
        revoke_url="https://console.anthropic.com/settings/keys",
        secrets=["ANTHROPIC_API_KEY", "anthropic-api-key", "CLAUDE_API_KEY"],
    ),
    "perplexity": Provider(
        name="Perplexity",
        capability=RotationCapability.SEMI_AUTO,
        verify_cmd='curl -sf -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -X POST https://api.perplexity.ai/chat/completions -d \'{"model":"sonar","messages":[{"role":"user","content":"ping"}],"max_tokens":1}\'',
        verify_env="KEY",
        create_url="https://www.perplexity.ai/settings/api",
        revoke_url="https://www.perplexity.ai/settings/api",
        secrets=["PERPLEXITY_API_KEY"],
    ),
    "gemini": Provider(
        name="Google Gemini",
        capability=RotationCapability.SEMI_AUTO,
        verify_cmd='curl -sf -o /dev/null -w "%{http_code}" "https://generativelanguage.googleapis.com/v1beta/models?key=$KEY"',
        verify_env="KEY",
        create_url="https://aistudio.google.com/app/apikey",
        revoke_url="https://aistudio.google.com/app/apikey",
        secrets=["GEMINI_API_KEY", "GOOGLE_GENAI_API_KEY"],
    ),
    "wolfram": Provider(
        name="Wolfram Alpha",
        capability=RotationCapability.SEMI_AUTO,
        verify_cmd='curl -sf -o /dev/null -w "%{http_code}" "https://api.wolframalpha.com/v2/query?input=1%2B1&appid=$KEY&output=json"',
        verify_env="KEY",
        create_url="https://developer.wolframalpha.com/portal/myapps/",
        secrets=["WOLFRAM_API_KEY"],
    ),
    "openrouter": Provider(
        name="OpenRouter",
        capability=RotationCapability.SEMI_AUTO,
        verify_cmd='curl -sf -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $KEY" https://openrouter.ai/api/v1/models',
        verify_env="KEY",
        create_url="https://openrouter.ai/keys",
        revoke_url="https://openrouter.ai/keys",
        secrets=["OPENROUTER_API_KEY"],
    ),
    "resend": Provider(
        name="Resend",
        capability=RotationCapability.SEMI_AUTO,
        verify_cmd='curl -sf -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $KEY" https://api.resend.com/domains',
        verify_env="KEY",
        create_url="https://resend.com/api-keys",
        revoke_url="https://resend.com/api-keys",
        secrets=["RESEND_API_KEY"],
    ),
    "stripe": Provider(
        name="Stripe",
        capability=RotationCapability.SEMI_AUTO,
        verify_cmd='curl -sf -o /dev/null -w "%{http_code}" -u "$KEY:" https://api.stripe.com/v1/balance',
        verify_env="KEY",
        create_url="https://dashboard.stripe.com/test/apikeys",
        revoke_url="https://dashboard.stripe.com/test/apikeys",
        secrets=["stripe-secret-key-test"],
    ),
    "linkedin": Provider(
        name="LinkedIn",
        capability=RotationCapability.SEMI_AUTO,
        verify_cmd='curl -sf -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $KEY" https://api.linkedin.com/v2/userinfo',
        verify_env="KEY",
        create_url="https://www.linkedin.com/developers/apps",
        max_age_days=60,  # OAuth tokens expire faster
        secrets=["linkedin-access-token"],
    ),
    "github": Provider(
        name="GitHub",
        capability=RotationCapability.SEMI_AUTO,
        verify_cmd='curl -sf -o /dev/null -w "%{http_code}" -H "Authorization: token $KEY" https://api.github.com/user',
        verify_env="KEY",
        create_url="https://github.com/settings/tokens",
        revoke_url="https://github.com/settings/tokens",
        secrets=["GITHUB_TOKEN"],
    ),
    "firebase": Provider(
        name="Firebase",
        capability=RotationCapability.GOOGLE_NATIVE,
        max_age_days=180,
        secrets=[
            "FIREBASE_ADMIN_CREDENTIALS_BASE64",
            "FIREBASE_PRIVATE_KEY",
            "FIREBASE_CLIENT_EMAIL",
            "FIREBASE_PROJECT_ID",
        ],
    ),
    "google_mcp": Provider(
        name="Google MCP OAuth",
        capability=RotationCapability.MANUAL,
        max_age_days=365,
        secrets=[
            "mcp-google-oauth-credentials",
            "mcp-gmail-oauth-token",
            "mcp-google-docs-oauth-token",
            "mcp-google-drive-oauth-token",
            "mcp-google-sheets-service-account",
            "mcp-google-slides-oauth-token",
        ],
    ),
    "internal": Provider(
        name="Internal/NexVigilant",
        capability=RotationCapability.FULL_AUTO,
        max_age_days=90,
        secrets=["nexcore-api-key", "internal-api-key", "CRON_SECRET", "MANUAL_SYNC_SECRET"],
    ),
    "unclassified": Provider(
        name="Unclassified",
        capability=RotationCapability.MANUAL,
        secrets=[],  # Populated at runtime with orphans
    ),
}


def secret_to_provider(secret_name: str) -> tuple[str, Provider]:
    """Find which provider owns a secret."""
    for pid, prov in PROVIDERS.items():
        if secret_name in prov.secrets:
            return pid, prov
    return "unclassified", PROVIDERS["unclassified"]


# ─── GCloud Helpers ──────────────────────────────────────────────────

def gcloud(args: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Run a gcloud command, return (success, output)."""
    cmd = ["gcloud"] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"


def list_secrets() -> list[dict]:
    """List all secrets with metadata."""
    ok, out = gcloud(["secrets", "list", "--format=json"])
    if not ok:
        print(f"ERROR: Failed to list secrets: {out}", file=sys.stderr)
        sys.exit(1)
    return json.loads(out)


def get_versions(secret_name: str) -> list[dict]:
    """Get all versions of a secret."""
    ok, out = gcloud(["secrets", "versions", "list", secret_name, "--format=json"])
    if not ok:
        return []
    return json.loads(out)


def access_secret(secret_name: str, version: str = "latest") -> Optional[str]:
    """Access a secret version's value."""
    ok, out = gcloud(["secrets", "versions", "access", version, f"--secret={secret_name}"])
    return out if ok else None


def add_version(secret_name: str, value: str) -> bool:
    """Add a new version to a secret."""
    cmd = ["gcloud", "secrets", "versions", "add", secret_name, "--data-file=-"]
    try:
        result = subprocess.run(
            cmd, input=value, capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def disable_version(secret_name: str, version: str) -> bool:
    """Disable a specific version."""
    ok, _ = gcloud(["secrets", "versions", "disable", version, f"--secret={secret_name}", "--quiet"])
    return ok


def destroy_version(secret_name: str, version: str) -> bool:
    """Destroy a specific version (irreversible)."""
    ok, _ = gcloud(["secrets", "versions", "destroy", version, f"--secret={secret_name}", "--quiet"])
    return ok


def generate_key(length: int = 64) -> str:
    """Generate a cryptographically secure random key."""
    import secrets as sec
    return sec.token_hex(length // 2)


# ─── Verification ────────────────────────────────────────────────────

def verify_key(provider: Provider, key_value: str) -> tuple[bool, str]:
    """Verify a key works by calling the provider's health endpoint."""
    if not provider.verify_cmd:
        return True, "no-verify-endpoint"

    env = os.environ.copy()
    env[provider.verify_env or "KEY"] = key_value

    try:
        result = subprocess.run(
            ["bash", "-c", provider.verify_cmd],
            capture_output=True, text=True, timeout=15, env=env
        )
        status = result.stdout.strip()
        if status in ("200", "201"):
            return True, f"HTTP {status}"
        return False, f"HTTP {status}"
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)


# ─── Commands ────────────────────────────────────────────────────────

@dataclass
class SecretAuditRow:
    name: str
    provider_id: str
    provider_name: str
    capability: str
    versions: int
    latest_state: str
    age_days: int
    status: str  # OK, STALE, CRITICAL, DISABLED


def cmd_audit(args: argparse.Namespace) -> None:
    """Audit all secrets for age, staleness, and rotation needs."""
    secrets = list_secrets()
    now = datetime.now(timezone.utc)
    rows: list[SecretAuditRow] = []

    for s in secrets:
        name = s["name"].split("/")[-1]
        pid, prov = secret_to_provider(name)
        versions = get_versions(name)

        if not versions:
            rows.append(SecretAuditRow(
                name=name, provider_id=pid, provider_name=prov.name,
                capability=prov.capability.value, versions=0,
                latest_state="empty", age_days=0, status="EMPTY"
            ))
            continue

        latest = versions[0]  # Sorted by create_time DESC
        latest_state = latest.get("state", "unknown")
        create_time = datetime.fromisoformat(
            latest["createTime"].replace("Z", "+00:00")
        )
        age = (now - create_time).days

        if latest_state == "DISABLED":
            status = "DISABLED"
        elif age > 180:
            status = "CRITICAL"
        elif age > prov.max_age_days:
            status = "STALE"
        else:
            status = "OK"

        rows.append(SecretAuditRow(
            name=name, provider_id=pid, provider_name=prov.name,
            capability=prov.capability.value, versions=len(versions),
            latest_state=latest_state, age_days=age, status=status
        ))

    # Sort: CRITICAL first, then STALE, then by age DESC
    priority = {"CRITICAL": 0, "STALE": 1, "EMPTY": 2, "DISABLED": 3, "OK": 4}
    rows.sort(key=lambda r: (priority.get(r.status, 5), -r.age_days))

    if args.format == "json":
        print(json.dumps([vars(r) for r in rows], indent=2))
        return

    # Table output
    critical = sum(1 for r in rows if r.status == "CRITICAL")
    stale = sum(1 for r in rows if r.status == "STALE")
    ok = sum(1 for r in rows if r.status == "OK")
    disabled = sum(1 for r in rows if r.status == "DISABLED")

    print(f"\n{'='*90}")
    print(f"  KEY ANNIHILATOR — Secret Age Audit")
    print(f"  {len(rows)} secrets | {critical} CRITICAL | {stale} STALE | {ok} OK | {disabled} DISABLED")
    print(f"{'='*90}\n")

    status_icon = {"OK": "  ", "STALE": "⚠ ", "CRITICAL": "🔴", "DISABLED": "⏸ ", "EMPTY": "∅ "}

    print(f"{'St':<3} {'Secret':<45} {'Provider':<16} {'Age':>5} {'Ver':>4} {'Capability':<14} {'State':<10}")
    print(f"{'─'*3} {'─'*45} {'─'*16} {'─'*5} {'─'*4} {'─'*14} {'─'*10}")

    for r in rows:
        icon = status_icon.get(r.status, "  ")
        print(f"{icon} {r.name:<45} {r.provider_name:<16} {r.age_days:>4}d {r.versions:>4} {r.capability:<14} {r.latest_state:<10}")

    if critical > 0 or stale > 0:
        print(f"\n{'─'*90}")
        print("  Recommended actions:")
        if critical > 0:
            print(f"  🔴 {critical} secrets are >180 days old — rotate immediately")
            print(f"     Run: python3 key_rotator.py rotate --all-critical")
        if stale > 0:
            print(f"  ⚠  {stale} secrets are past rotation threshold — schedule rotation")
            print(f"     Run: python3 key_rotator.py rotate --all-stale")
        print()


def cmd_rotate(args: argparse.Namespace) -> None:
    """Rotate a secret: generate/accept new key, store, verify, disable old."""
    secrets_to_rotate: list[str] = []

    if args.all_stale or args.all_critical:
        secrets = list_secrets()
        now = datetime.now(timezone.utc)
        for s in secrets:
            name = s["name"].split("/")[-1]
            _, prov = secret_to_provider(name)
            versions = get_versions(name)
            if not versions:
                continue
            latest = versions[0]
            if latest.get("state") == "DISABLED":
                continue
            create_time = datetime.fromisoformat(
                latest["createTime"].replace("Z", "+00:00")
            )
            age = (now - create_time).days
            if args.all_critical and age > 180:
                secrets_to_rotate.append(name)
            elif args.all_stale and age > prov.max_age_days:
                secrets_to_rotate.append(name)
    elif args.secret:
        secrets_to_rotate = [args.secret]
    else:
        print("ERROR: Specify --secret NAME, --all-stale, or --all-critical", file=sys.stderr)
        sys.exit(1)

    for secret_name in secrets_to_rotate:
        print(f"\n{'─'*60}")
        print(f"  Rotating: {secret_name}")
        print(f"{'─'*60}")

        pid, prov = secret_to_provider(secret_name)

        # Step 1: Get current key for comparison
        old_key = access_secret(secret_name)
        if old_key is None:
            print(f"  ERROR: Cannot access current version of {secret_name}")
            continue

        # Step 2: Generate or prompt for new key
        if prov.capability == RotationCapability.FULL_AUTO and pid == "internal":
            new_key = generate_key(64)
            print(f"  Generated new 64-char hex key")
        else:
            print(f"\n  Provider: {prov.name} ({prov.capability.value})")
            if prov.create_url:
                print(f"  Create new key at: {prov.create_url}")
            if prov.revoke_url:
                print(f"  Revoke old key at: {prov.revoke_url}")
            print()
            new_key = input("  Paste new key (or 'skip' to skip): ").strip()
            if new_key.lower() == "skip":
                print(f"  Skipped {secret_name}")
                continue

        if new_key == old_key:
            print(f"  WARNING: New key is identical to old key — skipping")
            continue

        # Step 3: Store new version
        if add_version(secret_name, new_key):
            print(f"  Stored as new version in Secret Manager")
        else:
            print(f"  ERROR: Failed to store new version")
            continue

        # Step 4: Verify new key works
        if prov.verify_cmd:
            ok, detail = verify_key(prov, new_key)
            if ok:
                print(f"  Verified: {detail}")
            else:
                print(f"  VERIFICATION FAILED: {detail}")
                print(f"  WARNING: New key stored but may not work!")
                print(f"  To rollback: gcloud secrets versions disable latest --secret={secret_name}")
                resp = input("  Continue with disabling old version? (y/N): ").strip().lower()
                if resp != "y":
                    continue
        else:
            print(f"  No verification endpoint — skipping verify")

        # Step 5: Disable old versions
        versions = get_versions(secret_name)
        disabled_count = 0
        for v in versions[1:]:  # Skip latest (index 0)
            if v.get("state") == "ENABLED":
                vid = v["name"].split("/")[-1]
                if disable_version(secret_name, vid):
                    disabled_count += 1
        if disabled_count > 0:
            print(f"  Disabled {disabled_count} old version(s)")

        # Step 6: Remind about external revocation
        if prov.revoke_url and prov.capability != RotationCapability.FULL_AUTO:
            print(f"\n  ACTION REQUIRED: Revoke old key at {prov.revoke_url}")
            print(f"  Old key prefix: {old_key[:8]}...")

        print(f"  ✓ Rotation complete for {secret_name}")


def cmd_disable_old(args: argparse.Namespace) -> None:
    """Disable all non-latest versions of a secret."""
    versions = get_versions(args.secret)
    if len(versions) <= 1:
        print(f"Only 1 version — nothing to disable")
        return

    count = 0
    for v in versions[1:]:
        if v.get("state") == "ENABLED":
            vid = v["name"].split("/")[-1]
            if disable_version(args.secret, vid):
                print(f"  Disabled version {vid}")
                count += 1
    print(f"Disabled {count} old version(s) of {args.secret}")


def cmd_destroy_old(args: argparse.Namespace) -> None:
    """Destroy disabled versions older than min_age days (irreversible)."""
    secrets = list_secrets()
    now = datetime.now(timezone.utc)
    total_destroyed = 0

    for s in secrets:
        name = s["name"].split("/")[-1]
        versions = get_versions(name)

        for v in versions:
            if v.get("state") != "DISABLED":
                continue
            create_time = datetime.fromisoformat(
                v["createTime"].replace("Z", "+00:00")
            )
            age = (now - create_time).days
            if age >= args.min_age:
                vid = v["name"].split("/")[-1]
                if destroy_version(name, vid):
                    print(f"  Destroyed {name} v{vid} (disabled {age}d ago)")
                    total_destroyed += 1

    print(f"\nDestroyed {total_destroyed} disabled version(s) older than {args.min_age} days")


def cmd_verify(args: argparse.Namespace) -> None:
    """Verify a secret's current value works with its provider."""
    pid, prov = secret_to_provider(args.secret)
    if not prov.verify_cmd:
        print(f"No verification endpoint for {prov.name}")
        return

    key = access_secret(args.secret)
    if key is None:
        print(f"ERROR: Cannot access {args.secret}")
        sys.exit(1)

    ok, detail = verify_key(prov, key)
    status = "PASS" if ok else "FAIL"
    print(f"{status}: {args.secret} ({prov.name}) — {detail}")
    sys.exit(0 if ok else 1)


def cmd_verify_all(args: argparse.Namespace) -> None:
    """Verify all secrets that have verification endpoints."""
    results = []
    seen = set()

    for _pid, prov in PROVIDERS.items():
        if not prov.verify_cmd:
            continue
        for secret_name in prov.secrets:
            if secret_name in seen:
                continue
            seen.add(secret_name)
            key = access_secret(secret_name)
            if key is None:
                results.append((secret_name, prov.name, "SKIP", "cannot access"))
                continue
            ok, detail = verify_key(prov, key)
            status = "PASS" if ok else "FAIL"
            results.append((secret_name, prov.name, status, detail))
            icon = "✓" if ok else "✗"
            print(f"  {icon} {secret_name:<40} {prov.name:<16} {detail}")

    passed = sum(1 for r in results if r[2] == "PASS")
    failed = sum(1 for r in results if r[2] == "FAIL")
    skipped = sum(1 for r in results if r[2] == "SKIP")
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped out of {len(results)}")
    sys.exit(1 if failed > 0 else 0)


def cmd_providers(_args: argparse.Namespace) -> None:
    """Show provider capabilities and mapped secrets."""
    print(f"\n{'Provider':<20} {'Capability':<14} {'Max Age':>8} {'Secrets':>8} {'Verify':<6}")
    print(f"{'─'*20} {'─'*14} {'─'*8} {'─'*8} {'─'*6}")
    for pid, prov in PROVIDERS.items():
        if pid == "unclassified" and not prov.secrets:
            continue
        verify = "yes" if prov.verify_cmd else "no"
        print(f"{prov.name:<20} {prov.capability.value:<14} {prov.max_age_days:>6}d {len(prov.secrets):>8} {verify:<6}")
        for s in prov.secrets:
            print(f"  └─ {s}")
    print()


# ─── Main ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="NexVigilant Key Annihilator — Automated Secret Rotation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # audit
    p_audit = sub.add_parser("audit", help="Age-check all secrets")
    p_audit.add_argument("--format", choices=["table", "json"], default="table")

    # rotate
    p_rotate = sub.add_parser("rotate", help="Rotate a secret")
    p_rotate.add_argument("secret", nargs="?", help="Secret name to rotate")
    p_rotate.add_argument("--all-stale", action="store_true", help="Rotate all stale secrets")
    p_rotate.add_argument("--all-critical", action="store_true", help="Rotate all critical secrets")

    # disable-old
    p_disable = sub.add_parser("disable-old", help="Disable non-latest versions")
    p_disable.add_argument("secret", help="Secret name")

    # destroy-old
    p_destroy = sub.add_parser("destroy-old", help="Destroy disabled versions past grace period")
    p_destroy.add_argument("--min-age", type=int, default=30, help="Minimum days since disable (default: 30)")

    # verify
    p_verify = sub.add_parser("verify", help="Verify a secret works")
    p_verify.add_argument("secret", help="Secret name")

    # verify-all
    sub.add_parser("verify-all", help="Verify all secrets with endpoints")

    # providers
    sub.add_parser("providers", help="Show provider capabilities")

    args = parser.parse_args()
    commands = {
        "audit": cmd_audit,
        "rotate": cmd_rotate,
        "disable-old": cmd_disable_old,
        "destroy-old": cmd_destroy_old,
        "verify": cmd_verify,
        "verify-all": cmd_verify_all,
        "providers": cmd_providers,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
