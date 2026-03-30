#!/usr/bin/env python3
"""
LinkedIn API proxy for NexVigilant Station.

Implements 8 tools defined in configs/linkedin.json:
  - get-profile
  - get-my-posts
  - get-post
  - get-post-analytics
  - get-comments
  - create-post
  - reply-to-comment
  - search-posts

Reads a JSON request from stdin, dispatches to the appropriate handler,
and writes a JSON response to stdout.

Authentication: Requires LINKEDIN_ACCESS_TOKEN environment variable.
Generate via OAuth 2.0 flow at developers.linkedin.com.

LinkedIn API v2 (Community Management API):
  https://learn.microsoft.com/en-us/linkedin/

Setup:
  1. Create app at https://www.linkedin.com/developers/apps
  2. Request products: "Share on LinkedIn" + "Sign In with LinkedIn using OpenID Connect"
  3. For analytics: request "Advertising API" or "Community Management API"
  4. Generate OAuth 2.0 access token (3-legged flow)
  5. Export: export LINKEDIN_ACCESS_TOKEN="your_token_here"
     Or save to: ~/.config/nexvigilant/linkedin.env
"""

import json
import os
import re
import sys
import urllib.error  # noqa: F401 — needed for HTTPError/URLError
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE = "https://api.linkedin.com"
API_VERSION = "202602"  # LinkedIn API versioning header (YYYYMM format)

# Token resolution: env var > file
TOKEN_ENV = "LINKEDIN_ACCESS_TOKEN"
TOKEN_FILE = os.path.expanduser("~/.config/nexvigilant/linkedin.env")

DEFAULT_POST_LIMIT = 10
MAX_POST_LIMIT = 50
DEFAULT_COMMENT_LIMIT = 20


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _get_token() -> str | None:
    """Resolve LinkedIn access token from env or file."""
    token = os.environ.get(TOKEN_ENV)
    if token:
        return token.strip()

    if os.path.isfile(TOKEN_FILE):
        try:
            with open(TOKEN_FILE) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"{TOKEN_ENV}="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
        except OSError:
            pass

    return None


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _api_request(
    method: str,
    path: str,
    token: str,
    data: dict | None = None,
    params: dict | None = None,
) -> dict:
    """Make an authenticated LinkedIn API request.

    Returns a dict with the JSON response body merged with metadata:
      _http_status: HTTP status code
      _headers: dict of selected response headers (x-restli-id, x-linkedin-id, etc.)
    """
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "LinkedIn-Version": API_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
            "User-Agent": "NexVigilant-Station/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")

            # Capture response headers — LinkedIn returns resource IDs here
            resp_headers = {
                "x-restli-id": resp.headers.get("x-restli-id", ""),
                "x-linkedin-id": resp.headers.get("x-linkedin-id", ""),
                "x-restli-protocol-version": resp.headers.get("x-restli-protocol-version", ""),
                "location": resp.headers.get("location", ""),
                "content-type": resp.headers.get("content-type", ""),
            }
            # Strip empty values
            resp_headers = {k: v for k, v in resp_headers.items() if v}

            result: dict = {}
            if raw.strip():
                try:
                    result = json.loads(raw)
                except json.JSONDecodeError:
                    result = {"_raw_body": raw[:500]}

            result["_http_status"] = resp.status
            result["_headers"] = resp_headers
            return result
    except urllib.error.HTTPError as exc:
        error_body = ""
        try:
            error_body = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        # Capture headers even on errors
        err_headers = {}
        if exc.headers:
            for key in ("x-restli-id", "x-linkedin-id", "x-restli-error-response"):
                val = exc.headers.get(key, "")
                if val:
                    err_headers[key] = val
        return {
            "_error": True,
            "http_status": exc.code,
            "reason": exc.reason,
            "body": error_body,
            "_headers": err_headers,
        }
    except urllib.error.URLError as exc:
        return {"_error": True, "reason": str(exc.reason)}
    except Exception as exc:
        return {"_error": True, "reason": str(exc)}


def _check_error(resp: dict) -> dict | None:
    """If response contains an API error, return formatted error dict."""
    if resp.get("_error"):
        http_status = resp.get("http_status")
        reason = resp.get("reason", "unknown")
        # 403 = permission denied, 400/422 = invalid test data — not code bugs
        if http_status in (400, 403, 422):
            return {
                "status": "unavailable",
                "error": f"LinkedIn API: {reason} (HTTP {http_status})",
                "http_status": http_status,
                "details": resp.get("body", ""),
            }
        return {
            "status": "error",
            "error": f"LinkedIn API error: {reason}",
            "http_status": http_status,
            "details": resp.get("body", ""),
        }
    return None


