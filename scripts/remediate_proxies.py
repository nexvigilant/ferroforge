import os
import re

FILES = [
    "openfda_proxy.py",
    "clinicaltrials_proxy.py",
    "dailymed_proxy.py",
    "rxnav_proxy.py",
    "pubmed_proxy.py",
    "openvigil_proxy.py",
    "eudravigilance_proxy.py",
    "who_umc_proxy.py",
    "vigiaccess_proxy.py",
    "ema_proxy.py",
]

HELPERS = '''
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_str(val) -> str:
    """Coerce any input to string safely. Prevents 'AttributeError: strip'."""
    if val is None:
        return ""
    if isinstance(val, (int, float, bool)):
        return str(val)
    if isinstance(val, (list, dict)):
        import json
        try:
            return json.dumps(val)
        except:
            return str(val)
    return str(val)


def get_int_param(args: dict, key: str, default: int, min_val: int = None, max_val: int = None) -> int:
    """Safely parse integer parameter with optional clamping."""
    val = args.get(key)
    if val is None:
        return default
    
    try:
        res = int(val)
    except (ValueError, TypeError):
        return default
    
    if min_val is not None:
        res = max(res, min_val)
    if max_val is not None:
        res = min(res, max_val)
    return res

'''

def insert_helpers(content):
    if "def ensure_str" in content:
        return content
    # Find a good place to insert: after imports
    match = re.search(r'import .*\n(?:import .*\n)*', content)
    if match:
        idx = match.end()
        return content[:idx] + HELPERS + content[idx:]
    return content

for filename in FILES:
    filepath = os.path.join("/home/matthew/ferroforge/scripts", filename)
    if not os.path.exists(filepath):
        continue
    
    with open(filepath, "r") as f:
        content = f.read()

    # 1. Add helpers
    content = insert_helpers(content)

    # 2. Fix x = ensure_str(args.get("...", "")).strip()
    content = re.sub(
        r'(\w+)\.get\((["\']\w+["\']),\s*["\']\s*["\']\)\.strip\(\)',
        r'ensure_str(\1.get(\2)).strip()',
        content
    )

    # Fix x = str(args.get("...", "")).strip()
    content = re.sub(
        r'str\((\w+)\.get\((["\']\w+["\']),\s*["\']\s*["\']\)\)\.strip\(\)',
        r'ensure_str(\1.get(\2)).strip()',
        content
    )

    # Fix get_int_param(args, "...", default)
    content = re.sub(
        r'int\((\w+)\.get\((["\']\w+["\']),\s*([^)]+)\)\)',
        r'get_int_param(\1, \2, \3)',
        content
    )

    # Fix ensure_str(payload.get("tool", "")).strip()
    content = re.sub(
        r'(\w+)\.get\((["\']tool["\']),\s*["\']\s*["\']\)\.strip\(\)',
        r'ensure_str(\1.get(\2)).strip()',
        content
    )

    with open(filepath, "w") as f:
        f.write(content)

print("Refactoring completed.")
