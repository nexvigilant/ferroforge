#!/usr/bin/env python3
"""
PubMed E-utilities proxy for NexVigilant Station.

Implements the 5 tools defined in configs/pubmed.json:
  - search-articles
  - get-abstract
  - get-citations
  - search-case-reports
  - search-signal-literature

Reads a JSON request from stdin, dispatches to the appropriate handler,
and writes a JSON response to stdout.  All HTTP calls go through urllib
(stdlib only).  XML is parsed with xml.etree.ElementTree (stdlib only).

PubMed E-utilities courtesy parameters are appended to every request:
  &tool=nexvigilant&email=dev@nexvigilant.com
"""

import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
COURTESY = "&tool=nexvigilant&email=dev@nexvigilant.com"
DEFAULT_LIMIT = 10
MAX_LIMIT = 50
# NCBI asks for no more than 3 requests / second without an API key.
REQUEST_DELAY = 0.35  # seconds between sequential requests
_RETRY_CODES = {429, 503}
_MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(url: str) -> bytes:
    """Perform a GET request and return the response body."""
    import urllib.error
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "NexVigilant-Station/1.0 (dev@nexvigilant.com)"},
    )
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in _RETRY_CODES and attempt < _MAX_RETRIES - 1:
                time.sleep(0.2 * (3 ** attempt))
                last_exc = exc
                continue
            raise
        except urllib.error.URLError as exc:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(0.2 * (3 ** attempt))
                last_exc = exc
                continue
            raise
    raise RuntimeError(f"Failed after {_MAX_RETRIES} retries: {last_exc}")


def _get_json(url: str) -> dict:
    return json.loads(_get(url).decode("utf-8"))


def _get_xml(url: str) -> ET.Element:
    return ET.fromstring(_get(url).decode("utf-8"))


# ---------------------------------------------------------------------------
# XML parsing helpers
# ---------------------------------------------------------------------------

def _text(element: ET.Element | None, default: str = "") -> str:
    """Return stripped text content of an element, or default."""
    if element is None:
        return default
    return (element.text or "").strip()


def _parse_article(article_el: ET.Element) -> dict:
    """
    Extract structured metadata from a PubMed <PubmedArticle> XML element.

    Fields returned:
      pmid, title, abstract, authors, journal, year, pub_types, doi
    """
    medline = article_el.find(".//MedlineCitation")
    if medline is None:
        return {}

    pmid = _text(medline.find("PMID"))

    article = medline.find("Article")
    if article is None:
        return {"pmid": pmid}

    title = _text(article.find("ArticleTitle"))

    # Abstract — may be structured (multiple AbstractText elements)
    abstract_parts = []
    for ab in article.findall(".//AbstractText"):
        label = ab.get("Label", "")
        text = (ab.text or "").strip()
        if label:
            abstract_parts.append(f"{label}: {text}")
        elif text:
            abstract_parts.append(text)
    abstract = " ".join(abstract_parts)

    # Authors
    authors = []
    for author in article.findall(".//Author"):
        last = _text(author.find("LastName"))
        fore = _text(author.find("ForeName"))
        if last:
            authors.append(f"{last} {fore}".strip())
        else:
            collective = _text(author.find("CollectiveName"))
            if collective:
                authors.append(collective)

    # Journal
    journal_el = article.find("Journal")
    journal = ""
    year = ""
    if journal_el is not None:
        journal = _text(journal_el.find("Title")) or _text(
            journal_el.find("ISOAbbreviation")
        )
        pub_date = journal_el.find(".//PubDate")
        if pub_date is not None:
            year = _text(pub_date.find("Year")) or _text(pub_date.find("MedlineDate"))

    # Publication types
    pub_types = [
        _text(pt)
        for pt in article.findall(".//PublicationType")
        if _text(pt)
    ]

    # DOI
    doi = ""
    for loc_id in article.findall(".//ELocationID"):
        if loc_id.get("EIdType") == "doi":
            doi = _text(loc_id)
            break

    return {
        "pmid": pmid,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "journal": journal,
        "year": year,
        "pub_types": pub_types,
        "doi": doi,
    }


# ---------------------------------------------------------------------------
# Parameter resolution helpers
# ---------------------------------------------------------------------------

def _resolve_query(params: dict) -> str:
    """Resolve query from any known alias. Agents use varied parameter names."""
    return (params.get("query") or params.get("search_query") or params.get("search")
            or params.get("q") or params.get("drug_name") or params.get("drug")
            or "").strip()