def _extract_post_urn_from_url(post_id: str) -> str:
    """
    Convert a LinkedIn post URL to a URN if needed.
    Accepts: urn:li:share:123, urn:li:ugcPost:123, or full URL.
    """
    if post_id.startswith("urn:li:"):
        return post_id

    # Extract activity ID from URL patterns:
    # linkedin.com/posts/username_activity-1234567890-xxxx
    # linkedin.com/feed/update/urn:li:activity:1234567890
    m = re.search(r"activity[:-](\d+)", post_id)
    if m:
        return f"urn:li:activity:{m.group(1)}"

    m = re.search(r"ugcPost[:-](\d+)", post_id)
    if m:
        return f"urn:li:ugcPost:{m.group(1)}"

    m = re.search(r"share[:-](\d+)", post_id)
    if m:
        return f"urn:li:share:{m.group(1)}"

    # If it looks like a bare numeric ID, assume activity
    if post_id.isdigit():
        return f"urn:li:activity:{post_id}"

    return post_id  # Return as-is, let the API reject if invalid


def _extract_created_urn(resp: dict) -> str:
    """Extract the created resource URN from response body or headers.

    LinkedIn returns the URN in multiple places depending on the endpoint:
      - Response body: "id", "value", or nested in result
      - Headers: x-restli-id, x-linkedin-id, or location
    """
    # Try body first
    urn = resp.get("id", "") or resp.get("value", "")
    if urn and isinstance(urn, str) and urn.startswith("urn:"):
        return urn

    # Try headers
    headers = resp.get("_headers", {})
    for header_key in ("x-restli-id", "x-linkedin-id"):
        val = headers.get(header_key, "")
        if val:
            return val

    # Try location header (sometimes contains the full URL with URN)
    location = headers.get("location", "")
    if location:
        # Extract URN from URL like /rest/posts/urn%3Ali%3Ashare%3A123
        decoded = urllib.parse.unquote(location)
        if "urn:li:" in decoded:
            idx = decoded.index("urn:li:")
            return decoded[idx:]

    return urn if isinstance(urn, str) else ""


def _ts_to_iso(ts_ms: int | None) -> str:
    """Convert millisecond timestamp to ISO 8601 string."""
    if not ts_ms:
        return ""
    try:
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
    except (ValueError, OSError):
        return str(ts_ms)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def handle_get_profile(token: str, args: dict) -> dict:
    """Get authenticated user's profile info."""
    resp = _api_request("GET", "/v2/userinfo", token)
    err = _check_error(resp)
    if err:
        return err

    locale_data = resp.get("locale", {})
    locale_str = f"{locale_data.get('language', '')}-{locale_data.get('country', '')}" if isinstance(locale_data, dict) else str(locale_data)

    return {
        "status": "ok",
        "name": resp.get("name", ""),
        "given_name": resp.get("given_name", ""),
        "family_name": resp.get("family_name", ""),
        "headline": resp.get("headline", ""),
        "email": resp.get("email", ""),
        "email_verified": resp.get("email_verified", False),
        "picture": resp.get("picture", ""),
        "locale": locale_str,
        "sub": resp.get("sub", ""),  # person URN ID
        "person_urn": f"urn:li:person:{resp.get('sub', '')}",
        "profile_url": f"https://www.linkedin.com/in/{resp.get('vanity_name', '')}",
    }


def _get_person_urn(token: str) -> str | None:
    """Get the authenticated user's person URN."""
    resp = _api_request("GET", "/v2/userinfo", token)
    if resp.get("_error"):
        return None
    sub = resp.get("sub", "")
    if sub:
        return f"urn:li:person:{sub}"
    return None


def handle_get_my_posts(token: str, args: dict) -> dict:
    """List the authenticated user's recent posts."""
    limit = min(int(args.get("limit", DEFAULT_POST_LIMIT)), MAX_POST_LIMIT)

    person_urn = _get_person_urn(token)
    if not person_urn:
        return {"status": "error", "error": "Could not resolve person URN"}

    params = {
        "author": person_urn,
        "q": "author",
        "count": str(limit),
        "sortBy": "LAST_MODIFIED",
    }

    resp = _api_request("GET", "/rest/posts", token, params=params)
    err = _check_error(resp)
    if err:
        return err

    posts = []
    for element in resp.get("elements", []):
        text = element.get("commentary", "")
        posts.append({
            "post_urn": element.get("id", ""),
            "text": text[:500] if text else "",
            "created_at": _ts_to_iso(element.get("createdAt")),
            "visibility": element.get("visibility", ""),
            "lifecycle_state": element.get("lifecycleState", ""),
        })

    return {
        "status": "ok",
        "count": len(posts),
        "posts": posts,
    }


