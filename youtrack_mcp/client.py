"""A thin async REST client for the JetBrains YouTrack API.

Only the handful of endpoints the MCP tools need are implemented. Every method
returns parsed JSON (``dict``/``list``) exactly as YouTrack sends it; formatting
for humans/LLMs lives in :mod:`youtrack_mcp.formatting`.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

from .redact import redact_text

logger = logging.getLogger(__name__)

# connect/pool fail fast (unreachable host shouldn't block a synchronous MCP
# tool-call for 30s); read stays generous since large project searches/reports
# can legitimately take a while on YouTrack's side. See ADR-0002 §5.
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)

#: Total attempt budget per request: 1 initial try + 2 retries. See ADR-0002 §3.
_MAX_ATTEMPTS = 3
#: Backoff before attempt 2 and attempt 3 respectively, before jitter.
_BACKOFF_SCHEDULE = (0.5, 1.0)
_JITTER_FRACTION = 0.2
#: If a 429's Retry-After asks for longer than this, fail fast instead of
#: blocking the synchronous MCP tool-call.
_RETRY_AFTER_CEILING = 10.0

#: Any of these are safe to retry on a GET: the request has no side effects.
_RETRYABLE_ON_READ = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)
#: For a side-effecting POST, only retry errors where the request is known not
#: to have reached the server (connection never established). A ReadTimeout or
#: RemoteProtocolError on a POST means we can't tell if it was already applied,
#: so those are fatal instead of risking a duplicate issue/command.
_RETRYABLE_ON_WRITE = (httpx.ConnectError, httpx.ConnectTimeout)

#: Field selectors used whenever we fetch issues. YouTrack returns nothing
#: unless fields are requested explicitly, so keep these in one place.
#:
#: ``formatting.py`` renders two distinct views: ``format_issue_line`` (one
#: line: id, state, summary, assignee) for list-y results, and
#: ``format_issue_detail`` (adds project, reporter login, priority/type/due
#: date, description) for a single issue. Each selector below requests only
#: what its consumers actually read — no ``created``/``updated`` (never
#: read), no ``reporter.fullName`` (only ``login`` is read), no
#: ``customFields.value.minutes`` (never read).
ISSUE_LIST_FIELDS = (
    "idReadable,summary,resolved,"
    "customFields(name,value(name,fullName,login,presentation,text))"
)
ISSUE_DETAIL_FIELDS = (
    "idReadable,summary,description,resolved,"
    "project(shortName,name),reporter(login),"
    "customFields(name,value(name,fullName,login,presentation,text))"
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
        timeout: Per-request timeout. Either a single number of seconds applied
            uniformly to every phase (kept for backwards compatibility, e.g.
            existing tests that pass a plain ``float``), or an ``httpx.Timeout``
            to set connect/read/write/pool independently. Defaults to
            :data:`DEFAULT_TIMEOUT`.
        transport: Optional ``httpx`` transport, used by the test-suite to stub
            network access.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float | httpx.Timeout = DEFAULT_TIMEOUT,
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

    def _log_error_response(self, method: str, path: str, resp: httpx.Response) -> str:
        """Log the full (redacted) error body and return the same redacted text.

        The exception message re-uses this redacted text so a secret can't
        leak via either the log or the exception path -- only the
        log-vs-exception body length changed (no more silent 500-char
        truncation), not what's masked. See #3602.
        """
        redacted_body = redact_text(resp.text)
        logger.error(
            "YouTrack API error: %s %s /%s -> %s: %s",
            method, self.api_url, path, resp.status_code, redacted_body,
        )
        return redacted_body

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> Any:
        """Perform one HTTP call, retrying transient failures per ADR-0002.

        GET is idempotent and retries any network error or 5xx. A
        side-effecting method (POST) only retries errors known to have
        happened before the request reached the server (``ConnectError``/
        ``ConnectTimeout``); a ``ReadTimeout`` or 5xx there is raised
        immediately since a retry risks duplicating the side effect. ``429``
        always retries (a rejection by the rate limiter can't have applied
        any side effect), honouring ``Retry-After`` up to a ceiling so a
        synchronous MCP tool-call never blocks for longer than that.
        """
        is_get = method.upper() == "GET"
        retryable_network_errors = _RETRYABLE_ON_READ if is_get else _RETRYABLE_ON_WRITE

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                resp = await self._http().request(method, path, params=params, json=json)
            except _RETRYABLE_ON_READ as exc:
                if not isinstance(exc, retryable_network_errors) or attempt == _MAX_ATTEMPTS:
                    raise YouTrackError(
                        f"{method} /{path} failed on attempt {attempt}/{_MAX_ATTEMPTS} "
                        f"(not retried further): {exc!r}"
                    ) from exc
                await self._sleep_before_retry(attempt)
                continue

            if resp.status_code == 429:
                retry_after = self._retry_after_seconds(resp)
                if retry_after is not None and retry_after > _RETRY_AFTER_CEILING:
                    body = self._log_error_response(method, path, resp)
                    raise YouTrackError(
                        f"429 {method} /{path}: rate limited, Retry-After="
                        f"{retry_after:.0f}s exceeds {_RETRY_AFTER_CEILING:.0f}s ceiling, "
                        f"not waiting: {body}"
                    )
                if attempt == _MAX_ATTEMPTS:
                    body = self._log_error_response(method, path, resp)
                    raise YouTrackError(
                        f"429 {method} /{path}: rate limited, retry budget exhausted "
                        f"after {attempt} attempt(s): {body}"
                    )
                if retry_after is not None:
                    await asyncio.sleep(retry_after)
                else:
                    await self._sleep_before_retry(attempt)
                continue

            if resp.status_code >= 500:
                if not is_get or attempt == _MAX_ATTEMPTS:
                    body = self._log_error_response(method, path, resp)
                    raise YouTrackError(
                        f"{resp.status_code} {method} /{path} "
                        f"(attempt {attempt}/{_MAX_ATTEMPTS}): {body}"
                    )
                await self._sleep_before_retry(attempt)
                continue

            if resp.status_code >= 400:
                body = self._log_error_response(method, path, resp)
                raise YouTrackError(f"{resp.status_code} {method} /{path}: {body}")

            return resp.json() if resp.content else None

        # Unreachable: the loop above always returns or raises before running
        # out of attempts.
        raise AssertionError("retry loop exited without returning or raising")

    @staticmethod
    async def _sleep_before_retry(attempt: int) -> None:
        base = _BACKOFF_SCHEDULE[attempt - 1]
        jitter = base * _JITTER_FRACTION
        await asyncio.sleep(base + random.uniform(-jitter, jitter))

    @staticmethod
    def _retry_after_seconds(resp: httpx.Response) -> float | None:
        header = resp.headers.get("Retry-After")
        if header is None:
            return None
        try:
            return float(header)
        except ValueError:
            # YouTrack is not expected to send the HTTP-date form; if it ever
            # does, fall back to the normal backoff schedule rather than
            # failing to parse it.
            return None

    # -- reads ---------------------------------------------------------------

    async def me(self) -> dict[str, Any]:
        """Return the profile of the token owner."""
        return await self._request(
            "GET", "users/me", params={"fields": "login,fullName,email"}
        )

    async def search_issues(
        self, query: str, *, top: int = 30, fields: str = ISSUE_LIST_FIELDS
    ) -> list[dict[str, Any]]:
        """Return issues matching a YouTrack search ``query``."""
        return await self._request(
            "GET", "issues", params={"query": query, "fields": fields, "$top": top}
        )

    async def get_issue(
        self, issue_id: str, *, fields: str = ISSUE_DETAIL_FIELDS
    ) -> dict[str, Any]:
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
        return await self._request(
            "POST", "issues", params={"fields": ISSUE_DETAIL_FIELDS}, json=body
        )

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