def _resolve_drug(params: dict) -> str:
    """Resolve drug name from any known alias."""
    return (params.get("drug_name") or params.get("drug") or params.get("name")
            or params.get("substance") or params.get("product")
            or params.get("query") or "").strip()


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def search_articles(params: dict) -> dict:
    """
    Two-phase search: esearch to get PMIDs, then efetch for full metadata.
    """
    query = _resolve_query(params)
    if not query:
        return {"error": "query parameter is required (also accepts: drug_name, drug, search_query)"}

    mesh_terms = params.get("mesh_terms", "").strip()
    date_range = params.get("date_range", "").strip()
    article_type = params.get("article_type", "").strip()
    limit = min(int(params.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)

    # Build query string
    full_query = query
    if mesh_terms:
        full_query += f" AND {mesh_terms}[MeSH Terms]"
    if article_type:
        full_query += f" AND {article_type}[Publication Type]"

    # Phase 1 — esearch
    esearch_url = (
        f"{BASE}/esearch.fcgi"
        f"?db=pubmed"
        f"&term={urllib.parse.quote(full_query)}"
        f"&retmax={limit}"
        f"&retmode=json"
        f"{COURTESY}"
    )
    if date_range:
        parts = date_range.split(":")
        if len(parts) == 2:
            esearch_url += f"&mindate={parts[0].strip()}&maxdate={parts[1].strip()}&datetype=pdat"

    esearch_data = _get_json(esearch_url)
    result_info = esearch_data.get("esearchresult", {})
    id_list = result_info.get("idlist", [])
    total = int(result_info.get("count", 0))

    if not id_list:
        return {
            "query": full_query,
            "total_found": total,
            "returned": 0,
            "articles": [],
        }

    # Phase 2 — efetch
    time.sleep(REQUEST_DELAY)
    ids_csv = ",".join(id_list)
    efetch_url = (
        f"{BASE}/efetch.fcgi"
        f"?db=pubmed"
        f"&id={ids_csv}"
        f"&retmode=xml"
        f"{COURTESY}"
    )
    root = _get_xml(efetch_url)
    articles = [_parse_article(el) for el in root.findall(".//PubmedArticle")]

    return {
        "query": full_query,
        "total_found": total,
        "returned": len(articles),
        "articles": articles,
    }


def get_abstract(params: dict) -> dict:
    """
    Fetch structured metadata and abstract for a single PMID.
    """
    pmid = str(params.get("pmid", "")).strip()
    if not pmid:
        return {"error": "pmid parameter is required"}

    efetch_url = (
        f"{BASE}/efetch.fcgi"
        f"?db=pubmed"
        f"&id={urllib.parse.quote(pmid)}"
        f"&retmode=xml"
        f"{COURTESY}"
    )
    root = _get_xml(efetch_url)
    article_el = root.find(".//PubmedArticle")
    if article_el is None:
        return {"error": f"PMID {pmid} not found", "pmid": pmid}

    result = _parse_article(article_el)

    # Include full MeSH headings for downstream microgram use
    mesh_headings = []
    for mh in root.findall(".//MeshHeading"):
        descriptor = _text(mh.find("DescriptorName"))
        if descriptor:
            mesh_headings.append(descriptor)
    result["mesh_headings"] = mesh_headings

    return result


def get_citations(params: dict) -> dict:
    """
    Use elink to find articles that cite the given PMID.
    Returns citing PMIDs plus brief metadata for each.
    """
    pmid = str(params.get("pmid", "")).strip()
    if not pmid:
        return {"error": "pmid parameter is required"}

    # Use XML mode — elink JSON from NCBI can contain control characters
    elink_url = (
        f"{BASE}/elink.fcgi"
        f"?dbfrom=pubmed"
        f"&db=pmc"
        f"&id={urllib.parse.quote(pmid)}"
        f"&linkname=pubmed_pmc_refs"
        f"{COURTESY}"
    )
    try:
        root = _get_xml(elink_url)
    except ET.ParseError:
        return {
            "pmid": pmid,
            "citing_count": 0,
            "citing_articles": [],
            "note": "Failed to parse elink XML response.",
        }

    # Extract linked PMC IDs, then resolve back to PMIDs
    citing_ids: list[str] = []
    for link_set in root.findall(".//LinkSetDb"):
        link_name = _text(link_set.find("LinkName"))
        if "refs" in link_name or "citedin" in link_name:
            for link in link_set.findall("Link"):
                link_id = _text(link.find("Id"))
                if link_id:
                    citing_ids.append(link_id)

    if not citing_ids:
        return {
            "pmid": pmid,
            "citing_count": 0,
            "citing_articles": [],
            "note": "No citing articles found via elink (citedin linkname). "
                    "elink citation data is limited to PubMed Central full-text.",
        }

    # Fetch metadata for up to DEFAULT_LIMIT citing articles
    fetch_ids = citing_ids[:DEFAULT_LIMIT]
    time.sleep(REQUEST_DELAY)
    ids_csv = ",".join(fetch_ids)
    efetch_url = (
        f"{BASE}/efetch.fcgi"
        f"?db=pubmed"
        f"&id={ids_csv}"
        f"&retmode=xml"
        f"{COURTESY}"
    )
    root = _get_xml(efetch_url)
    articles = [_parse_article(el) for el in root.findall(".//PubmedArticle")]

    return {
        "pmid": pmid,
        "citing_count": len(citing_ids),
        "returned": len(articles),
        "citing_articles": articles,
    }


def search_case_reports(params: dict) -> dict:
    """
    Search PubMed for adverse event case reports for a specific drug.
    Optional: narrow by adverse_event term.
    """
    drug_name = _resolve_drug(params)
    if not drug_name:
        return {"error": "drug_name parameter is required (also accepts: drug, name, substance, query)"}

    adverse_event = params.get("adverse_event", "").strip()

    # Build structured PubMed query — case report pub type is sufficient filter
    drug_clause = f"{drug_name}[Title/Abstract]"
    pub_type_clause = "Case Reports[Publication Type]"

    if adverse_event:
        query = (
            f"{drug_clause} AND {pub_type_clause} "
            f"AND ({adverse_event}[Title/Abstract])"
        )
    else:
        query = f"{drug_clause} AND {pub_type_clause}"

    return search_articles({"query": query, "limit": DEFAULT_LIMIT})


def search_signal_literature(params: dict) -> dict:
    """
    Find pharmacovigilance signal detection papers for a drug.
    Targets papers using standard PV methodology terms.
    """
    drug_name = _resolve_drug(params)
    if not drug_name:
        return {"error": "drug_name parameter is required (also accepts: drug, name, substance, query)"}

    pv_terms = (
        "pharmacovigilance[Title/Abstract] OR "
        "signal detection[Title/Abstract] OR "
        "disproportionality[Title/Abstract] OR "
        "PRR[Title/Abstract] OR "
        "ROR[Title/Abstract] OR "
        "reporting odds ratio[Title/Abstract] OR "
        "proportional reporting ratio[Title/Abstract] OR "
        "information component[Title/Abstract] OR "
        "EBGM[Title/Abstract] OR "
        "spontaneous report*[Title/Abstract]"
    )
    query = f"{drug_name}[Title/Abstract] AND ({pv_terms})"

    return search_articles({"query": query, "limit": DEFAULT_LIMIT})


def get_mesh_terms(params: dict) -> dict:
    """
    Extract MeSH (Medical Subject Headings) terms assigned to a PubMed article.
    Returns descriptor names with qualifier names and major topic flags.
    Useful for MedDRA concept mapping in PV signal detection workflows.
    """
    pmid = str(params.get("pmid", "")).strip()
    if not pmid:
        return {"error": "pmid parameter is required"}

    efetch_url = (
        f"{BASE}/efetch.fcgi"
        f"?db=pubmed"
        f"&id={urllib.parse.quote(pmid)}"
        f"&retmode=xml"
        f"{COURTESY}"
    )
    root = _get_xml(efetch_url)
    article_el = root.find(".//PubmedArticle")
    if article_el is None:
        return {"error": f"PMID {pmid} not found", "pmid": pmid}

    title = _text(article_el.find(".//ArticleTitle"))

    mesh_headings = []
    for mh in article_el.findall(".//MeshHeading"):
        descriptor_el = mh.find("DescriptorName")
        if descriptor_el is None:
            continue
        descriptor = _text(descriptor_el)
        major = descriptor_el.get("MajorTopicYN", "N") == "Y"

        qualifiers = []
        for qual in mh.findall("QualifierName"):
            qualifiers.append({
                "name": _text(qual),
                "major_topic": qual.get("MajorTopicYN", "N") == "Y",
            })

        mesh_headings.append({
            "descriptor": descriptor,
            "major_topic": major,
            "qualifiers": qualifiers,
        })

    # Also extract chemical/substance list
    chemicals = []
    for chem in article_el.findall(".//Chemical/NameOfSubstance"):
        chemicals.append(_text(chem))

    return {
        "pmid": pmid,
        "title": title,
        "mesh_heading_count": len(mesh_headings),
        "mesh_headings": mesh_headings,
        "chemicals": chemicals,
    }


def get_related_articles(params: dict) -> dict:
    """
    Find articles related to a given PMID using PubMed's elink similarity algorithm.
    Returns the top related articles with metadata.
    """
    pmid = str(params.get("pmid", "")).strip()
    if not pmid:
        return {"error": "pmid parameter is required"}

    limit = min(int(params.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)

    # elink with linkname=pubmed_pubmed to get related articles
    elink_url = (
        f"{BASE}/elink.fcgi"
        f"?dbfrom=pubmed"
        f"&db=pubmed"
        f"&id={urllib.parse.quote(pmid)}"
        f"&linkname=pubmed_pubmed"
        f"&retmode=xml"
        f"{COURTESY}"
    )
    try:
        root = _get_xml(elink_url)
    except ET.ParseError:
        return {
            "pmid": pmid,
            "related_count": 0,
            "related_articles": [],
            "note": "Failed to parse elink XML response.",
        }

    # Extract linked PMIDs
    related_ids: list[str] = []
    for link_set in root.findall(".//LinkSetDb"):
        for link in link_set.findall("Link"):
            link_id = _text(link.find("Id"))
            if link_id and link_id != pmid:
                related_ids.append(link_id)

    if not related_ids:
        return {
            "pmid": pmid,
            "related_count": 0,
            "related_articles": [],
        }

    # Fetch metadata for top related articles
    fetch_ids = related_ids[:limit]
    time.sleep(REQUEST_DELAY)
    ids_csv = ",".join(fetch_ids)
    efetch_url = (
        f"{BASE}/efetch.fcgi"
        f"?db=pubmed"
        f"&id={ids_csv}"
        f"&retmode=xml"
        f"{COURTESY}"
    )
    root = _get_xml(efetch_url)
    articles = [_parse_article(el) for el in root.findall(".//PubmedArticle")]

    return {
        "pmid": pmid,
        "related_count": len(related_ids),
        "returned": len(articles),
        "related_articles": articles,
    }


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

HANDLERS: dict[str, Any] = {
    "search-articles": search_articles,
    "get-abstract": get_abstract,
    "get-citations": get_citations,
    "search-case-reports": search_case_reports,
    "search-signal-literature": search_signal_literature,
    "get-mesh-terms": get_mesh_terms,
    "get-related-articles": get_related_articles,
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Read a JSON request from stdin and write a JSON response to stdout.

    Request schema:
      { "tool": "<tool-name>", "params": { ... } }

    Response schema (success):
      { "tool": "<tool-name>", "result": { ... } }

    Response schema (error):
      { "tool": "<tool-name>", "error": "<message>" }
    """
    raw = sys.stdin.read().strip()
    if not raw:
        json.dump({"error": "empty request"}, sys.stdout)
        sys.stdout.write("\n")
        return

    try:
        request = json.loads(raw)
    except json.JSONDecodeError as exc:
        json.dump({"error": f"invalid JSON: {exc}"}, sys.stdout)
        sys.stdout.write("\n")
        return

    tool_name = request.get("tool", "")
    params = request.get("arguments", request.get("args", request.get("params", {})))

    handler = HANDLERS.get(tool_name)
    if handler is None:
        json.dump(
            {
                "error": f"unknown tool: {tool_name!r}",
                "available_tools": list(HANDLERS.keys()),
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        return

    try:
        result = handler(params)
        if isinstance(result, dict) and "error" in result:
            result["status"] = "error"
        elif isinstance(result, dict) and "status" not in result:
            result["status"] = "ok"
        json.dump(result, sys.stdout, indent=2)
    except urllib.error.HTTPError as exc:
        json.dump(
            {"status": "error", "error": f"HTTP {exc.code}: {exc.reason}"},
            sys.stdout,
        )
    except urllib.error.URLError as exc:
        json.dump(
            {"status": "error", "error": f"Network error: {exc.reason}"},
            sys.stdout,
        )
    except ET.ParseError as exc:
        json.dump(
            {"status": "error", "error": f"XML parse error: {exc}"},
            sys.stdout,
        )
    except Exception as exc:  # noqa: BLE001
        json.dump(
            {"status": "error", "error": f"Unexpected error: {type(exc).__name__}: {exc}"},
            sys.stdout,
        )

    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
