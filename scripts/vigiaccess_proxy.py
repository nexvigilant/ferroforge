#!/usr/bin/env python3
"""
VigiAccess (WHO) Proxy — routes MoltBrowser hub tool calls for vigiaccess.org.

Usage:
    echo '{"tool": "search-reports", "args": {"medicine": "metformin"}}' | python3 vigiaccess_proxy.py

VigiAccess uses Fable.Remoting over HTTPS. Requests are JSON; responses are
MessagePack (application/vnd.msgpack). This proxy includes a minimal stdlib-only
MessagePack decoder to handle responses without external dependencies.

Reads a single JSON object from stdin, dispatches to the appropriate handler,
writes a structured JSON response to stdout. No external dependencies — stdlib only.
"""

from __future__ import annotations

import json
import re
import struct
import sys
import urllib.error
import urllib.request
from typing import Any

BASE_URL = "https://www.vigiaccess.org/protocol/IProtocol"
REQUEST_TIMEOUT = 10
USER_AGENT = "NexVigilant-FerroForge/1.0 (ferroforge@nexvigilant.com)"

# Zero-width characters injected by VigiAccess into strings (anti-scraping).
_ZW_RE = re.compile(
    r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\u034f\u00ad]"
)


# ---------------------------------------------------------------------------
# Minimal MessagePack decoder (stdlib only, covers types returned by VigiAccess)
# ---------------------------------------------------------------------------

def _decode_msgpack(data: bytes, offset: int = 0):
    """Decode one MessagePack value from *data* starting at *offset*.

    Returns (value, new_offset).  Supports: nil, bool, positive/negative fixint,
    uint8/16/32, int8/16/32, float32/64, fixstr/str8/str16, fixarray/array16/array32,
    fixmap/map16, bin8/bin16.  Raises ValueError on unsupported types.
    """
    b = data[offset]

    # nil
    if b == 0xC0:
        return None, offset + 1
    # false / true
    if b == 0xC2:
        return False, offset + 1
    if b == 0xC3:
        return True, offset + 1

    # positive fixint 0x00-0x7f
    if b <= 0x7F:
        return b, offset + 1
    # negative fixint 0xe0-0xff
    if b >= 0xE0:
        return b - 256, offset + 1

    # unsigned integers
    if b == 0xCC:
        return data[offset + 1], offset + 2
    if b == 0xCD:
        return struct.unpack(">H", data[offset + 1 : offset + 3])[0], offset + 3
    if b == 0xCE:
        return struct.unpack(">I", data[offset + 1 : offset + 5])[0], offset + 5

    # signed integers
    if b == 0xD0:
        return struct.unpack(">b", data[offset + 1 : offset + 2])[0], offset + 2
    if b == 0xD1:
        return struct.unpack(">h", data[offset + 1 : offset + 3])[0], offset + 3
    if b == 0xD2:
        return struct.unpack(">i", data[offset + 1 : offset + 5])[0], offset + 5

    # float 32 / 64
    if b == 0xCA:
        return struct.unpack(">f", data[offset + 1 : offset + 5])[0], offset + 5
    if b == 0xCB:
        return struct.unpack(">d", data[offset + 1 : offset + 9])[0], offset + 9

    # fixstr 0xa0-0xbf
    if 0xA0 <= b <= 0xBF:
        n = b & 0x1F
        offset += 1
        return data[offset : offset + n].decode("utf-8", errors="replace"), offset + n
    # str 8
    if b == 0xD9:
        n = data[offset + 1]
        offset += 2
        return data[offset : offset + n].decode("utf-8", errors="replace"), offset + n
    # str 16
    if b == 0xDA:
        n = struct.unpack(">H", data[offset + 1 : offset + 3])[0]
        offset += 3
        return data[offset : offset + n].decode("utf-8", errors="replace"), offset + n
    # str 32
    if b == 0xDB:
        n = struct.unpack(">I", data[offset + 1 : offset + 5])[0]
        offset += 5
        return data[offset : offset + n].decode("utf-8", errors="replace"), offset + n

    # bin 8 / bin 16 (skip over, return as bytes)
    if b == 0xC4:
        n = data[offset + 1]
        offset += 2
        return data[offset : offset + n], offset + n
    if b == 0xC5:
        n = struct.unpack(">H", data[offset + 1 : offset + 3])[0]
        offset += 3
        return data[offset : offset + n], offset + n

    # fixarray 0x90-0x9f
    if 0x90 <= b <= 0x9F:
        n = b & 0x0F
        offset += 1
        items = []
        for _ in range(n):
            val, offset = _decode_msgpack(data, offset)
            items.append(val)
        return items, offset
    # array 16
    if b == 0xDC:
        n = struct.unpack(">H", data[offset + 1 : offset + 3])[0]
        offset += 3
        items = []
        for _ in range(n):
            val, offset = _decode_msgpack(data, offset)
            items.append(val)
        return items, offset
    # array 32
    if b == 0xDD:
        n = struct.unpack(">I", data[offset + 1 : offset + 5])[0]
        offset += 5
        items = []
        for _ in range(n):
            val, offset = _decode_msgpack(data, offset)
            items.append(val)
        return items, offset

    # fixmap 0x80-0x8f
    if 0x80 <= b <= 0x8F:
        n = b & 0x0F
        offset += 1
        d = {}
        for _ in range(n):
            k, offset = _decode_msgpack(data, offset)
            v, offset = _decode_msgpack(data, offset)
            d[k] = v
        return d, offset
    # map 16
    if b == 0xDE:
        n = struct.unpack(">H", data[offset + 1 : offset + 3])[0]
        offset += 3
        d = {}
        for _ in range(n):
            k, offset = _decode_msgpack(data, offset)
            v, offset = _decode_msgpack(data, offset)
            d[k] = v
        return d, offset

    raise ValueError(f"Unsupported msgpack type: 0x{b:02x} at offset {offset}")


