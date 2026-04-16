#!/usr/bin/env python3
"""
Claude.ai API proxy for NexVigilant Station.

Implements 11 tools defined in configs/claude-ai.json:
  - list-organizations
  - list-projects
  - get-project
  - create-project
  - update-project
  - list-conversations
  - get-conversation
  - search-conversations
  - send-message
  - delete-conversation
  - list-project-files

Reads a JSON request from stdin, dispatches to the appropriate handler,
and writes a JSON response to stdout.

Authentication: Requires CLAUDE_AI_SESSION_KEY environment variable.
This is the sessionKey cookie from your logged-in claude.ai browser session.

To extract your session key:
  1. Log in to claude.ai in your browser
  2. Open DevTools > Application > Cookies > claude.ai
  3. Copy the value of the "sessionKey" cookie
  4. Export: export CLAUDE_AI_SESSION_KEY="sk-ant-sid01-..."
     Or save to: ~/.config/nexvigilant/claude-ai.env

Organization ID is auto-discovered on first call and cached.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE = "https://claude.ai/api"
TOKEN_ENV = "CLAUDE_AI_SESSION_KEY"
TOKEN_FILE = os.path.expanduser("~/.config/nexvigilant/claude-ai.env")
ORG_ENV = "CLAUDE_AI_ORG_ID"

DEFAULT_CONVERSATION_LIMIT = 20
MAX_CONVERSATION_LIMIT = 100
DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 50
DEFAULT_MODEL = "claude-sonnet-4-20250514"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _get_session_key() -> str | None:
    """Resolve claude.ai session key from env or file."""
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


def _get_default_org(session_key: str) -> str | None:
    """Get default organization ID from env or by querying the API."""
    org_id = os.environ.get(ORG_ENV)
    if org_id:
        return org_id.strip()

    # Query organizations endpoint
    resp = _api_request("GET", "/organizations", session_key)
    if resp.get("_error"):
        return None

    # Response is a list of orgs
    orgs = resp if isinstance(resp, list) else resp.get("data", [])
    if not orgs:
        return None

    # Return the first org's UUID
    if isinstance(orgs, list) and len(orgs) > 0:
        return orgs[0].get("uuid")

    return None


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _api_request(
    method: str,
    path: str,
    session_key: str,
    data: dict | None = None,
    params: dict | None = None,
) -> Any:
    """Make an authenticated claude.ai API request."""
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
            "Cookie": f"sessionKey={session_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "NexVigilant-Station/1.0",
            "Anthropic-Client-Sha": "unknown",
            "Anthropic-Client-Version": "unknown",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            if raw.strip():
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return {"_raw_body": raw[:2000]}
            return {}
    except urllib.error.HTTPError as exc:
        error_body = ""
        try:
            error_body = exc.read().decode("utf-8", errors="replace")[:1000]
        except Exception:
            pass
        return {
            "_error": True,
            "http_status": exc.code,
            "reason": exc.reason,
            "body": error_body,
        }
    except urllib.error.URLError as exc:
        return {"_error": True, "reason": str(exc.reason)}
    except Exception as exc:
        return {"_error": True, "reason": str(exc)}


def _check_error(resp: Any) -> dict | None:
    """If response contains an API error, return formatted error dict."""
    if isinstance(resp, dict) and resp.get("_error"):
        http_status = resp.get("http_status")
        reason = resp.get("reason", "unknown")
        if http_status == 401:
            return {
                "status": "error",
                "error": "Session key expired or invalid. Re-extract from browser cookies.",
                "http_status": 401,
            }
        if http_status == 403:
            return {
                "status": "error",
                "error": f"Forbidden: {reason}",
                "http_status": 403,
                "details": resp.get("body", ""),
            }
        return {
            "status": "error",
            "error": f"Claude.ai API error: {reason}",
            "http_status": http_status,
            "details": resp.get("body", ""),
        }
    return None


def _resolve_org(session_key: str, args: dict) -> tuple[str | None, dict | None]:
    """Resolve org_id from args or auto-discover. Returns (org_id, error_dict)."""
    org_id = args.get("org_id")
    if org_id:
        return org_id, None

    org_id = _get_default_org(session_key)
    if not org_id:
        return None, {
            "status": "error",
            "error": "Could not determine organization ID. Pass org_id explicitly or set CLAUDE_AI_ORG_ID.",
        }
    return org_id, None


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def handle_list_organizations(session_key: str, args: dict) -> dict:
    resp = _api_request("GET", "/organizations", session_key)
    err = _check_error(resp)
    if err:
        return err

    orgs = resp if isinstance(resp, list) else []
    return {
        "status": "ok",
        "organizations": [
            {
                "uuid": o.get("uuid", ""),
                "name": o.get("name", ""),
                "join_token": o.get("join_token", ""),
            }
            for o in orgs
        ],
    }


def handle_list_projects(session_key: str, args: dict) -> dict:
    org_id, err = _resolve_org(session_key, args)
    if err:
        return err

    resp = _api_request("GET", f"/organizations/{org_id}/projects", session_key)
    err = _check_error(resp)
    if err:
        return err

    projects = resp if isinstance(resp, list) else resp.get("data", [])
    return {
        "status": "ok",
        "count": len(projects),
        "projects": [
            {
                "uuid": p.get("uuid", ""),
                "name": p.get("name", ""),
                "description": p.get("description", ""),
                "created_at": p.get("created_at", ""),
                "updated_at": p.get("updated_at", ""),
                "is_default": p.get("is_default", False),
            }
            for p in projects
        ],
    }


def handle_get_project(session_key: str, args: dict) -> dict:
    project_id = args.get("project_id")
    if not project_id:
        return {"status": "error", "error": "project_id is required"}

    org_id, err = _resolve_org(session_key, args)
    if err:
        return err

    resp = _api_request("GET", f"/organizations/{org_id}/projects/{project_id}", session_key)
    err = _check_error(resp)
    if err:
        return err

    return {
        "status": "ok",
        "uuid": resp.get("uuid", ""),
        "name": resp.get("name", ""),
        "description": resp.get("description", ""),
        "prompt_template": resp.get("prompt_template", ""),
        "created_at": resp.get("created_at", ""),
        "updated_at": resp.get("updated_at", ""),
    }


def handle_create_project(session_key: str, args: dict) -> dict:
    name = args.get("name")
    if not name:
        return {"status": "error", "error": "name is required"}

    org_id, err = _resolve_org(session_key, args)
    if err:
        return err

    payload: dict[str, Any] = {"name": name}
    if args.get("description"):
        payload["description"] = args["description"]
    if args.get("instructions"):
        payload["prompt_template"] = args["instructions"]

    resp = _api_request("POST", f"/organizations/{org_id}/projects", session_key, data=payload)
    err = _check_error(resp)
    if err:
        return err

    uuid = resp.get("uuid", "")
    return {
        "status": "ok",
        "uuid": uuid,
        "name": resp.get("name", name),
        "url": f"https://claude.ai/project/{uuid}" if uuid else "",
    }


def handle_update_project(session_key: str, args: dict) -> dict:
    project_id = args.get("project_id")
    if not project_id:
        return {"status": "error", "error": "project_id is required"}

    org_id, err = _resolve_org(session_key, args)
    if err:
        return err

    payload: dict[str, Any] = {}
    if args.get("name"):
        payload["name"] = args["name"]
    if args.get("description"):
        payload["description"] = args["description"]
    if args.get("instructions"):
        payload["prompt_template"] = args["instructions"]

    if not payload:
        return {"status": "error", "error": "At least one of name, description, or instructions required"}

    resp = _api_request("PUT", f"/organizations/{org_id}/projects/{project_id}", session_key, data=payload)
    err = _check_error(resp)
    if err:
        return err

    return {
        "status": "ok",
        "uuid": resp.get("uuid", project_id),
        "name": resp.get("name", ""),
    }


def handle_list_conversations(session_key: str, args: dict) -> dict:
    org_id, err = _resolve_org(session_key, args)
    if err:
        return err

    limit = min(args.get("limit", DEFAULT_CONVERSATION_LIMIT), MAX_CONVERSATION_LIMIT)

    path = f"/organizations/{org_id}/chat_conversations"
    params: dict[str, Any] = {"limit": limit}

    project_id = args.get("project_id")
    if project_id:
        params["project_uuid"] = project_id

    resp = _api_request("GET", path, session_key, params=params)
    err = _check_error(resp)
    if err:
        return err

    convos = resp if isinstance(resp, list) else resp.get("data", [])
    return {
        "status": "ok",
        "count": len(convos),
        "conversations": [
            {
                "uuid": c.get("uuid", ""),
                "name": c.get("name", ""),
                "created_at": c.get("created_at", ""),
                "updated_at": c.get("updated_at", ""),
                "project_uuid": c.get("project_uuid", ""),
                "model": c.get("model", ""),
            }
            for c in convos[:limit]
        ],
    }


def handle_get_conversation(session_key: str, args: dict) -> dict:
    conversation_id = args.get("conversation_id")
    if not conversation_id:
        return {"status": "error", "error": "conversation_id is required"}

    org_id, err = _resolve_org(session_key, args)
    if err:
        return err

    resp = _api_request(
        "GET",
        f"/organizations/{org_id}/chat_conversations/{conversation_id}",
        session_key,
    )
    err = _check_error(resp)
    if err:
        return err

    # Extract messages from the response
    chat_messages = resp.get("chat_messages", [])
    messages = []
    for m in chat_messages:
        text = m.get("text", "")
        # Some messages have content blocks instead of flat text
        if not text and m.get("content"):
            parts = []
            for block in m["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            text = "\n".join(parts)

        messages.append({
            "uuid": m.get("uuid", ""),
            "sender": m.get("sender", ""),
            "text": text[:5000],  # Truncate very long messages
            "created_at": m.get("created_at", ""),
        })

    return {
        "status": "ok",
        "uuid": resp.get("uuid", conversation_id),
        "name": resp.get("name", ""),
        "model": resp.get("model", ""),
        "created_at": resp.get("created_at", ""),
        "message_count": len(messages),
        "messages": messages,
    }


def handle_search_conversations(session_key: str, args: dict) -> dict:
    query = args.get("query")
    if not query:
        return {"status": "error", "error": "query is required"}

    org_id, err = _resolve_org(session_key, args)
    if err:
        return err

    limit = min(args.get("limit", DEFAULT_SEARCH_LIMIT), MAX_SEARCH_LIMIT)

    resp = _api_request(
        "GET",
        f"/organizations/{org_id}/chat_conversations/search",
        session_key,
        params={"q": query, "limit": limit},
    )
    err = _check_error(resp)
    if err:
        return err

    results = resp if isinstance(resp, list) else resp.get("data", [])
    return {
        "status": "ok",
        "query": query,
        "count": len(results),
        "results": [
            {
                "conversation_uuid": r.get("uuid", r.get("conversation_uuid", "")),
                "conversation_name": r.get("name", r.get("conversation_name", "")),
                "matched_message": r.get("matched_message", r.get("snippet", ""))[:500],
                "sender": r.get("sender", ""),
                "created_at": r.get("created_at", ""),
            }
            for r in results[:limit]
        ],
    }


def handle_send_message(session_key: str, args: dict) -> dict:
    message = args.get("message")
    if not message:
        return {"status": "error", "error": "message is required"}

    org_id, err = _resolve_org(session_key, args)
    if err:
        return err

    conversation_id = args.get("conversation_id")
    model = args.get("model", DEFAULT_MODEL)

    # If no conversation_id, create a new conversation first
    if not conversation_id:
        create_payload: dict[str, Any] = {"name": "", "model": model}
        project_id = args.get("project_id")
        if project_id:
            create_payload["project_uuid"] = project_id

        create_resp = _api_request(
            "POST",
            f"/organizations/{org_id}/chat_conversations",
            session_key,
            data=create_payload,
        )
        err = _check_error(create_resp)
        if err:
            return err

        conversation_id = create_resp.get("uuid", "")
        if not conversation_id:
            return {"status": "error", "error": "Failed to create conversation"}

    # Send the message via the completion endpoint
    # claude.ai uses a streaming SSE endpoint for chat
    payload = {
        "completion": {
            "prompt": message,
            "model": model,
        },
        "organization_uuid": org_id,
        "conversation_uuid": conversation_id,
        "text": message,
        "attachments": [],
    }

    resp = _api_request(
        "POST",
        f"/organizations/{org_id}/chat_conversations/{conversation_id}/completion",
        session_key,
        data=payload,
    )
    err = _check_error(resp)
    if err:
        # The completion endpoint might use SSE streaming — try to extract what we got
        if isinstance(resp, dict) and resp.get("body"):
            # Parse SSE events from the body
            body = resp["body"]
            response_text = _extract_sse_response(body)
            if response_text:
                return {
                    "status": "ok",
                    "conversation_id": conversation_id,
                    "response_text": response_text,
                    "model": model,
                    "url": f"https://claude.ai/chat/{conversation_id}",
                }
        return err

    # Handle direct JSON response
    response_text = ""
    if isinstance(resp, dict):
        response_text = resp.get("completion", resp.get("text", ""))
        if not response_text and resp.get("content"):
            parts = []
            for block in resp["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            response_text = "\n".join(parts)

    return {
        "status": "ok",
        "conversation_id": conversation_id,
        "response_text": response_text[:10000],
        "model": model,
        "url": f"https://claude.ai/chat/{conversation_id}",
    }


def _extract_sse_response(body: str) -> str:
    """Extract assistant response text from SSE event stream."""
    parts = []
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            data_str = line[6:]
            if data_str == "[DONE]":
                continue
            try:
                data = json.loads(data_str)
                if data.get("type") == "completion":
                    parts.append(data.get("completion", ""))
                elif data.get("type") == "content_block_delta":
                    delta = data.get("delta", {})
                    parts.append(delta.get("text", ""))
            except json.JSONDecodeError:
                continue
    return "".join(parts)


def handle_delete_conversation(session_key: str, args: dict) -> dict:
    conversation_id = args.get("conversation_id")
    if not conversation_id:
        return {"status": "error", "error": "conversation_id is required"}

    org_id, err = _resolve_org(session_key, args)
    if err:
        return err

    resp = _api_request(
        "DELETE",
        f"/organizations/{org_id}/chat_conversations/{conversation_id}",
        session_key,
    )
    err = _check_error(resp)
    if err:
        return err

    return {
        "status": "deleted",
        "conversation_id": conversation_id,
    }


def handle_list_project_files(session_key: str, args: dict) -> dict:
    project_id = args.get("project_id")
    if not project_id:
        return {"status": "error", "error": "project_id is required"}

    org_id, err = _resolve_org(session_key, args)
    if err:
        return err

    resp = _api_request(
        "GET",
        f"/organizations/{org_id}/projects/{project_id}/docs",
        session_key,
    )
    err = _check_error(resp)
    if err:
        return err

    files = resp if isinstance(resp, list) else resp.get("data", [])
    return {
        "status": "ok",
        "project_id": project_id,
        "count": len(files),
        "files": [
            {
                "uuid": f.get("uuid", ""),
                "file_name": f.get("file_name", f.get("filename", "")),
                "file_type": f.get("content_type", f.get("file_type", "")),
                "file_size": f.get("file_size", 0),
                "created_at": f.get("created_at", ""),
            }
            for f in files
        ],
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

HANDLERS = {
    "list-organizations": handle_list_organizations,
    "list-projects": handle_list_projects,
    "get-project": handle_get_project,
    "create-project": handle_create_project,
    "update-project": handle_update_project,
    "list-conversations": handle_list_conversations,
    "get-conversation": handle_get_conversation,
    "search-conversations": handle_search_conversations,
    "send-message": handle_send_message,
    "delete-conversation": handle_delete_conversation,
    "list-project-files": handle_list_project_files,
}


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        json.dump({"status": "error", "error": "Empty input"}, sys.stdout)
        return

    try:
        request = json.loads(raw)
    except json.JSONDecodeError:
        json.dump({"status": "error", "error": "Invalid JSON input"}, sys.stdout)
        return

    tool = request.get("tool", "")
    arguments = request.get("arguments", {})

    # Strip domain prefix if present (dispatch.py sends full tool name)
    tool_name = tool
    prefix = "claude_ai_"
    if tool_name.startswith(prefix):
        tool_name = tool_name[len(prefix):]
    # Convert underscores back to hyphens for handler lookup
    tool_name = tool_name.replace("_", "-")

    session_key = _get_session_key()
    if not session_key:
        json.dump({
            "status": "error",
            "error": (
                "No claude.ai session key found. "
                f"Set {TOKEN_ENV} env var or save to {TOKEN_FILE}. "
                "Extract from browser: DevTools > Application > Cookies > sessionKey"
            ),
        }, sys.stdout)
        return

    handler = HANDLERS.get(tool_name)
    if not handler:
        json.dump({
            "status": "error",
            "error": f"Unknown tool: {tool_name}",
            "available": list(HANDLERS.keys()),
        }, sys.stdout)
        return

    result = handler(session_key, arguments)
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
