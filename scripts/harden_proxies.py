import glob
import re
import sys
from pathlib import Path

HELPERS = '''
import json

def ensure_str(val) -> str:
    """Coerce any input to string safely to prevent AttributeError."""
    if val is None:
        return ""
    if isinstance(val, (int, float, bool)):
        return str(val)
    if isinstance(val, (list, dict)):
        try:
            return json.dumps(val)
        except Exception:
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

def process_file(file_path: Path):
    if file_path.name in ("pharma_proxy.py", "harden_proxies.py", "dispatch.py", "config_forge.py"):
        return

    with open(file_path, "r") as f:
        content = f.read()

    orig_content = content
    has_changes = False

    # Check if there are any vulnerable patterns to begin with
    needs_helpers = bool(re.search(r'\.get\([^)]*\)\.strip\(\)', content)) or \
                    bool(re.search(r'int\(args\.get', content))

    if not needs_helpers:
        return

    # 1. Inject helpers if missing
    if "def ensure_str" not in content:
        # Insert after the last import
        import_end = 0
        for match in re.finditer(r'^(import |from ).*$', content, re.MULTILINE):
            import_end = match.end()
        if import_end > 0:
            content = content[:import_end] + "\n\n" + HELPERS + "\n" + content[import_end:]
        else:
            content = HELPERS + "\n" + content
        has_changes = True

    # 2. Replace vulnerable strip() calls
    # Matches: args.get("key", "default").strip() -> ensure_str(args.get("key", "default")).strip()
    new_content, count1 = re.subn(
        r'(\b(?:args|payload|p)\.get\([^)]+\))\.strip\(\)',
        r'ensure_str(\1).strip()',
        content
    )
    
    # Matches: (args.get(...) or "").strip() -> ensure_str(args.get(...) or "").strip()
    new_content, count2 = re.subn(
        r'\(((?:args|payload|p)\.get\([^)]+\)\s*or\s*[^)]+)\)\.strip\(\)',
        r'ensure_str(\1).strip()',
        new_content
    )
    
    # 3. Replace vulnerable int() calls (basic ones without min/max first)
    new_content, count3 = re.subn(
        r'int\(\s*(?:args|payload|p)\.get\("([^"]+)"(?:,\s*([^)]+))?\)\)',
        lambda m: f'get_int_param(args, "{m.group(1)}", {m.group(2) or 0})',
        new_content
    )

    # Replace max/min wrappers for clamping (e.g. min(int(...), 100))
    new_content, count4 = re.subn(
        r'min\(\s*get_int_param\(args,\s*"([^"]+)",\s*([^)]+)\),\s*([^)]+)\)',
        r'get_int_param(args, "\1", \2, max_val=\3)',
        new_content
    )
    
    new_content, count5 = re.subn(
        r'max\(\s*get_int_param\(args,\s*"([^"]+)",\s*([^)]+)\),\s*([^)]+)\)',
        r'get_int_param(args, "\1", \2, min_val=\3)',
        new_content
    )

    if count1 + count2 + count3 + count4 + count5 > 0:
        with open(file_path, "w") as f:
            f.write(new_content)
        print(f"Hardened {file_path.name}")

if __name__ == "__main__":
    script_dir = Path("/home/matthew/ferroforge/scripts")
    for py_file in script_dir.glob("*.py"):
        process_file(py_file)
