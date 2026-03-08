# NexVigilant Station Scoreboard

Last updated: 2026-03-08

## Summary

| Metric | Count |
|--------|-------|
| Local configs | 22 |
| Local tools | 163 |
| On Hub | 20 |
| Hub tools (deployed) | 149 |
| Pending hub update | 0 |
| Not on hub | 2 (linkedin, wikipedia) |

## Config Inventory

| Config | Domain | Tools | Proxy | Hub ID | Hub Status |
|--------|--------|:-----:|:-----:|--------|------------|
| cioms | cioms.ch | 7 | yes | c627cf76 | CURRENT (was 3) |
| clinicaltrials | clinicaltrials.gov | 7 | yes | eac34bff | CURRENT (was 5) |
| dailymed | dailymed.nlm.nih.gov | 6 | yes | 0aaff15c | CURRENT (was 3) |
| drugbank | go.drugbank.com | 7 | yes | 495185a7 | CURRENT (was 5) |
| ema | www.ema.europa.eu | 6 | yes | 1935c7ca | CURRENT |
| eudravigilance | eudravigilance.ema.europa.eu | 7 | yes | 2d00d152 | CURRENT (was 4) |
| fda-accessdata | accessdata.fda.gov | 6 | yes | 886f2bf5 | CURRENT |
| fda-safety | www.fda.gov | 7 | yes | a7b06752 | CURRENT (was 4) |
| ich | ich.org | 7 | yes | fa63ee17 | CURRENT (was 4) |
| linkedin | www.linkedin.com | 12 | yes | — | NOT DEPLOYED |
| meddra | meddra.org | 7 | yes | a3405faa | CURRENT (was 4) |
| openfda | api.fda.gov | 7 | yes | d2cd2d1b | CURRENT |
| openvigilfrance | open-vigil.fr | 7 | yes | a09c36fc | CURRENT (was 4) |
| primitives | primitives.nexvigilant.com | 15 | no | db9233fc | CURRENT |
| pubmed | pubmed.ncbi.nlm.nih.gov | 7 | yes | 43ea0e58 | CURRENT (was 5) |
| rxnav | rxnav.nlm.nih.gov | 6 | yes | f89f7e4f | CURRENT |
| science-drug-targets | science.nexvigilant.com | 6 | yes | 167bb50b | CURRENT |
| science-genomics | science.nexvigilant.com | 6 | yes | 786ed95a | CURRENT |
| science-hexim1 | science.nexvigilant.com | 10 | yes | 653d6998 | CURRENT |
| vigiaccess | vigiaccess.org | 7 | yes | 9bd444fe | CURRENT (was 5) |
| who-umc | who-umc.org | 7 | yes | 305a17de | CURRENT (was 4) |
| wikipedia | en.wikipedia.org | 6 | yes | — | NOT DEPLOYED |

## Expansion Campaign Log

| Config | Before | After | Tools Added | Session |
|--------|:------:|:-----:|-------------|---------|
| DailyMed | 3 | 6 | get-drug-label, get-adverse-reactions, get-drug-interactions | 2026-03-08a |
| OpenVigil | 4 | 7 | get-case-demographics, get-temporal-trend, get-drug-combinations | 2026-03-08a |
| EudraVigilance | 4 | 7 | get-geographical-distribution, get-age-group-distribution, get-reporter-distribution | 2026-03-08a |
| FDA-safety | 4 | 7 | get-boxed-warning, get-safety-labeling-changes, get-rems-info | 2026-03-08a |
| WHO-UMC | 4 | 7 | get-causality-assessment, get-signal-methodology, get-country-programs | 2026-03-08a |
| ICH | 4 | 7 | get-meddra-guidelines, get-safety-reporting-guidelines, get-benefit-risk-guidelines | 2026-03-08a |
| MedDRA | 4 | 7 | get-term-hierarchy, get-soc-terms, get-smq | 2026-03-08a |
| ClinicalTrials | 5 | 7 | get-eligibility-criteria, get-study-design | 2026-03-08b |
| DrugBank | 5 | 7 | get-classification, get-contraindications | 2026-03-08b |
| PubMed | 5 | 7 | get-mesh-terms, get-related-articles | 2026-03-08b |
| VigiAccess | 5 | 7 | get-sex-distribution, get-year-distribution | 2026-03-08b |
| CIOMS | 3 | 7 | get-seriousness-criteria, get-causality-categories, get-reporting-timelines, get-cioms-form-ii | 2026-03-08b |

## Deploy Command

```bash
# Batch deploy all (requires HUB_API_KEY)
cd ~/ferroforge
HUB_API_KEY=<key> python3 scripts/config_forge.py batch-deploy hub-mapping.json

# Deploy single config
HUB_API_KEY=<key> python3 scripts/config_forge.py deploy configs/<name>.json --hub-id <uuid>
```

## Hub Cap

Account limit: 50 configs. Currently using 20 slots. 30 remaining.
