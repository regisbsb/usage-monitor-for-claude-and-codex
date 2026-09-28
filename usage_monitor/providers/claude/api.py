"""Claude OAuth API boundary.

This module is the only part of the Claude provider that reads credentials or
makes network requests.  Requests are sent directly to ``api.anthropic.com``;
redirects are deliberately disabled so an Authorization header cannot leave
that origin.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import requests
import truststore

from ...i18n import T

API_URL_USAGE = "https://api.anthropic.com/api/oauth/usage"
API_URL_PROFILE = "https://api.anthropic.com/api/oauth/profile"
_FALLBACK_USER_AGENT = "claude-code/2.1.204"
_UNSET = object()

# Claude is the only built-in HTTPS client; use roots trusted by Windows.
truststore.inject_into_ssl()

__all__ = [
    "API_URL_PROFILE",
    "API_URL_USAGE",
    "ClaudeAPI",
    "merge_scoped_limits",
]


class ClaudeAPI:
    """Read one Claude config directory and call the Anthropic OAuth API."""

    def __init__(self, config_dir: Path, cli: Any) -> None:
        self.config_dir = Path(config_dir)
        self.credentials_path = self.config_dir / ".credentials.json"
        self._cli = cli

    def read_access_token(self) -> str | None:
        """Return the current access token, tolerating atomic file rewrites."""
        try:
            payload = json.loads(self.credentials_path.read_text(encoding="utf-8-sig"))
            oauth = payload.get("claudeAiOauth") if isinstance(payload, dict) else None
            token = oauth.get("accessToken") if isinstance(oauth, dict) else None
            return token if isinstance(token, str) and token else None
        except (OSError, UnicodeError, ValueError):
            return None

    def auth_revision(self) -> str | None:
        """Return a non-secret marker that changes when the token changes."""
        token = self.read_access_token()
        if token is None:
            return None
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def api_headers(self, token: str | None | object = _UNSET) -> dict[str, str] | None:
        """Build API headers for *token*, or for the current token if omitted."""
        if token is _UNSET:
            token = self.read_access_token()
        if not isinstance(token, str) or not token:
            return None
        version = self._cli.native_version()
        user_agent = f"claude-code/{version}" if version else _FALLBACK_USER_AGENT
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": user_agent,
            "anthropic-beta": "oauth-2025-04-20",
        }

    def fetch_usage(self, token: str | None | object = _UNSET) -> dict[str, Any]:
        """Fetch normalized quota data with a caller-pinned token."""
        headers = self.api_headers(token)
        if headers is None:
            return {"error": T['no_token']}

        try:
            response = self._get(API_URL_USAGE, headers)
            return merge_scoped_limits(response.json())
        except requests.exceptions.SSLError:
            return {"error": T['certificate_error']}
        except requests.ConnectionError:
            return {"error": T['connection_error']}
        except requests.HTTPError as error:
            response = error.response
            code = response.status_code if response is not None else 0
            server_message = _extract_server_message(response)
            extra: dict[str, Any] = {}
            if server_message:
                extra["server_message"] = server_message
            if code == 401:
                return {
                    **extra,
                    "error": T['auth_expired'],
                    "auth_error": True,
                }
            if code == 429:
                retry_after = _parse_retry_after(response)
                if retry_after is not None:
                    extra["retry_after"] = retry_after
                return {
                    **extra,
                    "error": "API request failed (HTTP 429).",
                    "rate_limited": True,
                }
            if 500 <= code < 600:
                return {
                    **extra,
                    "error": f"Anthropic API temporarily unavailable (HTTP {code}).",
                }
            return {**extra, "error": f"API request failed (HTTP {code or '?'})."}
        except Exception:
            return {"error": "Could not connect to Anthropic API."}

    def fetch_profile(self, token: str | None | object = _UNSET) -> dict[str, Any] | None:
        """Fetch account identity with a caller-pinned token."""
        headers = self.api_headers(token)
        if headers is None:
            return None
        try:
            return self._get(API_URL_PROFILE, headers).json()
        except Exception:
            return None

    @staticmethod
    def _get(url: str, headers: dict[str, str]) -> requests.Response:
        if url not in (API_URL_USAGE, API_URL_PROFILE):
            raise ValueError("Claude API URL is outside the allowed origin")
        response = requests.get(
            url,
            headers=headers,
            timeout=10,
            allow_redirects=False,
        )
        if 300 <= response.status_code < 400:
            raise requests.HTTPError(response=response)
        response.raise_for_status()
        return response


def merge_scoped_limits(data: dict[str, Any]) -> dict[str, Any]:
    """Expose active model-scoped limits as ordinary quota fields."""
    limits = data.get("limits")
    if not isinstance(limits, list):
        return data

    reset_to_field: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, dict) and value.get("utilization") is not None:
            resets_at = value.get("resets_at")
            if isinstance(resets_at, str) and resets_at:
                reset_to_field.setdefault(resets_at, key)

    group_prefix: dict[str, str] = {}
    for limit in limits:
        if not isinstance(limit, dict) or limit.get("scope"):
            continue
        group = limit.get("group")
        resets_at = limit.get("resets_at")
        if isinstance(group, str) and isinstance(resets_at, str) and resets_at in reset_to_field:
            group_prefix.setdefault(group, reset_to_field[resets_at])

    merged = dict(data)
    for limit in limits:
        if not isinstance(limit, dict):
            continue
        scope = limit.get("scope")
        model = scope.get("model") if isinstance(scope, dict) else None
        display_name = model.get("display_name") if isinstance(model, dict) else None
        group = limit.get("group")
        prefix = group_prefix.get(group) if isinstance(group, str) else None
        if not isinstance(display_name, str) or not display_name or not prefix:
            continue
        field = f"{prefix}_{_model_slug(display_name)}"
        if merged.get(field) is None:
            merged[field] = {
                "utilization": float(limit.get("percent") or 0),
                "resets_at": limit.get("resets_at"),
                "from_account_limits": True,
            }
    return merged


def _model_slug(display_name: str) -> str:
    cleaned = "".join(char if char.isalnum() else " " for char in display_name.lower())
    return "_".join(cleaned.split())


def _extract_server_message(response: requests.Response | None) -> str | None:
    if response is None:
        return None
    try:
        message = response.json().get("error", {}).get("message") or None
        if message:
            message = message.removesuffix(" Please try again later.")
            message = message.removesuffix(" Please try again later").strip()
        return message or None
    except Exception:
        return None


def _parse_retry_after(response: requests.Response | None) -> int | None:
    if response is None:
        return None
    try:
        retry_after = response.headers.get("Retry-After")
        return max(int(retry_after), 0) if retry_after is not None else None
    except (TypeError, ValueError):
        return None
