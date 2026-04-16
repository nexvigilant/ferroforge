# Archived Orphan Proxy Scripts (2026-04-16)

These 12 proxy scripts existed in `scripts/` but were not referenced by any
config in `~/ferroforge/configs/*.json` and were not imported by `dispatch.py`
or other active scripts.

Reason for archival: maintenance-burden reduction. Each script was scanned
for internal imports and dispatch.py references before archival.

## How to restore

```bash
mv scripts/archive/2026-04-16-orphans/<script_name>.py scripts/
```

Then wire it into a config (`"proxy": "scripts/<script_name>.py"`) or
reference it in dispatch.py.

## Orphans archived

- cioms_ch_proxy.py
- claude_ai_proxy.py
- dispatch_daemon.py
- eudravigilance_live_ema_europa_eu_proxy.py
- gate_dispatch.py
- go_drugbank_com_proxy.py
- ich_org_proxy.py
- lilly_proxy.py
- meddra_org_proxy.py
- novartis_proxy.py
- pfizer_proxy.py
- who_umc_org_proxy.py

Note: Individual pharma company proxies (lilly, novartis, pfizer) were
orphaned because the per-company coverage moved into nexcore-rust-native
handlers via `nexcore_proxy.py`.