def _clean_str(s: str) -> str:
    """Remove zero-width / soft-hyphen characters injected by VigiAccess."""
    return _ZW_RE.sub("", s)


def _clean(obj: Any) -> Any:
    """Recursively clean strings in decoded msgpack data."""
    if isinstance(obj, str):
        return _clean_str(obj)
    if isinstance(obj, list):
        return [_clean(x) for x in obj]
    if isinstance(obj, dict):
        return {_clean(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, bytes):
        return None  # binary blobs not used in our data
    return obj


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _post_rpc(method: str, body_json: str) -> bytes:
    """POST to VigiAccess Fable.Remoting endpoint. Returns raw response bytes."""
    url = f"{BASE_URL}/{method}"
    req = urllib.request.Request(
        url,
        data=body_json.encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "*/*",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.read()
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", str(exc))
        raise RuntimeError(f"VigiAccess request failed: {reason}") from exc


def _rpc_call(method: str, body_json: str) -> Any:
    """Call a Fable.Remoting method and return decoded, cleaned result."""
    raw = _post_rpc(method, body_json)
    result, _ = _decode_msgpack(raw)
    return _clean(result)


def _unavailable_response(message: str = "") -> dict:
    msg = message or "VigiAccess service unreachable. Try again later."
    return {"status": "unavailable", "message": msg}


# ---------------------------------------------------------------------------
# Search helper — shared by all tools that need to resolve medicine → DrugId
# ---------------------------------------------------------------------------

def _search_drug(medicine: str):
    """Search VigiAccess for a medicine name. Returns list of Drug dicts."""
    body = json.dumps([medicine])
    raw_drugs = _rpc_call("search", body)
    if not isinstance(raw_drugs, list):
        return []
    drugs = []
    for drug_raw in raw_drugs:
        # Drug: [DrugId_option, ActiveIngredient_option, TradeName_option]
        drug_id_union = drug_raw[0]  # [0, [0, "hash"]]
        active_union = drug_raw[1]   # [0, "name"]
        trade_union = drug_raw[2]    # [1, [0, "name"]] or [0]

        encrypted_hash = None
        if (isinstance(drug_id_union, list) and len(drug_id_union) >= 2
                and drug_id_union[0] == 0 and isinstance(drug_id_union[1], list)
                and len(drug_id_union[1]) >= 2):
            encrypted_hash = drug_id_union[1][1]

        active = None
        if isinstance(active_union, list) and len(active_union) >= 2 and active_union[0] == 0:
            active = active_union[1]

        trade = None
        if isinstance(trade_union, list) and len(trade_union) >= 2 and trade_union[0] == 1:
            inner = trade_union[1]
            if isinstance(inner, list) and len(inner) >= 2:
                trade = inner[1]

        drugs.append({
            "encrypted_id": encrypted_hash,
            "active_ingredient": active,
            "trade_name": trade,
        })
    return drugs


def _get_distribution(encrypted_id: str):
    """Fetch the full distribution data for a drug by its encrypted ID.

    Returns a dict with keys: total_count, reactions, regions, age_groups, sex, years.
    """
    body = json.dumps([{"DrugId": {"Encrypted": encrypted_id}}])
    dist = _rpc_call("distribution", body)
    if not isinstance(dist, list) or len(dist) < 6:
        raise RuntimeError("Unexpected distribution response format")

    # Distribution: [TotalCount, Reaction[], Region[], AgeGroup[], Sex[], Year[]]
    total_count = dist[0]

    reactions = []
    for rxn in dist[1]:
        # Reaction: [SocId_option, Description_option, Count]
        desc_union = rxn[1]
        desc = desc_union[1] if isinstance(desc_union, list) and len(desc_union) >= 2 else str(desc_union)
        count = rxn[2]
        reactions.append({"soc": desc, "count": count})

    regions = [{"region": item[0], "count": item[1]} for item in dist[2]]
    age_groups = [{"age_group": item[0], "count": item[1]} for item in dist[3]]
    sex = [{"sex": item[0], "count": item[1]} for item in dist[4]]
    years = [{"year": item[0], "count": item[1]} for item in dist[5]]

    return {
        "total_count": total_count,
        "reactions": reactions,
        "regions": regions,
        "age_groups": age_groups,
        "sex": sex,
        "years": years,
    }


def _resolve_and_distribute(medicine: str):
    """Search for a medicine, pick the first match, fetch distribution."""
    drugs = _search_drug(medicine)
    if not drugs:
        return None, None
    # Pick the first result (best match)
    best = drugs[0]
    if not best.get("encrypted_id"):
        return best, None
    dist = _get_distribution(best["encrypted_id"])
    return best, dist


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def search_reports(args: dict) -> dict:
    """Search VigiBase reports by medicine name."""
    medicine = (args.get("medicine") or args.get("drug_name") or args.get("drug")
                or args.get("name") or args.get("substance") or args.get("query") or "").strip()
    if not medicine:
        return {"status": "error", "message": "medicine is required (also accepts: drug_name, drug, name, substance)"}

    try:
        drugs = _search_drug(medicine)
    except RuntimeError as exc:
        return _unavailable_response(str(exc))
    except Exception as exc:
        return {"status": "error", "message": f"Search failed: {exc}"}

    if not drugs:
        return {"status": "ok", "count": 0, "results": [],
                "message": f"No results found for '{medicine}'"}

    # For the first/best match, get the total ICSR count
    best = drugs[0]
    total_count = 0
    if best.get("encrypted_id"):
        try:
            dist = _get_distribution(best["encrypted_id"])
            total_count = dist["total_count"]
        except Exception:
            pass  # count stays 0; search results still returned

    results = []
    for d in drugs:
        entry = {"active_ingredient": d["active_ingredient"]}
        if d.get("trade_name"):
            entry["trade_name"] = d["trade_name"]
        results.append(entry)

    return {
        "status": "ok",
        "count": total_count,
        "medicine": medicine,
        "active_ingredient": best.get("active_ingredient"),
        "total_reports": total_count,
        "results": results,
    }


def get_adverse_reactions(args: dict) -> dict:
    """Get adverse reaction breakdown by SOC for a medicine."""
    medicine = (args.get("medicine") or args.get("drug_name") or args.get("drug")
                or args.get("name") or args.get("substance") or args.get("query") or "").strip()
    if not medicine:
        return {"status": "error", "message": "medicine is required (also accepts: drug_name, drug, name, substance)"}

    try:
        best, dist = _resolve_and_distribute(medicine)
    except RuntimeError as exc:
        return _unavailable_response(str(exc))
    except Exception as exc:
        return {"status": "error", "message": f"Request failed: {exc}"}

    if not best:
        return {"status": "ok", "data": {"medicine": medicine, "reactions": []},
                "message": f"No results found for '{medicine}'"}
    if not dist:
        return {"status": "error", "message": "Could not retrieve distribution data"}

    total = dist["total_count"]
    reactions = []
    for rxn in dist["reactions"]:
        pct = round(rxn["count"] / total * 100, 1) if total > 0 else 0
        reactions.append({
            "soc": rxn["soc"],
            "count": rxn["count"],
            "percentage": pct,
        })

    return {
        "status": "ok",
        "data": {
            "medicine": medicine,
            "active_ingredient": best.get("active_ingredient"),
            "total_reports": total,
            "reactions": reactions,
        },
    }


def get_reporter_distribution(args: dict) -> dict:
    """Get report distribution by reporter type.

    Note: VigiAccess does not expose reporter-type breakdown in its public
    interface. This tool returns the geographic (continent) distribution as
    the closest available proxy, clearly labeled. The VigiAccess UI itself
    does not show reporter-type data.
    """
    medicine = (args.get("medicine") or args.get("drug_name") or args.get("drug")
                or args.get("name") or args.get("substance") or args.get("query") or "").strip()
    if not medicine:
        return {"status": "error", "message": "medicine is required (also accepts: drug_name, drug, name, substance)"}

    try:
        best, dist = _resolve_and_distribute(medicine)
    except RuntimeError as exc:
        return _unavailable_response(str(exc))
    except Exception as exc:
        return {"status": "error", "message": f"Request failed: {exc}"}

    if not best:
        return {"status": "ok", "data": {"medicine": medicine, "distribution": []},
                "message": f"No results found for '{medicine}'"}
    if not dist:
        return {"status": "error", "message": "Could not retrieve distribution data"}

    # VigiAccess public API does not provide reporter-type breakdown.
    # Return what we have and note the limitation.
    return {
        "status": "ok",
        "data": {
            "medicine": medicine,
            "active_ingredient": best.get("active_ingredient"),
            "total_reports": dist["total_count"],
            "note": "VigiAccess does not publicly expose reporter-type distribution. "
                    "Geographic distribution is provided instead.",
            "distribution": dist["regions"],
        },
    }


def get_age_distribution(args: dict) -> dict:
    """Get case distribution by patient age group."""
    medicine = (args.get("medicine") or args.get("drug_name") or args.get("drug")
                or args.get("name") or args.get("substance") or args.get("query") or "").strip()
    if not medicine:
        return {"status": "error", "message": "medicine is required (also accepts: drug_name, drug, name, substance)"}

    try:
        best, dist = _resolve_and_distribute(medicine)
    except RuntimeError as exc:
        return _unavailable_response(str(exc))
    except Exception as exc:
        return {"status": "error", "message": f"Request failed: {exc}"}

    if not best:
        return {"status": "ok", "data": {"medicine": medicine, "distribution": []},
                "message": f"No results found for '{medicine}'"}
    if not dist:
        return {"status": "error", "message": "Could not retrieve distribution data"}

    total = dist["total_count"]
    age_data = []
    for ag in dist["age_groups"]:
        pct = round(ag["count"] / total * 100, 1) if total > 0 else 0
        age_data.append({
            "age_group": ag["age_group"],
            "count": ag["count"],
            "percentage": pct,
        })

    return {
        "status": "ok",
        "data": {
            "medicine": medicine,
            "active_ingredient": best.get("active_ingredient"),
            "total_reports": total,
            "distribution": age_data,
        },
    }


def get_region_distribution(args: dict) -> dict:
    """Get geographic distribution of reports by WHO region."""
    medicine = (args.get("medicine") or args.get("drug_name") or args.get("drug")
                or args.get("name") or args.get("substance") or args.get("query") or "").strip()
    if not medicine:
        return {"status": "error", "message": "medicine is required (also accepts: drug_name, drug, name, substance)"}

    try:
        best, dist = _resolve_and_distribute(medicine)
    except RuntimeError as exc:
        return _unavailable_response(str(exc))
    except Exception as exc:
        return {"status": "error", "message": f"Request failed: {exc}"}

    if not best:
        return {"status": "ok", "data": {"medicine": medicine, "distribution": []},
                "message": f"No results found for '{medicine}'"}
    if not dist:
        return {"status": "error", "message": "Could not retrieve distribution data"}

    total = dist["total_count"]
    region_data = []
    for rg in dist["regions"]:
        pct = round(rg["count"] / total * 100, 1) if total > 0 else 0
        region_data.append({
            "region": rg["region"],
            "count": rg["count"],
            "percentage": pct,
        })

    return {
        "status": "ok",
        "data": {
            "medicine": medicine,
            "active_ingredient": best.get("active_ingredient"),
            "total_reports": total,
            "distribution": region_data,
        },
    }


def get_sex_distribution(args: dict) -> dict:
    """Get report distribution by patient sex."""
    medicine = (args.get("medicine") or args.get("drug_name") or args.get("drug")
                or args.get("name") or args.get("substance") or args.get("query") or "").strip()
    if not medicine:
        return {"status": "error", "message": "medicine is required (also accepts: drug_name, drug, name, substance)"}

    try:
        best, dist = _resolve_and_distribute(medicine)
    except RuntimeError as exc:
        return _unavailable_response(str(exc))
    except Exception as exc:
        return {"status": "error", "message": f"Request failed: {exc}"}

    if not best:
        return {"status": "ok", "data": {"medicine": medicine, "distribution": []},
                "message": f"No results found for '{medicine}'"}
    if not dist:
        return {"status": "error", "message": "Could not retrieve distribution data"}

    total = dist["total_count"]
    sex_data = []
    for sx in dist["sex"]:
        pct = round(sx["count"] / total * 100, 1) if total > 0 else 0
        sex_data.append({
            "sex": sx["sex"],
            "count": sx["count"],
            "percentage": pct,
        })

    return {
        "status": "ok",
        "data": {
            "medicine": medicine,
            "active_ingredient": best.get("active_ingredient"),
            "total_reports": total,
            "distribution": sex_data,
        },
    }


def get_year_distribution(args: dict) -> dict:
    """Get report distribution by reporting year for temporal trend analysis."""
    medicine = (args.get("medicine") or args.get("drug_name") or args.get("drug")
                or args.get("name") or args.get("substance") or args.get("query") or "").strip()
    if not medicine:
        return {"status": "error", "message": "medicine is required (also accepts: drug_name, drug, name, substance)"}

    try:
        best, dist = _resolve_and_distribute(medicine)
    except RuntimeError as exc:
        return _unavailable_response(str(exc))
    except Exception as exc:
        return {"status": "error", "message": f"Request failed: {exc}"}

    if not best:
        return {"status": "ok", "data": {"medicine": medicine, "distribution": []},
                "message": f"No results found for '{medicine}'"}
    if not dist:
        return {"status": "error", "message": "Could not retrieve distribution data"}

    total = dist["total_count"]
    year_data = []
    for yr in dist["years"]:
        pct = round(yr["count"] / total * 100, 1) if total > 0 else 0
        year_data.append({
            "year": yr["year"],
            "count": yr["count"],
            "percentage": pct,
        })

    return {
        "status": "ok",
        "data": {
            "medicine": medicine,
            "active_ingredient": best.get("active_ingredient"),
            "total_reports": total,
            "distribution": year_data,
        },
    }


TOOL_DISPATCH = {
    "search-reports": search_reports,
    "get-adverse-reactions": get_adverse_reactions,
    "get-reporter-distribution": get_reporter_distribution,
    "get-age-distribution": get_age_distribution,
    "get-region-distribution": get_region_distribution,
    "get-sex-distribution": get_sex_distribution,
    "get-year-distribution": get_year_distribution,
}


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        result = {"status": "error", "message": "No input received on stdin"}
        print(json.dumps(result))
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        result = {"status": "error", "message": f"Invalid JSON input: {exc}"}
        print(json.dumps(result))
        sys.exit(1)

    tool_name = payload.get("tool", "").strip()
    args = payload.get("arguments", payload.get("args", {}))

    if tool_name not in TOOL_DISPATCH:
        known = list(TOOL_DISPATCH.keys())
        result = {
            "status": "error",
            "message": f"Unknown tool '{tool_name}'. Known tools: {known}",
        }
        print(json.dumps(result))
        sys.exit(1)

    handler = TOOL_DISPATCH[tool_name]
    result = handler(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
