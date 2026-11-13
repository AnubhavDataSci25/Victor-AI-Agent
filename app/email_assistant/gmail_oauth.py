"""
Victor Autonomous Email Assistant — Official Gmail OAuth 2.0 Manager.

Implements Authorization Code Flow with PKCE (S256) and CSRF state validation
using a local loopback callback server, automatic refresh, and clean revocation.
Requests only the minimum required scopes.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any, Optional
import urllib.parse
import webbrowser

import httpx

from app.email_assistant.crypto_store import EncryptedTokenStore

logger = logging.getLogger(__name__)

# Minimum necessary OAuth 2.0 scopes
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
]

_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_REVOKE_URI = "https://oauth2.googleapis.com/revoke"
_USERINFO_URI = "https://www.googleapis.com/oauth2/v2/userinfo"

_DEFAULT_CLIENT_JSON = (
    Path(__file__).resolve().parent.parent.parent / "config" / "gmail_oauth_client.json"
)


class GmailOAuthManager:
    """Manages OAuth 2.0 authorization, encrypted token persistence, refresh, and revocation."""

    def __init__(
        self,
        token_store: EncryptedTokenStore | None = None,
        client_json_path: Path | None = None,
    ) -> None:
        self.token_store = token_store or EncryptedTokenStore()
        self.client_json_path = client_json_path or _DEFAULT_CLIENT_JSON
        self._refresh_lock = asyncio.Lock()

    def _load_client_config(self) -> tuple[str, str]:
        """Load OAuth Client ID and Secret from env vars or config/gmail_oauth_client.json."""
        cid = (os.getenv("GMAIL_CLIENT_ID") or "").strip()
        csec = (os.getenv("GMAIL_CLIENT_SECRET") or "").strip()
        if cid and csec:
            return cid, csec

        if self.client_json_path.exists():
            try:
                raw = json.loads(self.client_json_path.read_text(encoding="utf-8"))
                block = raw.get("installed") or raw.get("web") or raw
                cid = (block.get("client_id") or "").strip()
                csec = (block.get("client_secret") or "").strip()
                if cid and csec:
                    return cid, csec
            except Exception as e:
                logger.warning(f"[GmailOAuth] Failed reading client config file: {type(e).__name__}")

        raise RuntimeError(
            "Gmail OAuth 2.0 client credentials are not configured. "
            "Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env or place your Google Desktop OAuth JSON at "
            f"{self.client_json_path}."
        )

    def has_client_config(self) -> bool:
        try:
            self._load_client_config()
            return True
        except RuntimeError:
            return False

    async def get_valid_access_token(self) -> str:
        """Return a valid OAuth access token, refreshing automatically if expired."""
        async with self._refresh_lock:
            token_data = self.token_store.load()
            if not token_data or not token_data.get("access_token"):
                raise RuntimeError("Gmail is not connected. Please authorize Gmail using gmail_connect.")

            expires_at = float(token_data.get("expires_at", 0))
            if time.time() < (expires_at - 60):
                return token_data["access_token"]

            refresh_token = token_data.get("refresh_token")
            if not refresh_token:
                raise RuntimeError("Gmail refresh token missing. Please re-authorize Gmail using gmail_connect.")

            client_id, client_secret = self._load_client_config()
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    _TOKEN_URI,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
            if resp.status_code != 200:
                logger.warning(f"[GmailOAuth] Token refresh failed with status {resp.status_code}")
                raise RuntimeError("Gmail session expired and could not be refreshed. Please reconnect Gmail.")

            refreshed = resp.json()
            token_data["access_token"] = refreshed["access_token"]
            token_data["expires_at"] = time.time() + float(refreshed.get("expires_in", 3600))
            if refreshed.get("refresh_token"):
                token_data["refresh_token"] = refreshed["refresh_token"]
            self.token_store.save(token_data)
            return token_data["access_token"]

    async def get_status(self) -> dict[str, Any]:
        """Return connection status, authorized account email, and granted scopes."""
        token_data = self.token_store.load()
        if not token_data or not token_data.get("access_token"):
            return {
                "connected": False,
                "account_email": None,
                "scopes": GMAIL_SCOPES,
                "client_configured": self.has_client_config(),
            }

        account_email = token_data.get("account_email")
        if not account_email:
            try:
                access_token = await self.get_valid_access_token()
                account_email = await self._fetch_account_email(access_token)
                if account_email:
                    token_data = self.token_store.load() or token_data
                    token_data["account_email"] = account_email
                    self.token_store.save(token_data)
            except Exception:
                pass

        return {
            "connected": True,
            "account_email": account_email or "Connected Gmail Account",
            "scopes": token_data.get("scope", " ".join(GMAIL_SCOPES)).split(),
            "client_configured": self.has_client_config(),
        }

    async def _fetch_account_email(self, access_token: str) -> Optional[str]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _USERINFO_URI,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code == 200:
                return resp.json().get("email")
        return None

    async def authorize_interactive(self, timeout_seconds: float = 180.0, open_browser: bool = True) -> dict[str, Any]:
        """
        Launch local loopback OAuth 2.0 + PKCE flow in the user's browser.
        Waits for user consent and exchanges the authorization code for tokens.
        """
        client_id, client_secret = self._load_client_config()

        code_verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        expected_state = secrets.token_urlsafe(24)

        result_holder: dict[str, Optional[str]] = {"code": None, "error": None, "state": None}
        done_event = threading.Event()

        class _CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/favicon.ico":
                    self.send_response(204)
                    self.end_headers()
                    return

                if parsed.path not in ("/oauth2callback", "/"):
                    self.send_response(404)
                    self.end_headers()
                    return

                params = urllib.parse.parse_qs(parsed.query)
                result_holder["code"] = (params.get("code") or [None])[0]
                result_holder["error"] = (params.get("error") or [None])[0]
                result_holder["state"] = (params.get("state") or [None])[0]

                ok = bool(result_holder["code"]) and result_holder["state"] == expected_state
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Connection", "close")

                body = (
                    "<!DOCTYPE html><html><head><title>Victor - Gmail Authorization</title>"
                    "<meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
                    "<style>"
                    "body{font-family:system-ui,-apple-system,sans-serif;background:#020817;color:#F1F6FF;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}"
                    ".card{background:rgba(7,20,38,0.95);border:1px solid #00D9FF;border-radius:14px;padding:36px;text-align:center;max-width:440px;box-shadow:0 0 35px rgba(0,217,255,0.25);}"
                    "h2{color:#00D9FF;margin-top:0;font-size:22px;}p{color:#91A7C4;line-height:1.6;font-size:15px;}"
                    "</style></head><body><div class='card'>"
                    + (
                        "<h2>✓ Gmail Connected Successfully</h2><p>Victor is now authorized to assist with your emails.<br><br>You can safely close this browser window and return to Victor.</p>"
                        if ok
                        else f"<h2>✗ Authorization Failed</h2><p>{html.escape(str(result_holder['error'] or 'State verification mismatch'))}</p>"
                    )
                    + "</div></body></html>"
                ).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                try:
                    self.wfile.flush()
                except Exception:
                    pass
                done_event.set()

            def log_message(self, format, *args):
                return  # Suppress HTTP server logs to prevent leaking query params

        server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
        port = server.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}/oauth2callback"

        auth_params = urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(GMAIL_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": expected_state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        })
        auth_url = f"{_AUTH_URI}?{auth_params}"
        logger.info(f"[GmailOAuth] OAuth listener running on http://127.0.0.1:{port}/oauth2callback (timeout: {timeout_seconds}s)")

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            if open_browser:
                logger.info("[GmailOAuth] Launching default browser for Google OAuth 2.0 consent...")
                webbrowser.open(auth_url)

            completed = await asyncio.to_thread(done_event.wait, timeout_seconds)
            if not completed:
                raise RuntimeError("Gmail authorization timed out waiting for browser consent (timeout reached).")
            if result_holder["error"]:
                raise RuntimeError(f"Gmail authorization declined: {result_holder['error']}")
            if result_holder["state"] != expected_state or not result_holder["code"]:
                raise RuntimeError("Gmail authorization failed CSRF state validation.")

            async with httpx.AsyncClient(timeout=25.0) as client:
                token_resp = await client.post(
                    _TOKEN_URI,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code": result_holder["code"],
                        "code_verifier": code_verifier,
                        "redirect_uri": redirect_uri,
                        "grant_type": "authorization_code",
                    },
                )
            if token_resp.status_code != 200:
                raise RuntimeError(f"OAuth token exchange failed (HTTP {token_resp.status_code}).")

            token_json = token_resp.json()
            token_data = {
                "access_token": token_json["access_token"],
                "refresh_token": token_json.get("refresh_token"),
                "expires_at": time.time() + float(token_json.get("expires_in", 3600)),
                "scope": token_json.get("scope", " ".join(GMAIL_SCOPES)),
                "token_type": token_json.get("token_type", "Bearer"),
            }
            account_email = await self._fetch_account_email(token_data["access_token"])
            if account_email:
                token_data["account_email"] = account_email
            self.token_store.save(token_data)
            logger.info("[GmailOAuth] Gmail account authorized and token encrypted locally.")
            return {
                "success": True,
                "connected": True,
                "account_email": account_email or "Connected Gmail Account",
                "scopes": token_data["scope"].split(),
            }
        finally:
            await asyncio.sleep(0.5)
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass

    async def disconnect(self) -> dict[str, Any]:
        """Revoke token with Google OAuth and wipe encrypted local credentials."""
        token_data = self.token_store.load()
        revoked_remote = False
        if token_data:
            tok = token_data.get("refresh_token") or token_data.get("access_token")
            if tok:
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.post(_REVOKE_URI, params={"token": tok})
                        revoked_remote = resp.status_code == 200
                except Exception:
                    pass
        cleared = self.token_store.clear()
        return {
            "success": True,
            "connected": False,
            "revoked_remote": revoked_remote,
            "local_cleared": cleared,
        }


if __name__ == "__main__":
    import sys

    async def _cli():
        mgr = GmailOAuthManager()
        st = await mgr.get_status()
        if len(sys.argv) > 1 and sys.argv[1] == "disconnect":
            res = await mgr.disconnect()
            print("Disconnected:", res)
        elif len(sys.argv) > 1 and sys.argv[1] == "status":
            print("Status:", st)
        else:
            print(f"Current status: {st}")
            print("Starting interactive authorization...")
            res = await mgr.authorize_interactive()
            print(f"[SUCCESS] Authorized as: {res.get('account_email')}")

    asyncio.run(_cli())

