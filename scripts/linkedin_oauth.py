#!/usr/bin/env python3
"""
LinkedIn OAuth 2.0 token generator for NexVigilant Station.

Usage:
    python3 linkedin_oauth.py

Opens your browser to LinkedIn's authorization page. After you approve,
LinkedIn redirects to localhost:8080/callback with an auth code.
This script exchanges the code for an access token and saves it.

Requires: LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET env vars,
or prompts interactively.
"""

import http.server
import json
import os
import sys
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

REDIRECT_URI = "http://localhost:8080/callback"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
SCOPES = "openid profile email w_member_social"
TOKEN_FILE = Path.home() / ".config" / "nexvigilant" / "linkedin.env"


def get_credentials() -> tuple[str, str]:
    """Get client ID and secret from env or interactive input."""
    client_id = os.environ.get("LINKEDIN_CLIENT_ID", "").strip()
    client_secret = os.environ.get("LINKEDIN_CLIENT_SECRET", "").strip()

    if not client_id:
        client_id = input("Client ID: ").strip()
    if not client_secret:
        client_secret = input("Client Secret: ").strip()

    return client_id, client_secret


def build_auth_url(client_id: str) -> str:
    """Build the LinkedIn authorization URL."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": "nexvigilant_station",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(code: str, client_id: str, client_secret: str) -> dict:
    """Exchange authorization code for access token."""
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")

    req = urllib.request.Request(
        TOKEN_URL,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def save_token(access_token: str) -> None:
    """Save token to ~/.config/nexvigilant/linkedin.env"""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(f"LINKEDIN_ACCESS_TOKEN={access_token}\n")
    TOKEN_FILE.chmod(0o600)
    print(f"\nToken saved to {TOKEN_FILE} (permissions: 600)")


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler that captures the OAuth callback."""

    auth_code: str | None = None

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            CallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
            <html><body style="font-family: system-ui; text-align: center; padding: 60px;">
            <h1>NexVigilant Station</h1>
            <p style="color: green; font-size: 1.2em;">Authorization successful! You can close this tab.</p>
            </body></html>
            """)
        elif "error" in params:
            error = params.get("error", ["unknown"])[0]
            desc = params.get("error_description", [""])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"""
            <html><body style="font-family: system-ui; text-align: center; padding: 60px;">
            <h1>Authorization Failed</h1>
            <p style="color: red;">{error}: {desc}</p>
            </body></html>
            """.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        """Suppress default HTTP logging."""
        pass


def main() -> None:
    print("=" * 50)
    print("NexVigilant Station — LinkedIn OAuth Setup")
    print("=" * 50)

    client_id, client_secret = get_credentials()

    auth_url = build_auth_url(client_id)
    print(f"\nOpening browser for authorization...")
    print(f"If browser doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    print("Waiting for callback on http://localhost:8080/callback ...")
    server = http.server.HTTPServer(("localhost", 8080), CallbackHandler)
    server.handle_request()  # Handle exactly one request

    if not CallbackHandler.auth_code:
        print("ERROR: No authorization code received.", file=sys.stderr)
        sys.exit(1)

    print("Authorization code received. Exchanging for access token...")
    token_resp = exchange_code(CallbackHandler.auth_code, client_id, client_secret)

    access_token = token_resp.get("access_token")
    expires_in = token_resp.get("expires_in", 0)

    if not access_token:
        print(f"ERROR: Token exchange failed: {token_resp}", file=sys.stderr)
        sys.exit(1)

    print(f"\nAccess token obtained!")
    print(f"  Expires in: {expires_in // 86400} days ({expires_in} seconds)")
    print(f"  Scopes: {token_resp.get('scope', SCOPES)}")

    save_token(access_token)

    # Quick verification
    print("\nVerifying token...")
    req = urllib.request.Request(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            profile = json.loads(resp.read().decode("utf-8"))
            print(f"  Authenticated as: {profile.get('name', 'unknown')}")
            print(f"  Email: {profile.get('email', 'not shared')}")
    except Exception as exc:
        print(f"  Warning: Verification failed: {exc}")

    print(f"\nDone! Token is live for {expires_in // 86400} days.")
    print("LinkedIn tools are now available via NexVigilant Station.")


if __name__ == "__main__":
    main()
