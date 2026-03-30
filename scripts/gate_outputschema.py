#!/usr/bin/env python3
"""Gate: Verify all tools have outputSchema defined."""
import json
import glob
import sys

project_dir = sys.argv[1] if len(sys.argv) > 1 else "."
missing = []
for f in sorted(glob.glob(f"{project_dir}/configs/*.json")):
    config = json.load(open(f))
    for t in config.get("tools", []):
        if "outputSchema" not in t:
            missing.append(f"{config['domain']}:{t['name']}")
if missing:
    print(f"  {len(missing)} tools missing outputSchema:")
    for m in missing[:10]:
        print(f"    - {m}")
    sys.exit(1)
total = sum(
    len(json.load(open(f)).get("tools", []))
    for f in glob.glob(f"{project_dir}/configs/*.json")
)
print(f"  All {total} tools have outputSchema")
