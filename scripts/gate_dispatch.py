#!/usr/bin/env python3
"""Gate: Verify dispatch routing covers all proxy configs."""
import json
import glob
import sys

project_dir = sys.argv[1] if len(sys.argv) > 1 else "."
scripts_dir = f"{project_dir}/scripts"

sys.path.insert(0, scripts_dir)
from dispatch import DOMAIN_ROUTES

configs_with_proxy = []
for f in sorted(glob.glob(f"{project_dir}/configs/*.json")):
    config = json.load(open(f))
    if config.get("proxy"):
        configs_with_proxy.append(config["domain"])

print(f"  Dispatch routes: {len(DOMAIN_ROUTES)}")
print(f"  Configs with proxy: {len(configs_with_proxy)}")

unrouted = []
for domain in configs_with_proxy:
    prefix = domain.replace(".", "_") + "_"
    if prefix not in DOMAIN_ROUTES:
        unrouted.append(domain)

if unrouted:
    print(f"  WARNING: {len(unrouted)} configs may lack dispatch routes:")
    for u in unrouted:
        print(f"    - {u}")
else:
    print("  All proxy configs have dispatch routes")
