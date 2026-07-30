"""Admin/provisioning tests using a stubbed Hub transport (no network)."""

import json
import logging

import httpx
import pytest

from youtrack_mcp.admin import AdminClient, AdminError
from youtrack_mcp.redact import REDACTED

SERVICES = {
    "services": [
        {"id": "yt-svc", "name": "YouTrack"},
        {"id": "hub-svc", "name": "YouTrack Administration"},
        {"id": "other", "name": "Konnector"},
    ]
}
ROLES = {
    "roles": [
        {"id": "role-contrib", "key": "contributor"},
        {"id": "role-sa", "key": "system-admin"},
    ]
}


def _hub(handler) -> AdminClient:
    return AdminClient(
        "https://yt.example.com/", "perm-admin", transport=httpx.MockTransport(handler)
    )


async def test_provision_creates_user_role_and_token():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append((request.method, path))
        if path == "/hub/api/rest/services":
            return httpx.Response(200, json=SERVICES)
        if path == "/hub/api/rest/roles":
            return httpx.Response(200, json=ROLES)
        if path == "/hub/api/rest/users" and request.method == "GET":
            return httpx.Response(200, json={"users": []})  # not found -> create
        if path == "/hub/api/rest/users" and request.method == "POST":
            return httpx.Response(200, json={"id": "u1", "login": "agent-a", "name": "Agent A"})
        if path == "/hub/api/rest/users/u1/projectroles" and request.method == "GET":
            return httpx.Response(200, json={"projectroles": []})
        if path == "/hub/api/rest/users/u1/projectroles" and request.method == "POST":
            body = json.loads(request.content)
            assert body["role"]["id"] == "role-contrib"
            assert body["project"]["id"] == "0"
            return httpx.Response(200, json={"id": "pr1"})
        if path == "/hub/api/rest/users/u1/permanenttokens" and request.method == "POST":
            body = json.loads(request.content)
            scope_ids = {s["id"] for s in body["scope"]}
            assert scope_ids == {"yt-svc", "hub-svc"}  # both services scoped
            return httpx.Response(200, json={"token": "perm-agenttoken"})
        return httpx.Response(404, text=f"unexpected {path}")

    client = _hub(handler)
    agent = await client.provision_agent("agent-a", "Agent A", role="contributor")
    await client.aclose()

    assert agent.token == "perm-agenttoken"
    assert agent.user_id == "u1"
    assert ("POST", "/hub/api/rest/users") in calls


async def test_provision_reuses_existing_user_and_skips_present_role():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/hub/api/rest/services":
            return httpx.Response(200, json=SERVICES)
        if path == "/hub/api/rest/users" and request.method == "GET":
            return httpx.Response(200, json={"users": [{"id": "u9", "login": "agent-a"}]})
        if path == "/hub/api/rest/users" and request.method == "POST":
            raise AssertionError("should not create an existing user")
        if path == "/hub/api/rest/users/u9/projectroles" and request.method == "GET":
            return httpx.Response(
                200,
                json={"projectroles": [{"role": {"key": "contributor"}, "project": {"id": "0"}}]},
            )
        if path == "/hub/api/rest/users/u9/projectroles" and request.method == "POST":
            raise AssertionError("role already present; should not re-add")
        if path == "/hub/api/rest/users/u9/permanenttokens":
            return httpx.Response(200, json={"token": "perm-x"})
        return httpx.Response(404, text=path)

    client = _hub(handler)
    agent = await client.provision_agent("agent-a", "Agent A")
    await client.aclose()
    assert agent.user_id == "u9"


async def test_error_surfaces():
    client = _hub(lambda req: httpx.Response(403, text="Forbidden"))
    with pytest.raises(AdminError):
        await client.list_users()
    await client.aclose()


async def test_create_token_error_body_is_logged_with_token_redacted(caplog):
    """A create_token call that errors after minting a token (e.g. a flaky
    downstream 5xx, or an API that echoes the request back on failure) must
    still surface the full response body for debugging -- but never the raw
    token value, in the log OR in the raised exception's message."""
    fake_token = "perm-agent-token-should-not-appear-in-logs"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/hub/api/rest/services":
            return httpx.Response(200, json=SERVICES)
        if path == "/hub/api/rest/users/u1/permanenttokens":
            # Simulate a backend that echoes the minted token even on a 5xx
            # (e.g. partial success reported as an error downstream).
            return httpx.Response(
                500,
                json={"error": "propagation failed", "token": fake_token},
            )
        return httpx.Response(404, text=path)

    client = _hub(handler)
    caplog.set_level(logging.ERROR)

    with pytest.raises(AdminError) as exc_info:
        await client.create_token("u1", "mcp-agent-a")
    await client.aclose()

    assert fake_token not in caplog.text
    assert fake_token not in str(exc_info.value)
    # The rest of the body stays visible for debugging.
    assert "propagation failed" in caplog.text
    assert REDACTED in caplog.text
