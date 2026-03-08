#!/usr/bin/env python3
"""
ClinicalTrials.gov API v2 proxy for NexVigilant Station.

Reads a JSON object from stdin:
    {"tool": "<tool-name>", "arguments": {...}}

Writes a JSON object to stdout with results or an error envelope.

All HTTP requests go to https://clinicaltrials.gov/api/v2/studies.
No authentication required. Uses urllib only.
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100

# Safety-relevant keywords for endpoint extraction.
SAFETY_KEYWORDS = {
    "adverse",
    "safety",
    "toxicity",
    "tolerability",
    "harm",
    "death",
    "mortality",
    "serious",
    "discontinuation",
    "withdrawal",
    "dose-limiting",
    "dlt",
    "mtd",
    "maximum tolerated",
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _get_json(url: str, params: dict[str, str] | None = None) -> Any:
    """Make a GET request and return parsed JSON. Raises on HTTP errors."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "NexVigilant-Station/1.0 (clinicaltrials_proxy.py)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP {exc.code} from ClinicalTrials.gov: {body[:400]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def _fetch_study(nct_id: str, fields: str | None = None) -> dict:
    """Fetch a single study by NCT ID."""
    nct_id = nct_id.strip().upper()
    url = f"{BASE_URL}/{urllib.parse.quote(nct_id)}"
    params: dict[str, str] = {}
    if fields:
        params["fields"] = fields
    return _get_json(url, params or None)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def search_trials(args: dict) -> dict:
    """
    Search ClinicalTrials.gov with free-text and optional structured filters.

    Maps to: GET /studies?query.term=...&filter.overallStatus=...&...
    """
    query = args.get("query", "").strip()
    if not query:
        return _error("'query' is required for search-trials")

    params: dict[str, str] = {
        "query.term": query,
        "pageSize": str(
            min(int(args.get("limit", DEFAULT_PAGE_SIZE)), MAX_PAGE_SIZE)
        ),
        "format": "json",
        "fields": (
            "NCTId,BriefTitle,OfficialTitle,OverallStatus,Phase,"
            "StartDate,CompletionDate,LeadSponsorName,Condition,InterventionName,"
            "EnrollmentCount,StudyType,BriefSummary"
        ),
    }

    condition = args.get("condition", "").strip()
    if condition:
        params["query.cond"] = condition

    intervention = args.get("intervention", "").strip()
    if intervention:
        params["query.intr"] = intervention

    status = args.get("status", "").strip()
    if status:
        # API accepts comma-separated uppercase status values.
        params["filter.overallStatus"] = status.upper().replace(" ", "_")

    phase = args.get("phase", "").strip()
    if phase:
        # API expects PHASE1, PHASE2, etc.
        phase_clean = phase.replace(" ", "").upper()
        if not phase_clean.startswith("PHASE"):
            phase_clean = f"PHASE{phase_clean}"
        params["filter.phase"] = phase_clean

    raw = _get_json(BASE_URL, params)

    studies = raw.get("studies", [])
    total = raw.get("totalCount", len(studies))
    next_token = raw.get("nextPageToken")

    results = []
    for study in studies:
        ps = study.get("protocolSection", {})
        id_mod = ps.get("identificationModule", {})
        status_mod = ps.get("statusModule", {})
        design_mod = ps.get("designModule", {})
        desc_mod = ps.get("descriptionModule", {})
        sponsor_mod = ps.get("sponsorCollaboratorsModule", {})
        cond_mod = ps.get("conditionsModule", {})
        arms_mod = ps.get("armsInterventionsModule", {})

        results.append(
            {
                "nct_id": id_mod.get("nctId"),
                "title": id_mod.get("briefTitle"),
                "official_title": id_mod.get("officialTitle"),
                "status": status_mod.get("overallStatus"),
                "phase": design_mod.get("phases"),
                "start_date": status_mod.get("startDateStruct", {}).get("date"),
                "completion_date": status_mod.get(
                    "primaryCompletionDateStruct", {}
                ).get("date"),
                "sponsor": sponsor_mod.get("leadSponsor", {}).get("name"),
                "conditions": cond_mod.get("conditions", []),
                "interventions": [
                    i.get("name")
                    for i in arms_mod.get("interventions", [])
                    if i.get("name")
                ],
                "enrollment": design_mod.get("enrollmentInfo", {}).get("count"),
                "study_type": design_mod.get("studyType"),
                "brief_summary": desc_mod.get("briefSummary", "")[:500],
            }
        )

    return {
        "total_count": total,
        "returned": len(results),
        "next_page_token": next_token,
        "trials": results,
    }


def get_trial(args: dict) -> dict:
    """
    Return full protocol record for a single NCT ID.

    Maps to: GET /studies/{nct_id}
    """
    nct_id = args.get("nct_id", "").strip()
    if not nct_id:
        return _error("'nct_id' is required for get-trial")

    raw = _fetch_study(nct_id)
    ps = raw.get("protocolSection", {})
    rs = raw.get("resultsSection", {})

    id_mod = ps.get("identificationModule", {})
    status_mod = ps.get("statusModule", {})
    design_mod = ps.get("designModule", {})
    desc_mod = ps.get("descriptionModule", {})
    sponsor_mod = ps.get("sponsorCollaboratorsModule", {})
    cond_mod = ps.get("conditionsModule", {})
    eligibility_mod = ps.get("eligibilityModule", {})
    outcomes_mod = ps.get("outcomesModule", {})
    arms_mod = ps.get("armsInterventionsModule", {})
    contacts_mod = ps.get("contactsLocationsModule", {})

    return {
        "nct_id": id_mod.get("nctId"),
        "title": id_mod.get("briefTitle"),
        "official_title": id_mod.get("officialTitle"),
        "overall_status": status_mod.get("overallStatus"),
        "phase": ", ".join(design_mod.get("phases", [])) if design_mod.get("phases") else "",
        "study_type": design_mod.get("studyType", ""),
        "allocation": design_mod.get("designInfo", {}).get("allocation"),
        "masking": design_mod.get("designInfo", {}).get("maskingInfo", {}).get(
            "masking"
        ),
        "start_date": status_mod.get("startDateStruct", {}).get("date"),
        "primary_completion_date": status_mod.get(
            "primaryCompletionDateStruct", {}
        ).get("date"),
        "completion_date": status_mod.get("completionDateStruct", {}).get("date"),
        "sponsor": sponsor_mod.get("leadSponsor", {}).get("name"),
        "collaborators": [
            c.get("name")
            for c in sponsor_mod.get("collaborators", [])
            if c.get("name")
        ],
        "conditions": cond_mod.get("conditions", []),
        "keywords": cond_mod.get("keywords", []),
        "interventions": [
            {
                "type": i.get("type"),
                "name": i.get("name"),
                "description": i.get("description", "")[:300],
            }
            for i in arms_mod.get("interventions", [])
        ],
        "arms": [
            {
                "label": a.get("label"),
                "type": a.get("type"),
                "description": a.get("description", "")[:300],
                "interventions": a.get("interventionNames", []),
            }
            for a in arms_mod.get("armGroups", [])
        ],
        "enrollment": design_mod.get("enrollmentInfo", {}),
        "eligibility": {
            "criteria": eligibility_mod.get("eligibilityCriteria", "")[:1000],
            "healthy_volunteers": eligibility_mod.get("healthyVolunteers"),
            "sex": eligibility_mod.get("sex"),
            "min_age": eligibility_mod.get("minimumAge"),
            "max_age": eligibility_mod.get("maximumAge"),
        },
        "primary_outcomes": outcomes_mod.get("primaryOutcomes", []),
        "secondary_outcomes": outcomes_mod.get("secondaryOutcomes", []),
        "brief_summary": desc_mod.get("briefSummary", ""),
        "detailed_description": desc_mod.get("detailedDescription", "")[:2000],
        "has_results": raw.get("hasResults", False),
        "results_available": bool(rs),
        "locations_count": len(contacts_mod.get("locations", [])),
    }


def get_safety_endpoints(args: dict) -> dict:
    """
    Extract safety-relevant primary and secondary outcomes from a trial.

    Filters outcomesModule entries whose measure or description contains
    safety-related keywords.
    """
    nct_id = args.get("nct_id", "").strip()
    if not nct_id:
        return _error("'nct_id' is required for get-safety-endpoints")

    raw = _fetch_study(nct_id)
    ps = raw.get("protocolSection", {})
    id_mod = ps.get("identificationModule", {})
    outcomes_mod = ps.get("outcomesModule", {})

    def is_safety_related(outcome: dict) -> bool:
        text = " ".join(
            [
                outcome.get("measure", ""),
                outcome.get("description", ""),
                outcome.get("timeFrame", ""),
            ]
        ).lower()
        return any(kw in text for kw in SAFETY_KEYWORDS)

    primary = outcomes_mod.get("primaryOutcomes", [])
    secondary = outcomes_mod.get("secondaryOutcomes", [])
    other = outcomes_mod.get("otherOutcomes", [])

    safety_primary = [o for o in primary if is_safety_related(o)]
    safety_secondary = [o for o in secondary if is_safety_related(o)]
    safety_other = [o for o in other if is_safety_related(o)]

    return {
        "nct_id": id_mod.get("nctId"),
        "title": id_mod.get("briefTitle"),
        "total_primary_outcomes": len(primary),
        "total_secondary_outcomes": len(secondary),
        "safety_primary_endpoints": safety_primary,
        "safety_secondary_endpoints": safety_secondary,
        "safety_other_endpoints": safety_other,
        "safety_endpoint_count": len(safety_primary)
        + len(safety_secondary)
        + len(safety_other),
        "all_primary_outcomes": primary,
        "all_secondary_outcomes": secondary,
    }


def get_serious_adverse_events(args: dict) -> dict:
    """
    Extract serious adverse events from the resultsSection of a completed trial.

    Pulls adverseEventsModule which contains SAE tables by organ class and term.
    """
    nct_id = args.get("nct_id", "").strip()
    if not nct_id:
        return _error("'nct_id' is required for get-serious-adverse-events")

    raw = _fetch_study(nct_id)
    ps = raw.get("protocolSection", {})
    rs = raw.get("resultsSection", {})
    id_mod = ps.get("identificationModule", {})

    if not rs:
        return {
            "nct_id": id_mod.get("nctId"),
            "title": id_mod.get("briefTitle"),
            "has_results": False,
            "message": (
                "No results posted for this trial. SAE data is only available "
                "after results have been submitted to ClinicalTrials.gov."
            ),
            "serious_adverse_events": [],
        }

    ae_mod = rs.get("adverseEventsModule", {})
    if not ae_mod:
        return {
            "nct_id": id_mod.get("nctId"),
            "title": id_mod.get("briefTitle"),
            "has_results": True,
            "message": "Results posted but no adverseEventsModule found.",
            "serious_adverse_events": [],
        }

    # Participant-level summary per group
    event_groups = ae_mod.get("eventGroups", [])
    group_summary = [
        {
            "group_id": g.get("id"),
            "title": g.get("title"),
            "description": g.get("description"),
            "deaths_num_affected": g.get("deathsNumAffected"),
            "deaths_num_at_risk": g.get("deathsNumAtRisk"),
            "serious_num_affected": g.get("seriousNumAffected"),
            "serious_num_at_risk": g.get("seriousNumAtRisk"),
            "other_num_affected": g.get("otherNumAffected"),
            "other_num_at_risk": g.get("otherNumAtRisk"),
        }
        for g in event_groups
    ]

    # Serious adverse event term-level data
    serious_events = ae_mod.get("seriousEvents", [])
    sae_records = []
    for event in serious_events:
        stats_by_group = {
            s.get("groupId"): {
                "num_events": s.get("numEvents"),
                "num_affected": s.get("numAffected"),
                "num_at_risk": s.get("numAtRisk"),
            }
            for s in event.get("stats", [])
        }
        sae_records.append(
            {
                "term": event.get("term"),
                "organ_system": event.get("organSystem"),
                "source_vocabulary": event.get("sourceVocabulary"),
                "assessment_type": event.get("assessmentType"),
                "notes": event.get("notes"),
                "stats_by_group": stats_by_group,
            }
        )

    # Also pull deaths separately
    death_events = [e for e in serious_events if "death" in (e.get("term") or "").lower()]

    return {
        "nct_id": id_mod.get("nctId"),
        "title": id_mod.get("briefTitle"),
        "has_results": True,
        "frequency_threshold": ae_mod.get("frequencyThreshold"),
        "time_frame": ae_mod.get("timeFrame"),
        "description": ae_mod.get("description"),
        "group_summary": group_summary,
        "serious_adverse_events": sae_records,
        "total_sae_terms": len(sae_records),
        "death_related_events": death_events,
    }


def compare_trial_arms(args: dict) -> dict:
    """
    Compare adverse event rates and outcomes across treatment arms in a trial.

    Pulls armGroups, adverseEventsModule, and baselineCharacteristicsModule
    to produce a side-by-side comparison.
    """
    nct_id = args.get("nct_id", "").strip()
    if not nct_id:
        return _error("'nct_id' is required for compare-trial-arms")

    raw = _fetch_study(nct_id)
    ps = raw.get("protocolSection", {})
    rs = raw.get("resultsSection", {})
    id_mod = ps.get("identificationModule", {})
    arms_mod = ps.get("armsInterventionsModule", {})

    # Protocol-level arm definitions
    arm_groups = [
        {
            "label": a.get("label"),
            "type": a.get("type"),
            "description": a.get("description", "")[:400],
            "interventions": a.get("interventionNames", []),
        }
        for a in arms_mod.get("armGroups", [])
    ]

    if not rs:
        return {
            "nct_id": id_mod.get("nctId"),
            "title": id_mod.get("briefTitle"),
            "has_results": False,
            "message": (
                "No results posted. Arm comparison requires posted results. "
                "Protocol arms are returned for reference."
            ),
            "protocol_arms": arm_groups,
            "arm_comparison": [],
        }

    ae_mod = rs.get("adverseEventsModule", {})
    baseline_mod = rs.get("baselineCharacteristicsModule", {})
    outcome_mod = rs.get("outcomeMeasuresModule", {})

    # Build arm comparison table keyed by eventGroup id
    event_groups = ae_mod.get("eventGroups", []) if ae_mod else []
    arm_comparison = [
        {
            "group_id": g.get("id"),
            "arm_title": g.get("title"),
            "description": g.get("description"),
            "serious_ae_affected": g.get("seriousNumAffected"),
            "serious_ae_at_risk": g.get("seriousNumAtRisk"),
            "other_ae_affected": g.get("otherNumAffected"),
            "other_ae_at_risk": g.get("otherNumAtRisk"),
            "deaths_affected": g.get("deathsNumAffected"),
            "deaths_at_risk": g.get("deathsNumAtRisk"),
            "serious_ae_rate_pct": _rate_pct(
                g.get("seriousNumAffected"), g.get("seriousNumAtRisk")
            ),
            "death_rate_pct": _rate_pct(
                g.get("deathsNumAffected"), g.get("deathsNumAtRisk")
            ),
        }
        for g in event_groups
    ]

    # Baseline participant counts per group
    baseline_groups = {}
    if baseline_mod:
        for grp in baseline_mod.get("groups", []):
            baseline_groups[grp.get("id")] = {
                "title": grp.get("title"),
                "description": grp.get("description"),
            }

    # Top-level outcome measures (summary, not full data)
    outcome_summaries = []
    if outcome_mod:
        for om in outcome_mod.get("outcomeMeasures", [])[:10]:
            outcome_summaries.append(
                {
                    "title": om.get("title"),
                    "type": om.get("type"),
                    "description": om.get("description", "")[:300],
                    "time_frame": om.get("timeFrame"),
                    "reporting_status": om.get("reportingStatus"),
                    "groups_count": len(om.get("groups", [])),
                }
            )

    # Identify which arm had lowest SAE rate (crude comparison)
    ranked = sorted(
        [a for a in arm_comparison if a["serious_ae_rate_pct"] is not None],
        key=lambda x: x["serious_ae_rate_pct"],
    )

    return {
        "nct_id": id_mod.get("nctId"),
        "title": id_mod.get("briefTitle"),
        "has_results": True,
        "protocol_arms": arm_groups,
        "arm_comparison": arm_comparison,
        "arms_ranked_by_sae_rate": ranked,
        "baseline_groups": baseline_groups,
        "outcome_summaries": outcome_summaries,
        "ae_time_frame": ae_mod.get("timeFrame") if ae_mod else None,
        "ae_frequency_threshold": ae_mod.get("frequencyThreshold") if ae_mod else None,
    }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _rate_pct(num: Any, denom: Any) -> float | None:
    """Compute percentage rate, returning None when inputs are absent or zero."""
    try:
        n = int(num)
        d = int(denom)
        if d == 0:
            return None
        return round(100.0 * n / d, 2)
    except (TypeError, ValueError):
        return None


def _error(message: str) -> dict:
    return {"error": True, "message": message}


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

def get_eligibility_criteria(args: dict) -> dict:
    """
    Extract eligibility criteria (inclusion/exclusion) from a trial record.

    Maps to: GET /studies/{nctId} -> eligibilityModule
    """
    nct_id = args.get("nct_id", "").strip().upper()
    if not nct_id:
        return _error("nct_id is required")

    try:
        study = _fetch_study(nct_id)
    except RuntimeError as exc:
        return _error(str(exc))

    protocol = study.get("protocolSection", {})
    elig = protocol.get("eligibilityModule", {})

    if not elig:
        return {"status": "ok", "nct_id": nct_id, "message": "No eligibility module found", "criteria": {}}

    criteria_text = elig.get("eligibilityCriteria", "")
    # Parse into inclusion/exclusion if structured
    inclusion = []
    exclusion = []
    current = None
    for line in criteria_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if "inclusion" in lower and "criteria" in lower:
            current = "inclusion"
            continue
        if "exclusion" in lower and "criteria" in lower:
            current = "exclusion"
            continue
        if current == "inclusion":
            inclusion.append(stripped.lstrip("•-* "))
        elif current == "exclusion":
            exclusion.append(stripped.lstrip("•-* "))

    return {
        "status": "ok",
        "nct_id": nct_id,
        "criteria": {
            "sex": elig.get("sex", "ALL"),
            "minimum_age": elig.get("minimumAge", "N/A"),
            "maximum_age": elig.get("maximumAge", "N/A"),
            "healthy_volunteers": elig.get("healthyVolunteers", False),
            "inclusion_criteria": inclusion if inclusion else ["(See raw text)"],
            "exclusion_criteria": exclusion if exclusion else ["(See raw text)"],
            "raw_text": criteria_text[:3000] if not (inclusion or exclusion) else None,
        },
        "data_source": "clinicaltrials.gov",
    }


def get_study_design(args: dict) -> dict:
    """
    Extract study design details — randomization, blinding, masking, allocation.

    Maps to: GET /studies/{nctId} -> designModule
    """
    nct_id = args.get("nct_id", "").strip().upper()
    if not nct_id:
        return _error("nct_id is required")

    try:
        study = _fetch_study(nct_id)
    except RuntimeError as exc:
        return _error(str(exc))

    protocol = study.get("protocolSection", {})
    design = protocol.get("designModule", {})
    ident = protocol.get("identificationModule", {})

    if not design:
        return {"status": "ok", "nct_id": nct_id, "message": "No design module found", "design": {}}

    design_info = design.get("designInfo", {})
    masking = design_info.get("maskingInfo", {})
    enrollment = design.get("enrollmentInfo", {})

    return {
        "status": "ok",
        "nct_id": nct_id,
        "title": ident.get("briefTitle", ""),
        "design": {
            "study_type": design.get("studyType", "N/A"),
            "phases": design.get("phases", []),
            "allocation": design_info.get("allocation", "N/A"),
            "intervention_model": design_info.get("interventionModel", "N/A"),
            "primary_purpose": design_info.get("primaryPurpose", "N/A"),
            "masking": {
                "type": masking.get("masking", "NONE"),
                "who_masked": masking.get("whoMasked", []),
            },
            "enrollment": {
                "count": enrollment.get("count", "N/A"),
                "type": enrollment.get("type", "N/A"),
            },
            "number_of_arms": design_info.get("numberOfArms", "N/A"),
        },
        "data_source": "clinicaltrials.gov",
    }


TOOLS: dict[str, Any] = {
    "search-trials": search_trials,
    "get-trial": get_trial,
    "get-safety-endpoints": get_safety_endpoints,
    "get-serious-adverse-events": get_serious_adverse_events,
    "compare-trial-arms": compare_trial_arms,
    "get-eligibility-criteria": get_eligibility_criteria,
    "get-study-design": get_study_design,
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(
            json.dumps({"error": True, "message": f"Invalid JSON on stdin: {exc}"}),
            flush=True,
        )
        sys.exit(1)

    tool_name = payload.get("tool", "")
    arguments = payload.get("arguments", {})

    handler = TOOLS.get(tool_name)
    if handler is None:
        known = list(TOOLS.keys())
        print(
            json.dumps(
                {
                    "error": True,
                    "message": f"Unknown tool '{tool_name}'. Known tools: {known}",
                }
            ),
            flush=True,
        )
        sys.exit(1)

    try:
        result = handler(arguments)
    except RuntimeError as exc:
        result = {"status": "error", "error": True, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        result = {
            "status": "error",
            "error": True,
            "message": f"Unexpected error in '{tool_name}': {type(exc).__name__}: {exc}",
        }

    # Ensure all successful responses have a "status" field
    if "status" not in result and not result.get("error"):
        result["status"] = "ok"

    print(json.dumps(result, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
