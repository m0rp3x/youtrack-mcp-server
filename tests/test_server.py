"""Tool-level tests for the create_issue / search_issues MCP tools.

These exercise the tool functions in :mod:`youtrack_mcp.server` directly,
against a fake in-memory client (no real network, no YouTrack instance
required). Client-level HTTP behaviour is covered separately in
``tests/test_client.py``.
"""

from __future__ import annotations

import pytest

from youtrack_mcp import server
from youtrack_mcp.client import YouTrackError

DEMO_ISSUE = {
    "idReadable": "DEMO-42",
    "summary": "Fix login",
    "resolved": None,
    "customFields": [],
}


class _FakeClient:
    """Stand-in for YouTrackClient: records calls, returns canned results."""

    def __init__(self, *, create_result=None, search_result=None, error=None):
        self._create_result = create_result
        self._search_result = search_result
        self._error = error
        self.create_calls: list[tuple] = []
        self.search_calls: list[tuple] = []

    async def create_issue(self, project, summary, description=None):
        if self._error is not None:
            raise self._error
        self.create_calls.append((project, summary, description))
        return self._create_result

    async def search_issues(self, query, *, top=30, fields=None):
        if self._error is not None:
            raise self._error
        self.search_calls.append((query, top))
        return self._search_result


@pytest.fixture(autouse=True)
def _reset_cached_client(monkeypatch):
    """Server caches a module-global client; make sure tests don't leak it."""
    monkeypatch.setattr(server, "_client", None)
    yield
    monkeypatch.setattr(server, "_client", None)


# -- create_issue -------------------------------------------------------------


async def test_create_issue_returns_issue_id(monkeypatch):
    fake = _FakeClient(create_result=DEMO_ISSUE)
    monkeypatch.setattr(server, "_client", fake)

    result = await server.create_issue(project="DEMO", summary="Fix login")

    assert "DEMO-42" in result
    assert fake.create_calls == [("DEMO", "Fix login", None)]


async def test_create_issue_passes_description_through(monkeypatch):
    fake = _FakeClient(create_result=DEMO_ISSUE)
    monkeypatch.setattr(server, "_client", fake)

    await server.create_issue(project="DEMO", summary="Fix login", description="steps to repro")

    assert fake.create_calls == [("DEMO", "Fix login", "steps to repro")]


async def test_create_issue_empty_description_is_not_sent(monkeypatch):
    fake = _FakeClient(create_result=DEMO_ISSUE)
    monkeypatch.setattr(server, "_client", fake)

    await server.create_issue(project="DEMO", summary="Fix login", description="")

    assert fake.create_calls == [("DEMO", "Fix login", None)]


async def test_create_issue_surfaces_api_error(monkeypatch):
    fake = _FakeClient(error=YouTrackError("422 POST /issues: Project not found"))
    monkeypatch.setattr(server, "_client", fake)

    with pytest.raises(YouTrackError, match="Project not found"):
        await server.create_issue(project="NOPE", summary="x")


# -- search_issues --------------------------------------------------------------


async def test_search_issues_returns_matching_issues(monkeypatch):
    fake = _FakeClient(search_result=[DEMO_ISSUE])
    monkeypatch.setattr(server, "_client", fake)

    result = await server.search_issues(query="project: DEMO")

    assert "DEMO-42" in result
    assert fake.search_calls == [("project: DEMO", 30)]


async def test_search_issues_respects_limit(monkeypatch):
    fake = _FakeClient(search_result=[DEMO_ISSUE])
    monkeypatch.setattr(server, "_client", fake)

    await server.search_issues(query="project: DEMO", limit=5)

    assert fake.search_calls == [("project: DEMO", 5)]


async def test_search_issues_no_results_message(monkeypatch):
    fake = _FakeClient(search_result=[])
    monkeypatch.setattr(server, "_client", fake)

    result = await server.search_issues(query="project: NONE")

    assert result == "No issues found."


async def test_search_issues_surfaces_api_error(monkeypatch):
    fake = _FakeClient(error=YouTrackError("400 GET /issues: Incorrect query syntax"))
    monkeypatch.setattr(server, "_client", fake)

    with pytest.raises(YouTrackError, match="Incorrect query syntax"):
        await server.search_issues(query="not a valid query (")
