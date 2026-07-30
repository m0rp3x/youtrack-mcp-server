"""Client tests using a stubbed httpx transport (no real network)."""

import logging

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


async def test_apply_command_body_for_status_change():
    """apply_command is the workflow-validated way to change an issue's State
    (POST /api/commands), same endpoint the ``run_command`` tool wraps.
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    client = _make_client(handler)
    await client.apply_command("State Done", ["DEMO-12"], "closing this")
    await client.aclose()

    assert seen["path"] == "/api/commands"
    assert seen["body"]["query"] == "State Done"
    assert seen["body"]["issues"] == [{"idReadable": "DEMO-12"}]
    assert seen["body"]["comment"] == "closing this"


async def test_apply_command_omits_comment_when_not_given():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    client = _make_client(handler)
    await client.apply_command("State Done", ["DEMO-12"])
    await client.aclose()

    assert "comment" not in seen["body"]


async def test_apply_command_multiple_issues():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    client = _make_client(handler)
    await client.apply_command("Priority Critical", ["DEMO-12", "DEMO-13"])
    await client.aclose()

    assert seen["body"]["issues"] == [
        {"idReadable": "DEMO-12"},
        {"idReadable": "DEMO-13"},
    ]


async def test_apply_command_invalid_transition_raises():
    """YouTrack rejects a command that names a state outside the issue's
    workflow (e.g. a State value that doesn't exist for the project) with a
    non-2xx response; the client surfaces this as YouTrackError rather than
    silently swallowing it, so the workflow validation done server-side by
    YouTrack is not bypassed.
    """
    client = _make_client(
        lambda req: httpx.Response(
            400, json={"error_description": "Value 'Bogus' is not valid for field State"}
        )
    )
    with pytest.raises(YouTrackError, match="Bogus"):
        await client.apply_command("State Bogus", ["DEMO-12"])
    await client.aclose()


async def test_add_comment_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"id": "4-1", "text": "hello", "author": {"login": "klod"}},
        )

    client = _make_client(handler)
    comment = await client.add_comment("DEMO-12", "hello")
    await client.aclose()

    assert seen["path"] == "/api/issues/DEMO-12/comments"
    assert seen["body"] == {"text": "hello"}
    assert comment["id"] == "4-1"
    assert comment["text"] == "hello"


async def test_add_comment_permission_error_raises():
    client = _make_client(lambda req: httpx.Response(403, text="Forbidden: Create Comment"))
    with pytest.raises(YouTrackError):
        await client.add_comment("DEMO-12", "hello")
    await client.aclose()


async def test_error_status_raises():
    client = _make_client(lambda req: httpx.Response(403, text="Forbidden"))
    with pytest.raises(YouTrackError):
        await client.me()
    await client.aclose()


async def test_error_response_body_is_logged_for_debugging(caplog):
    """4xx/5xx responses must land the full response body in the log so an
    incident can be diagnosed from logs alone, not just the truncated
    exception message."""
    client = _make_client(
        lambda req: httpx.Response(
            500, json={"error": "internal", "detail": "issue index is stale, retry later"}
        )
    )
    caplog.set_level(logging.ERROR)

    with pytest.raises(YouTrackError):
        await client.me()
    await client.aclose()

    assert "issue index is stale, retry later" in caplog.text
    assert "500" in caplog.text


async def test_list_projects_hides_archived_by_default():
    """include_archived defaults to False, so an archived project in the API
    response must be filtered out client-side before it reaches callers."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"shortName": "DEMO", "name": "Demo project", "archived": False},
                {"shortName": "OLD", "name": "Retired project", "archived": True},
            ],
        )

    client = _make_client(handler)
    projects = await client.list_projects()
    await client.aclose()

    assert [p["shortName"] for p in projects] == ["DEMO"]


async def test_list_projects_include_archived_returns_everything():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"shortName": "DEMO", "name": "Demo project", "archived": False},
                {"shortName": "OLD", "name": "Retired project", "archived": True},
            ],
        )

    client = _make_client(handler)
    projects = await client.list_projects(include_archived=True)
    await client.aclose()

    assert {p["shortName"] for p in projects} == {"DEMO", "OLD"}


async def test_list_projects_requests_archived_field():
    """The ``archived`` field must be requested explicitly, else YouTrack omits
    it and the archived filter above would silently do nothing."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["fields"] = dict(request.url.params)["fields"]
        return httpx.Response(200, json=[])

    client = _make_client(handler)
    await client.list_projects()
    await client.aclose()

    assert "archived" in seen["fields"]
    assert "shortName" in seen["fields"]
