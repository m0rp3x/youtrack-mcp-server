"""Admin/provisioning tests using a stubbed Hub transport (no network)."""

import json

import httpx
import pytest

from youtrack_mcp.admin import AdminClient, AdminError, LicenseLimitError

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
            return httpx.Response(
                200,
                json={"id": "u1", "login": "agent-a", "name": "Agent A", "banned": False},
            )
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
    assert agent.banned is False
    assert agent.newly_created is True
    assert ("POST", "/hub/api/rest/users") in calls


async def test_provision_reuses_existing_user_and_skips_present_role():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/hub/api/rest/services":
            return httpx.Response(200, json=SERVICES)
        if path == "/hub/api/rest/users" and request.method == "GET":
            return httpx.Response(
                200,
                json={"users": [{"id": "u9", "login": "agent-a", "banned": False}]},
            )
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
    assert agent.banned is False
    assert agent.newly_created is False


async def test_provision_new_user_banned_raises_license_limit_likely():
    """A brand-new user coming back banned is a likely seat-limit hit.

    No role grant or token mint should be attempted once ``banned`` is seen.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/hub/api/rest/services":
            return httpx.Response(200, json=SERVICES)
        if path == "/hub/api/rest/users" and request.method == "GET":
            return httpx.Response(200, json={"users": []})  # not found -> create
        if path == "/hub/api/rest/users" and request.method == "POST":
            return httpx.Response(
                200,
                json={"id": "u2", "login": "agent-b", "name": "Agent B", "banned": True},
            )
        if "/projectroles" in path or "/permanenttokens" in path:
            raise AssertionError("banned user must not be granted a role or minted a token")
        return httpx.Response(404, text=f"unexpected {path}")

    client = _hub(handler)
    with pytest.raises(LicenseLimitError) as excinfo:
        await client.provision_agent("agent-b", "Agent B")
    await client.aclose()

    assert excinfo.value.status == "LICENSE_LIMIT_LIKELY"
    assert excinfo.value.login == "agent-b"
    assert excinfo.value.user_id == "u2"
    assert isinstance(excinfo.value, AdminError)


async def test_provision_existing_banned_user_raises_already_banned():
    """Re-provisioning a login that is already banned must not retry mutations."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/hub/api/rest/services":
            return httpx.Response(200, json=SERVICES)
        if path == "/hub/api/rest/users" and request.method == "GET":
            return httpx.Response(
                200,
                json={"users": [{"id": "u9", "login": "agent-a", "banned": True}]},
            )
        if path == "/hub/api/rest/users" and request.method == "POST":
            raise AssertionError("should not create an already-existing user")
        if "/projectroles" in path or "/permanenttokens" in path:
            raise AssertionError("banned user must not be granted a role or minted a token")
        return httpx.Response(404, text=f"unexpected {path}")

    client = _hub(handler)
    with pytest.raises(LicenseLimitError) as excinfo:
        await client.provision_agent("agent-a", "Agent A")
    await client.aclose()

    assert excinfo.value.status == "ALREADY_BANNED"
    assert excinfo.value.user_id == "u9"


async def test_error_surfaces():
    client = _hub(lambda req: httpx.Response(403, text="Forbidden"))
    with pytest.raises(AdminError):
        await client.list_users()
    await client.aclose()