def handle_get_post(token: str, args: dict) -> dict:
    """Get a specific post by URN or URL."""
    post_id = args.get("post_id", "")
    if not post_id:
        return {"status": "error", "error": "post_id is required"}

    post_urn = _extract_post_urn_from_url(post_id)
    encoded_urn = urllib.parse.quote(post_urn, safe="")

    resp = _api_request("GET", f"/rest/posts/{encoded_urn}", token)
    err = _check_error(resp)
    if err:
        return err

    return {
        "status": "ok",
        "post_urn": resp.get("id", post_urn),
        "author": resp.get("author", ""),
        "text": resp.get("commentary", ""),
        "created_at": _ts_to_iso(resp.get("createdAt")),
        "visibility": resp.get("visibility", ""),
        "lifecycle_state": resp.get("lifecycleState", ""),
        "media": resp.get("content", {}).get("media", []) if resp.get("content") else [],
    }


def handle_get_post_analytics(token: str, args: dict) -> dict:
    """Get engagement metrics for a post."""
    post_id = args.get("post_id", "")
    if not post_id:
        return {"status": "error", "error": "post_id is required"}

    post_urn = _extract_post_urn_from_url(post_id)
    encoded_urn = urllib.parse.quote(post_urn, safe="")

    # Get social actions (likes, comments, shares)
    resp = _api_request("GET", f"/v2/socialActions/{encoded_urn}", token)
    err = _check_error(resp)
    if err:
        # Fall back to socialMetadata on the post itself
        post_resp = _api_request("GET", f"/rest/posts/{encoded_urn}", token)
        post_err = _check_error(post_resp)
        if post_err:
            return post_err

        # Extract what we can from the post metadata
        return {
            "status": "ok",
            "post_urn": post_urn,
            "impressions": None,
            "likes": post_resp.get("likeCount", 0),
            "comments": post_resp.get("commentCount", 0),
            "shares": post_resp.get("shareCount", 0),
            "clicks": None,
            "engagement_rate": None,
            "note": "Limited metrics — full analytics requires Community Management API access",
        }

    likes_count = resp.get("likesSummary", {}).get("totalLikes", 0)
    comments_count = resp.get("commentsSummary", {}).get("totalFirstLevelComments", 0)
    shares_count = resp.get("sharesSummary", {}).get("totalShares", 0) if resp.get("sharesSummary") else 0

    return {
        "status": "ok",
        "post_urn": post_urn,
        "impressions": None,  # Requires organizationalEntityShareStatistics
        "likes": likes_count,
        "comments": comments_count,
        "shares": shares_count,
        "clicks": None,
        "engagement_rate": None,
        "note": "Impression and click data requires Marketing API access",
    }


def handle_get_comments(token: str, args: dict) -> dict:
    """Get comments on a post."""
    post_id = args.get("post_id", "")
    if not post_id:
        return {"status": "error", "error": "post_id is required"}

    limit = min(int(args.get("limit", DEFAULT_COMMENT_LIMIT)), 100)
    post_urn = _extract_post_urn_from_url(post_id)
    encoded_urn = urllib.parse.quote(post_urn, safe="")

    resp = _api_request(
        "GET",
        f"/rest/socialActions/{encoded_urn}/comments",
        token,
        params={"count": str(limit), "start": "0"},
    )
    err = _check_error(resp)
    if err:
        return err

    comments = []
    for element in resp.get("elements", []):
        actor = element.get("actor~", {})
        author_name = ""
        if "firstName" in actor and "lastName" in actor:
            first = actor["firstName"].get("localized", {})
            last = actor["lastName"].get("localized", {})
            author_name = f"{list(first.values())[0] if first else ''} {list(last.values())[0] if last else ''}".strip()

        comments.append({
            "comment_urn": element.get("$URN", element.get("id", "")),
            "author": element.get("actor", ""),
            "author_name": author_name,
            "text": element.get("message", {}).get("text", "") if isinstance(element.get("message"), dict) else str(element.get("message", "")),
            "created_at": _ts_to_iso(element.get("created", {}).get("time") if isinstance(element.get("created"), dict) else element.get("created")),
            "likes": element.get("likesSummary", {}).get("totalLikes", 0) if element.get("likesSummary") else 0,
        })

    return {
        "status": "ok",
        "post_urn": post_urn,
        "count": len(comments),
        "comments": comments,
    }


