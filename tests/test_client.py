"""Client tests using a stubbed httpx transport (no real network)."""

import httpx
import pytest

from youtrack_mcp.client import YouTrackClient, YouTrackError


def _make_client(handler) -> YouTrackClient:
    return YouTrackClient(
        "https://yt.example.com/", "perm-test", transport=httpx.MockTransport(handler)
    )


def test_api_url_strips_trailing_slash():
    client = YouTrackClient("https://yt.example.com/", "t")
    assert client.api_url == "https://yt.example.com/api"


async def test_me_hits_correct_path_and_auth():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"login": "klod", "fullName": "Клод"})

    client = _make_client(handler)
    me = await client.me()
    await client.aclose()

    assert seen["path"] == "/api/users/me"  # the /api prefix is preserved
    assert seen["auth"] == "Bearer perm-test"
    assert me["login"] == "klod"


async def test_search_passes_query_and_top():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = dict(request.url.params)
        return httpx.Response(200, json=[{"idReadable": "DEMO-1"}])

    client = _make_client(handler)
    issues = await client.search_issues("for: me", top=5)
    await client.aclose()

    assert seen["query"]["query"] == "for: me"
    assert seen["query"]["$top"] == "5"
    assert issues[0]["idReadable"] == "DEMO-1"


async def test_create_issue_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"idReadable": "DEMO-42", "summary": "hi"})

    client = _make_client(handler)
    issue = await client.create_issue("DEMO", "hi", "body")
    await client.aclose()

    assert seen["body"]["project"]["shortName"] == "DEMO"
    assert seen["body"]["summary"] == "hi"
    assert seen["body"]["description"] == "body"
    assert issue["idReadable"] == "DEMO-42"


async def test_error_status_raises():
    client = _make_client(lambda req: httpx.Response(403, text="Forbidden"))
    with pytest.raises(YouTrackError):
        await client.me()
    await client.aclose()
