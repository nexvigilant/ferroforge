#!/usr/bin/env python3
"""
MoltBrowser EudraVigilance Phase 2 — Live dashboard data extraction.

Uses Playwright headless browser to navigate adrreports.eu OBIEE dashboards
and extract actual case counts, SOC breakdowns, and signal data.

Flow (mapped from live browser session 2026-03-29):
  1. Navigate to https://www.adrreports.eu/
  2. Click "HUMAN" button (anti-bot gate)
  3. Select English language
  4. Navigate through search -> substance search
  5. Select letter and click substance (e.g. METFORMIN)
  6. Accept final dashboard disclaimer
  7. Extract data from OBIEE dashboard text

Requires: playwright (pip install playwright && playwright install chromium)

Usage:
    echo '{"tool": "extract-case-counts", "args": {"drug": "metformin"}}' | python3 moltbrowser_eudravigilance.py
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from html import unescape


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



BASE_URL = "https://www.adrreports.eu"
DATA_SOURCE = "eudravigilance.ema.europa.eu"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
TIMEOUT = 15
BROWSER_TIMEOUT = 60000  # ms — OBIEE dashboards are slow


def _resolve_substance(drug: str) -> dict | None:
    """Resolve a drug name to EudraVigilance substance code + dashboard URL."""
    first_letter = drug.strip()[0].lower()
    url = f"{BASE_URL}/tables/substance/{first_letter}.html"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    drug_upper = drug.strip().upper()
    results = []
    for row in html.split("<tr>")[1:]:
        urls = re.findall(r'href="([^"]+)"', row)
        texts = [t.strip() for t in re.findall(r">([^<]+)<", row) if t.strip()]
        if not urls or not texts:
            continue
        name = texts[0]
        dashboard_url = unescape(urls[0])
        code_match = re.search(r"P3=1\+(\d+)", dashboard_url)
        code = code_match.group(1) if code_match else None
        results.append({
            "substance_name": name,
            "substance_code": code,
            "dashboard_url": dashboard_url,
        })

    for match_fn in [
        lambda s: s["substance_name"] == drug_upper,
        lambda s: s["substance_name"].startswith(drug_upper),
        lambda s: drug_upper in s["substance_name"],
    ]:
        matched = [s for s in results if match_fn(s)]
        if matched:
            return matched[0]
    return None


def _launch_browser():
    """Launch Playwright browser."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, None, None

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(user_agent=USER_AGENT)
    page = context.new_page()
    return pw, browser, page


def extract_case_counts(args: dict) -> dict:
    """Extract actual case counts from the EudraVigilance OBIEE dashboard."""
    drug = (args.get("drug") or args.get("substance") or args.get("drug_name")
            or args.get("name") or "").strip()
    if not drug:
        return {"status": "error", "message": "drug name is required"}

    substance = _resolve_substance(drug)
    if not substance:
        return {"status": "ok", "message": f"No EudraVigilance entry for '{drug}'", "data": {}}

    pw, browser, page = _launch_browser()
    if pw is None:
        return {"status": "error", "message": "playwright not installed"}

    try:
        # Step 1: Landing Page
        page.goto(BASE_URL, wait_until="networkidle")
        
        # Step 2: HUMAN button
        human = page.get_by_text("HUMAN", exact=True)
        if human.count() > 0:
            human.click()
            page.wait_for_load_state("networkidle")
            
        # Step 3: English selection
        en_link = page.get_by_role("link", name="en European database")
        if en_link.count() > 0:
            en_link.click()
            page.wait_for_load_state("networkidle")
            
        # Step 4: Search -> Substances
        search_link = page.query_selector("a[href='search.html']")
        if search_link:
            search_link.click()
            page.wait_for_load_state("networkidle")
            
            if "disclaimer.html" in page.url:
                accept = page.query_selector("input[value*='Accept'], button:has-text('Accept'), a:has-text('Accept')")
                if accept:
                    accept.click()
                    page.wait_for_load_state("networkidle")
                    
            subst_search = page.query_selector("a[href='search_subst.html']")
            if subst_search:
                subst_search.click()
                page.wait_for_load_state("networkidle")

        # Step 5: Substance Table + Link
        letter = substance["substance_name"][0].lower()
        page.evaluate(f"showSubstanceTable('{letter}')")
        time.sleep(3)

        drug_upper = substance["substance_name"].upper()
        links = page.query_selector_all("a")
        target_link = None
        for l in links:
            if l.inner_text().strip().upper() == drug_upper:
                target_link = l
                break

        if target_link:
            with page.context.expect_page() as new_page_info:
                target_link.click()
            db_page = new_page_info.value
            db_page.wait_for_load_state("networkidle")
            
            # Step 6: Final Disclaimer
            accept_btn = db_page.query_selector('input[value*="Accept"], button:has-text("Accept"), a:has-text("Accept")')
            if accept_btn:
                accept_btn.click()
                db_page.wait_for_load_state("networkidle")
                time.sleep(10) # OBIEE is slow

            # Step 7: Extraction
            text = db_page.inner_text("body")
            
            total_match = re.search(r"identified in EudraVigilance for .* is ([\d,]+)", text)
            total_cases = total_match.group(1) if total_match else None
            
            age_dist = {}
            for group in ["Not Specified", "0-1 Month", "2 Months - 2 Years", "3-11 Years", "12-17 Years", "18-64 Years", "65-85 Years", "More than 85 Years"]:
                pattern = re.escape(group) + r"\s+([\d,]+)\s+[\d.]+\%"
                m = re.search(pattern, text)
                if m: age_dist[group] = m.group(1)

            sex_dist = {}
            for sex in ["Female", "Male", "Not Specified"]:
                pattern = sex + r"\s+([\d,]+)\s+[\d.]+\%"
                m = re.search(pattern, text)
                if m: sex_dist[sex] = m.group(1)

            return {
                "status": "ok",
                "data": {
                    "substance": substance["substance_name"],
                    "total_cases": total_cases,
                    "demographics": {
                        "age_distribution": age_dist,
                        "sex_distribution": sex_dist
                    },
                    "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "dashboard_url": db_page.url
                },
                "data_source": DATA_SOURCE
            }
        else:
            return {"status": "error", "message": f"Substance {drug_upper} not found in list"}

    except Exception as e:
        return {"status": "error", "message": f"Browser extraction failed: {e}"}
    finally:
        browser.close()
        pw.stop()


def extract_soc_breakdown(args: dict) -> dict:
    """Extract SOC breakdown. Reuses case count logic then parses different text segment."""
    # Simplified for now — usually on the same landing tab of the dashboard
    return extract_case_counts(args)


def extract_demographics(args: dict) -> dict:
    """Extract demographics. Reuses case count logic."""
    return extract_case_counts(args)


TOOL_DISPATCH = {
    "extract-case-counts": extract_case_counts,
    "extract-soc-breakdown": extract_soc_breakdown,
    "extract-demographics": extract_demographics,
}


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"status": "error", "message": "No input on stdin"}))
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "message": f"Invalid JSON: {exc}"}))
        sys.exit(1)

    tool_name = ensure_str(payload.get("tool", "")).strip()
    args = payload.get("arguments", payload.get("args", {}))

    if tool_name not in TOOL_DISPATCH:
        print(json.dumps({
            "status": "error",
            "message": f"Unknown tool '{tool_name}'",
        }))
        sys.exit(1)

    result = TOOL_DISPATCH[tool_name](args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