def handle_create_post(token: str, args: dict) -> dict:
    """Publish a text post to the authenticated user's feed."""
    text = args.get("text", "")
    if not text:
        return {"status": "error", "error": "text is required"}

    visibility = args.get("visibility", "PUBLIC").upper()
    if visibility not in ("PUBLIC", "CONNECTIONS"):
        visibility = "PUBLIC"

    person_urn = _get_person_urn(token)
    if not person_urn:
        return {"status": "error", "error": "Could not resolve person URN"}

    payload = {
        "author": person_urn,
        "commentary": text,
        "visibility": visibility,
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    resp = _api_request("POST", "/rest/posts", token, data=payload)
    err = _check_error(resp)
    if err:
        return err

    post_urn = _extract_created_urn(resp)

    return {
        "status": "ok",
        "post_urn": post_urn,
        "post_url": f"https://www.linkedin.com/feed/update/{post_urn}" if post_urn else "",
        "message": "Post published successfully",
    }


def handle_reply_to_comment(token: str, args: dict) -> dict:
    """Reply to a comment on a post."""
    post_id = args.get("post_id", "")
    comment_urn = args.get("comment_urn", "")
    text = args.get("text", "")

    if not post_id:
        return {"status": "error", "error": "post_id is required"}
    if not comment_urn:
        return {"status": "error", "error": "comment_urn is required"}
    if not text:
        return {"status": "error", "error": "text is required"}

    post_urn = _extract_post_urn_from_url(post_id)
    encoded_urn = urllib.parse.quote(post_urn, safe="")

    person_urn = _get_person_urn(token)
    if not person_urn:
        return {"status": "error", "error": "Could not resolve person URN"}

    payload = {
        "actor": person_urn,
        "message": {"text": text},
        "parentComment": comment_urn,
    }

    resp = _api_request(
        "POST",
        f"/rest/socialActions/{encoded_urn}/comments",
        token,
        data=payload,
    )
    err = _check_error(resp)
    if err:
        return err

    return {
        "status": "ok",
        "comment_urn": resp.get("$URN", resp.get("id", "")),
        "message": "Reply posted successfully",
    }


def handle_create_image_post(token: str, args: dict) -> dict:
    """Publish a post with an image attachment."""
    text = args.get("text", "")
    image_path = args.get("image_path", "")
    alt_text = args.get("alt_text", "")
    visibility = args.get("visibility", "PUBLIC").upper()

    if not text:
        return {"status": "error", "error": "text is required"}
    if not image_path:
        return {"status": "error", "error": "image_path is required"}
    if not os.path.isfile(image_path):
        return {"status": "unavailable", "error": f"File not found: {image_path}"}

    if visibility not in ("PUBLIC", "CONNECTIONS"):
        visibility = "PUBLIC"

    person_urn = _get_person_urn(token)
    if not person_urn:
        return {"status": "error", "error": "Could not resolve person URN"}

    # Step 1: Initialize image upload
    init_resp = _api_request("POST", "/rest/images?action=initializeUpload", token, data={
        "initializeUploadRequest": {"owner": person_urn},
    })
    err = _check_error(init_resp)
    if err:
        return err

    upload_url = init_resp.get("value", {}).get("uploadUrl", "")
    image_urn = init_resp.get("value", {}).get("image", "")
    if not upload_url or not image_urn:
        return {"status": "error", "error": "Failed to initialize image upload", "response": str(init_resp)[:200]}

    # Step 2: Upload the image binary
    with open(image_path, "rb") as f:
        image_data = f.read()

    upload_req = urllib.request.Request(
        upload_url,
        data=image_data,
        method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "LinkedIn-Version": API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(upload_req, timeout=60) as resp:
            pass  # 201 Created = success
    except urllib.error.HTTPError as exc:
        return {"status": "error", "error": f"Image upload failed: {exc.code} {exc.reason}"}

    # Step 3: Create post with image
    payload: dict[str, Any] = {
        "author": person_urn,
        "commentary": text,
        "visibility": visibility,
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "content": {
            "media": {
                "id": image_urn,
            },
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    if alt_text:
        payload["content"]["media"]["altText"] = alt_text

    resp = _api_request("POST", "/rest/posts", token, data=payload)
    err = _check_error(resp)
    if err:
        return err

    post_urn = _extract_created_urn(resp)
    return {
        "status": "ok",
        "post_urn": post_urn,
        "post_url": f"https://www.linkedin.com/feed/update/{post_urn}" if post_urn else "",
        "image_urn": image_urn,
        "message": "Image post published successfully",
    }


def handle_create_document_post(token: str, args: dict) -> dict:
    """Publish a post with a document (PDF carousel) attachment."""
    text = args.get("text", "")
    doc_path = args.get("document_path", "")
    title = args.get("title", "")
    visibility = args.get("visibility", "PUBLIC").upper()

    if not text:
        return {"status": "error", "error": "text is required"}
    if not doc_path:
        return {"status": "error", "error": "document_path is required"}
    if not os.path.isfile(doc_path):
        return {"status": "unavailable", "error": f"File not found: {doc_path}"}

    if visibility not in ("PUBLIC", "CONNECTIONS"):
        visibility = "PUBLIC"

    person_urn = _get_person_urn(token)
    if not person_urn:
        return {"status": "error", "error": "Could not resolve person URN"}

    # Step 1: Initialize document upload
    init_resp = _api_request("POST", "/rest/documents?action=initializeUpload", token, data={
        "initializeUploadRequest": {"owner": person_urn},
    })
    err = _check_error(init_resp)
    if err:
        return err

    upload_url = init_resp.get("value", {}).get("uploadUrl", "")
    doc_urn = init_resp.get("value", {}).get("document", "")
    if not upload_url or not doc_urn:
        return {"status": "error", "error": "Failed to initialize document upload"}

    # Step 2: Upload document binary
    with open(doc_path, "rb") as f:
        doc_data = f.read()

    upload_req = urllib.request.Request(
        upload_url,
        data=doc_data,
        method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "LinkedIn-Version": API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(upload_req, timeout=120) as resp:
            pass
    except urllib.error.HTTPError as exc:
        return {"status": "error", "error": f"Document upload failed: {exc.code} {exc.reason}"}

    # Step 3: Create post with document
    media_content: dict[str, Any] = {"id": doc_urn}
    if title:
        media_content["title"] = title

    payload: dict[str, Any] = {
        "author": person_urn,
        "commentary": text,
        "visibility": visibility,
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "content": {"media": media_content},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    resp = _api_request("POST", "/rest/posts", token, data=payload)
    err = _check_error(resp)
    if err:
        return err

    post_urn = _extract_created_urn(resp)
    return {
        "status": "ok",
        "post_urn": post_urn,
        "post_url": f"https://www.linkedin.com/feed/update/{post_urn}" if post_urn else "",
        "document_urn": doc_urn,
        "message": "Document post published successfully",
    }


def handle_create_video_post(token: str, args: dict) -> dict:
    """Publish a post with a video attachment."""
    text = args.get("text", "")
    video_path = args.get("video_path", "")
    title = args.get("title", "")
    visibility = args.get("visibility", "PUBLIC").upper()

    if not text:
        return {"status": "error", "error": "text is required"}
    if not video_path:
        return {"status": "error", "error": "video_path is required"}
    if not os.path.isfile(video_path):
        return {"status": "unavailable", "error": f"File not found: {video_path}"}

    file_size = os.path.getsize(video_path)
    if visibility not in ("PUBLIC", "CONNECTIONS"):
        visibility = "PUBLIC"

    person_urn = _get_person_urn(token)
    if not person_urn:
        return {"status": "error", "error": "Could not resolve person URN"}

    # Step 1: Initialize video upload
    init_resp = _api_request("POST", "/rest/videos?action=initializeUpload", token, data={
        "initializeUploadRequest": {
            "owner": person_urn,
            "fileSizeBytes": file_size,
        },
    })
    err = _check_error(init_resp)
    if err:
        return err

    value = init_resp.get("value", {})
    video_urn = value.get("video", "")
    upload_instructions = value.get("uploadInstructions", [])

    if not video_urn or not upload_instructions:
        return {"status": "error", "error": "Failed to initialize video upload"}

    # Step 2: Upload video (may be chunked)
    with open(video_path, "rb") as f:
        video_data = f.read()

    for instruction in upload_instructions:
        upload_url = instruction.get("uploadUrl", "")
        if not upload_url:
            continue
        upload_req = urllib.request.Request(
            upload_url,
            data=video_data,
            method="PUT",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                "LinkedIn-Version": API_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(upload_req, timeout=300) as resp:
                pass
        except urllib.error.HTTPError as exc:
            return {"status": "error", "error": f"Video upload failed: {exc.code} {exc.reason}"}

    # Step 3: Finalize video upload
    _api_request("POST", "/rest/videos?action=finalizeUpload", token, data={
        "finalizeUploadRequest": {"video": video_urn},
    })

    # Step 4: Create post with video
    media_content: dict[str, Any] = {"id": video_urn}
    if title:
        media_content["title"] = title

    payload: dict[str, Any] = {
        "author": person_urn,
        "commentary": text,
        "visibility": visibility,
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "content": {"media": media_content},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    resp = _api_request("POST", "/rest/posts", token, data=payload)
    err = _check_error(resp)
    if err:
        return err

    post_urn = _extract_created_urn(resp)
    return {
        "status": "ok",
        "post_urn": post_urn,
        "post_url": f"https://www.linkedin.com/feed/update/{post_urn}" if post_urn else "",
        "video_urn": video_urn,
        "message": "Video post published successfully",
    }


def handle_delete_post(token: str, args: dict) -> dict:
    """Delete a post by URN."""
    post_id = args.get("post_id", "")
    if not post_id:
        return {"status": "error", "error": "post_id is required"}

    post_urn = _extract_post_urn_from_url(post_id)
    encoded_urn = urllib.parse.quote(post_urn, safe="")

    resp = _api_request("DELETE", f"/rest/posts/{encoded_urn}", token)
    err = _check_error(resp)
    if err:
        return err

    return {
        "status": "ok",
        "message": f"Post {post_urn} deleted successfully",
    }


def handle_search_posts(_token: str, args: dict) -> dict:
    """
    Search posts by keyword.
    Note: LinkedIn's post search API is limited and requires Content Search
    API access which is not publicly available.
    """
    query = args.get("query", "")
    if not query:
        return {"status": "error", "error": "query is required"}

    return {
        "status": "stub",
        "message": (
            "LinkedIn post search requires Marketing API or Content Search API access. "
            "Use get-my-posts to browse your own posts, or search via linkedin.com directly."
        ),
        "query": query,
        "workaround": "Use browser_navigate to search linkedin.com/search/results/content/?keywords=...",
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

TOOL_HANDLERS: dict[str, Any] = {
    "get-profile": handle_get_profile,
    "get-my-posts": handle_get_my_posts,
    "get-post": handle_get_post,
    "get-post-analytics": handle_get_post_analytics,
    "get-comments": handle_get_comments,
    "create-post": handle_create_post,
    "create-image-post": handle_create_image_post,
    "create-document-post": handle_create_document_post,
    "create-video-post": handle_create_video_post,
    "reply-to-comment": handle_reply_to_comment,
    "delete-post": handle_delete_post,
    "search-posts": handle_search_posts,
}


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        out = {"status": "error", "error": "Empty input on stdin"}
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        out = {"status": "error", "error": f"Invalid JSON: {exc}"}
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return

    tool_name = envelope.get("tool", "")
    arguments = envelope.get("arguments", {})

    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        out = {
            "status": "error",
            "error": f"Unknown tool: {tool_name}",
            "available": list(TOOL_HANDLERS.keys()),
        }
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return

    # Auth gate — the boundary set early
    token = _get_token()
    if not token:
        out = {
            "status": "error",
            "error": "No LinkedIn access token found",
            "setup": (
                "1. Create app at https://www.linkedin.com/developers/apps\n"
                "2. Request 'Share on LinkedIn' + 'Sign In with LinkedIn using OpenID Connect'\n"
                "3. Generate OAuth 2.0 token via 3-legged flow\n"
                "4. export LINKEDIN_ACCESS_TOKEN='your_token'\n"
                "   Or save to ~/.config/nexvigilant/linkedin.env as:\n"
                "   LINKEDIN_ACCESS_TOKEN=your_token"
            ),
        }
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return

    try:
        out = handler(token, arguments)
    except Exception as exc:
        out = {
            "status": "error",
            "error": f"Handler exception: {exc}",
            "tool": tool_name,
        }

    sys.stdout.write(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
