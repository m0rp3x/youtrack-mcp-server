"""A thin async REST client for the JetBrains YouTrack API.

Only the handful of endpoints the MCP tools need are implemented. Every method
returns parsed JSON (``dict``/``list``) exactly as YouTrack sends it; formatting
for humans/LLMs lives in :mod:`youtrack_mcp.formatting`.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .redact import redact_text

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0

#: Field selector used whenever we fetch issues. YouTrack returns nothing unless
#: fields are requested explicitly, so keep this in one place.
ISSUE_FIELDS = (
    "idReadable,summary,description,resolved,created,updated,"
    "project(shortName,name),reporter(login,fullName),"
    "customFields(name,value(name,fullName,login,presentation,text,minutes))"
)
COMMENT_FIELDS = "id,text,created,author(login,fullName)"
PROJECT_FIELDS = "shortName,name,archived"


class YouTrackError(RuntimeError):
    """Raised when the YouTrack API responds with a non-2xx status."""


class YouTrackClient:
    """Minimal async wrapper around the YouTrack REST API.

    Args:
        base_url: Base URL of the YouTrack instance, e.g. ``https://yt.example.com``
            (with or without a trailing slash; the ``/api`` prefix is added here).
        token: A YouTrack permanent token (``perm-…``).
        timeout: Per-request timeout in seconds.
        transport: Optional ``httpx`` transport, used by the test-suite to stub
            network access.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    @property
    def api_url(self) -> str:
        """Fully-qualified REST API root, e.g. ``https://yt.example.com/api``."""
        return f"{self._base_url}/api"

    @property
    def base_url(self) -> str:
        """Instance base URL (no trailing slash), e.g. ``https://yt.example.com``."""
        return self._base_url

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            # Trailing slash on base_url + slash-less relative paths keeps httpx
            # from discarding the "/api" prefix when it joins the URL.
            self._client = httpx.AsyncClient(
                base_url=self.api_url + "/",
                headers=self._headers,
                timeout=self._timeout,
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> Any:
        resp = await self._http().request(method, path, params=params, json=json)
        if resp.status_code >= 400:
            redacted_body = redact_text(resp.text)
            # Full body (redacted) goes to the log for debugging; the exception
            # message re-uses the same redacted text so a secret can't leak via
            # either path.
            logger.error(
                "YouTrack API error: %s %s /%s -> %s: %s",
                method, self.api_url, path, resp.status_code, redacted_body,
            )
            raise YouTrackError(f"{resp.status_code} {method} /{path}: {redacted_body}")
        return resp.json() if resp.content else None

    # -- reads ---------------------------------------------------------------

    async def me(self) -> dict[str, Any]:
        """Return the profile of the token owner."""
        return await self._request(
            "GET", "users/me", params={"fields": "login,fullName,email"}
        )

    async def search_issues(
        self, query: str, *, top: int = 30, fields: str = ISSUE_FIELDS
    ) -> list[dict[str, Any]]:
        """Return issues matching a YouTrack search ``query``."""
        return await self._request(
            "GET", "issues", params={"query": query, "fields": fields, "$top": top}
        )

    async def get_issue(self, issue_id: str, *, fields: str = ISSUE_FIELDS) -> dict[str, Any]:
        """Fetch a single issue by readable (``DEMO-12``) or internal id."""
        return await self._request("GET", f"issues/{issue_id}", params={"fields": fields})

    async def list_projects(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        """List projects visible to the token owner."""
        projects = await self._request(
            "GET", "admin/projects", params={"fields": PROJECT_FIELDS, "$top": 200}
        )
        if include_archived:
            return projects
        return [p for p in projects if not p.get("archived")]

    # -- writes --------------------------------------------------------------

    async def create_issue(
        self, project: str, summary: str, description: str | None = None
    ) -> dict[str, Any]:
        """Create an issue in ``project`` (its short name, e.g. ``DEMO``)."""
        body: dict[str, Any] = {"project": {"shortName": project}, "summary": summary}
        if description:
            body["description"] = description
        return await self._request("POST", "issues", params={"fields": ISSUE_FIELDS}, json=body)

    async def apply_command(
        self, command: str, issues: list[str], comment: str | None = None
    ) -> Any:
        """Apply a YouTrack command (e.g. ``State Done``, ``for me``) to issues."""
        body: dict[str, Any] = {
            "query": command,
            "issues": [{"idReadable": i} for i in issues],
        }
        if comment:
            body["comment"] = comment
        return await self._request("POST", "commands", json=body)

    async def add_comment(self, issue_id: str, text: str) -> dict[str, Any]:
        """Add a comment to an issue."""
        return await self._request(
            "POST",
            f"issues/{issue_id}/comments",
            params={"fields": COMMENT_FIELDS},
            json={"text": text},
        )
