"""Server-level tests for MCP tool wiring (no real network)."""

import httpx

import youtrack_mcp.server as server
from youtrack_mcp.client import YouTrackClient


async def test_create_issue_returns_explicit_url(monkeypatch):
    """create_issue's response includes an explicit ``url:`` field built from
    YOUTRACK_URL + idReadable, in addition to the existing summary line."""
    monkeypatch.setenv("YOUTRACK_URL", "https://yt.example.com/")
    monkeypatch.setenv("YOUTRACK_TOKEN", "perm-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"idReadable": "DEMO-42", "summary": "hi"})

    fake_client = YouTrackClient(
        "https://yt.example.com/", "perm-test", transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(server, "_client", fake_client)

    try:
        result = await server.create_issue("DEMO", "hi")
    finally:
        monkeypatch.setattr(server, "_client", None)
        await fake_client.aclose()

    # Existing behavior preserved: still starts with "Created " + the one-line summary.
    assert result.startswith("Created DEMO-42")
    # New, explicit field: the trailing-slash on YOUTRACK_URL is normalized away.
    assert "url: https://yt.example.com/issue/DEMO-42" in result


async def test_create_issue_url_uses_configured_youtrack_url(monkeypatch):
    """The URL is built from the client's configured base URL, not hardcoded."""
    monkeypatch.setenv("YOUTRACK_URL", "https://other-instance.example.com")
    monkeypatch.setenv("YOUTRACK_TOKEN", "perm-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"idReadable": "OPS-1", "summary": "x"})

    fake_client = YouTrackClient(
        "https://other-instance.example.com", "perm-test", transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(server, "_client", fake_client)

    try:
        result = await server.create_issue("OPS", "x")
    finally:
        monkeypatch.setattr(server, "_client", None)
        await fake_client.aclose()

    assert "url: https://other-instance.example.com/issue/OPS-1" in result
