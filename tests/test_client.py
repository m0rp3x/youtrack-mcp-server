"""Client tests using a stubbed httpx transport (no real network)."""

import logging

import httpx
import pytest

import youtrack_mcp.client as client_module
from youtrack_mcp.client import (
    ISSUE_DETAIL_FIELDS,
    ISSUE_LIST_FIELDS,
    YouTrackClient,
    YouTrackError,
)


def _make_client(handler) -> YouTrackClient:
    return YouTrackClient(
        "https://yt.example.com/", "perm-test", transport=httpx.MockTransport(handler)
    )


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Retry/backoff tests would otherwise really wait ~0.5-1.5s per case.

    Patch ``asyncio.sleep`` as seen from the client module so the retry loop
    still awaits *something* (keeping it a real coroutine boundary) but tests
    run instantly. Calls are recorded so tests can assert on the delay chosen
    (e.g. that a 429's ``Retry-After`` was actually honoured).
    """
    calls = []

    async def _fake_sleep(seconds):
        calls.append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", _fake_sleep)
    return calls


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
    assert seen["query"]["fields"] == ISSUE_LIST_FIELDS
    assert issues[0]["idReadable"] == "DEMO-1"


async def test_search_issues_requests_list_fields_only():
    """search_issues (list view: my_issues/search_issues) must request only
    what format_issue_line reads — no description/project/reporter, and no
    dead top-level fields (created/updated)."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["fields"] = dict(request.url.params)["fields"]
        return httpx.Response(200, json=[])

    client = _make_client(handler)
    await client.search_issues("for: me")
    await client.aclose()

    fields = seen["fields"]
    assert fields == ISSUE_LIST_FIELDS
    # needed by format_issue_line / state_of
    assert "idReadable" in fields
    assert "summary" in fields
    assert "resolved" in fields
    assert "customFields(name,value(name,fullName,login,presentation,text))" in fields
    # never read for the list view
    assert "description" not in fields
    assert "project" not in fields
    assert "reporter" not in fields
    # dead weight, never read at all
    assert "created" not in fields
    assert "updated" not in fields
    assert "minutes" not in fields


async def test_get_issue_requests_detail_fields():
    """get_issue (detail view) must request everything format_issue_detail
    reads, but drop dead fields: created/updated, reporter.fullName,
    customFields.value.minutes."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["fields"] = dict(request.url.params)["fields"]
        return httpx.Response(200, json={"idReadable": "DEMO-12"})

    client = _make_client(handler)
    await client.get_issue("DEMO-12")
    await client.aclose()

    fields = seen["fields"]
    assert fields == ISSUE_DETAIL_FIELDS
    # needed by format_issue_detail (and format_issue_line it calls)
    assert "idReadable" in fields
    assert "summary" in fields
    assert "description" in fields
    assert "resolved" in fields
    assert "project(shortName,name)" in fields
    assert "customFields(name,value(name,fullName,login,presentation,text))" in fields
    # reporter.login is read, reporter.fullName is not
    assert "reporter(login)" in fields
    assert "reporter(login,fullName)" not in fields
    # dead weight, never read at all
    assert "created" not in fields
    assert "updated" not in fields
    assert "minutes" not in fields


async def test_create_issue_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        seen["fields"] = dict(request.url.params)["fields"]
        return httpx.Response(200, json={"idReadable": "DEMO-42", "summary": "hi"})

    client = _make_client(handler)
    issue = await client.create_issue("DEMO", "hi", "body")
    await client.aclose()

    assert seen["body"]["project"]["shortName"] == "DEMO"
    assert seen["body"]["summary"] == "hi"
    assert seen["body"]["description"] == "body"
    assert issue["idReadable"] == "DEMO-42"
    # create_issue's response is rendered like a detail view (format_issue_line
    # + issue_url), so it uses the same detail selector as get_issue.
    assert seen["fields"] == ISSUE_DETAIL_FIELDS


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


# -- retry/timeout policy (ADR-0002) -----------------------------------------


async def test_get_retries_on_503_then_succeeds():
    """GET has no side effects, so a transient 5xx is retried within budget."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(200, json={"login": "klod"})

    client = _make_client(handler)
    result = await client.me()
    await client.aclose()

    assert calls["n"] == 2
    assert result["login"] == "klod"


async def test_post_does_not_retry_on_503():
    """A 5xx on a side-effecting POST is fatal immediately: we can't tell
    whether the issue was actually created before the error response, so a
    blind retry risks creating it twice."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="Service Unavailable")

    client = _make_client(handler)
    with pytest.raises(YouTrackError, match="503"):
        await client.create_issue("DEMO", "hi")
    await client.aclose()

    assert calls["n"] == 1


async def test_post_does_not_retry_on_read_timeout():
    """Same reasoning as the 503 case: a ReadTimeout means the request may
    have already reached and been applied by the server."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("timed out", request=request)

    client = _make_client(handler)
    with pytest.raises(YouTrackError):
        await client.create_issue("DEMO", "hi")
    await client.aclose()

    assert calls["n"] == 1


async def test_post_retries_on_connect_error():
    """A ConnectError means the connection never established, i.e. the
    request definitely wasn't sent yet — safe to retry even for a POST."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json={"idReadable": "DEMO-1", "summary": "hi"})

    client = _make_client(handler)
    issue = await client.create_issue("DEMO", "hi")
    await client.aclose()

    assert calls["n"] == 2
    assert issue["idReadable"] == "DEMO-1"


async def test_429_honours_retry_after_header(_no_real_sleep):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, text="rate limited")
        return httpx.Response(200, json={"login": "klod"})

    client = _make_client(handler)
    result = await client.me()
    await client.aclose()

    assert calls["n"] == 2
    assert result["login"] == "klod"
    assert _no_real_sleep == [2.0]  # header wins over the normal backoff schedule


async def test_429_retry_after_beyond_ceiling_is_fatal(_no_real_sleep):
    """A Retry-After above the ceiling must fail fast rather than block a
    synchronous MCP tool-call for that long."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "30"}, text="rate limited")

    client = _make_client(handler)
    with pytest.raises(YouTrackError, match="429"):
        await client.me()
    await client.aclose()

    assert calls["n"] == 1
    assert _no_real_sleep == []  # never waited


async def test_retry_budget_exhausted_raises_last_error():
    """Running out of the attempt budget raises the last error seen, not a
    generic/swallowed failure."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text=f"Service Unavailable (attempt {calls['n']})")

    client = _make_client(handler)
    with pytest.raises(YouTrackError, match="attempt 3"):
        await client.me()
    await client.aclose()

    assert calls["n"] == 3  # 1 initial + 2 retries, then give up
