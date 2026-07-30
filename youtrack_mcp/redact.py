"""Redact secret-shaped values before they reach a log line or exception text.

Used by both REST clients (:mod:`youtrack_mcp.client`,
:mod:`youtrack_mcp.admin`) when logging a non-2xx response body for
debugging. The Hub admin API (``AdminClient.create_token`` and friends) can
legitimately return a permanent token *inside a response body*; if that
response also happens to trip an error path (e.g. a downstream 5xx after the
token was minted, or a test/mock echoing the request), the raw body must
never reach a log verbatim.
"""

from __future__ import annotations

import json
import re
from typing import Any

REDACTED = "***REDACTED***"

#: Key names (case-insensitive, matched as whole segments so "token" doesn't
#: also match "tokenizer") whose values are always masked, wherever they show
#: up -- top-level or nested inside lists/dicts.
SECRET_KEYS = frozenset(
    {
        "token",
        "access_token",
        "accesstoken",
        "refresh_token",
        "refreshtoken",
        "permanenttoken",
        "permanent_token",
        "api_key",
        "apikey",
        "secret",
        "client_secret",
        "clientsecret",
        "password",
        "passwd",
        "authorization",
    }
)

#: Fallback for bodies that aren't valid JSON (HTML error pages, plain text):
#: mask ``"<secret-key>"`` / ``'<secret-key>'`` / ``<secret-key>=`` style
#: key-value pairs directly in the raw text.
_TEXT_PATTERN = re.compile(
    r'(?i)(["\']?(?:'
    + "|".join(re.escape(k) for k in SECRET_KEYS)
    + r')["\']?\s*[:=]\s*)(["\']?)([^"\'\s,}]+)(\2)'
)


def _redact_value(key: str, value: Any) -> Any:
    if key.lower() in SECRET_KEYS:
        return REDACTED
    return redact_json(value)


def redact_json(data: Any) -> Any:
    """Recursively mask secret-keyed values in a parsed JSON structure."""
    if isinstance(data, dict):
        return {k: _redact_value(k, v) for k, v in data.items()}
    if isinstance(data, list):
        return [redact_json(item) for item in data]
    return data


def redact_text(body: str) -> str:
    """Best-effort redaction for a raw response body.

    Tries to parse ``body`` as JSON and mask secret fields structurally; if
    that fails (non-JSON body), falls back to a regex substitution so a
    ``token=...`` or ``"token": "..."`` fragment in plain text/HTML is still
    masked rather than logged verbatim.
    """
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return _TEXT_PATTERN.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}{m.group(2)}", body)
    return json.dumps(redact_json(parsed), ensure_ascii=False)
