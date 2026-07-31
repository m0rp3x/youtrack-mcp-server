"""Contract E2E test: full agent -> YouTrack cycle through the public MCP tools.

Scope decided by PM on #3627: a live external sandbox SaaS organization was
ruled out as a CI dependency -- for a thin REST wrapper like this one, a real
third-party instance in CI means a long-lived token stored in CI plus a
flaky, network-dependent suite, for very little extra confidence. What
actually matters is whether the MCP tool chain builds the right HTTP requests
and correctly parses YouTrack's responses across a full
create -> transition -> comment -> re-fetch cycle -- and a mocked httpx
transport proves exactly that, with zero network and nothing extra to
configure.

``test_full_cycle_contract_against_mocked_transport`` always runs in CI: it
drives create_issue -> run_command -> add_comment -> get_issue through a real
YouTrackClient wired to httpx.MockTransport, asserting method/path/request
body on the way out and correct response parsing on the way back at every
step.

``test_full_cycle_live_against_real_instance`` is the optional live mode: it
only runs if YOUTRACK_E2E_URL and YOUTRACK_E2E_TOKEN are set, and is skipped
otherwise. Neither this repo nor its CI sets those variables today -- wiring
a real instance up is a separate, later concern.
"""

from __future__ import annotations

import json
import os
import uuid

import httpx
import pytest

import youtrack_mcp.server as server
from youtrack_mcp.client import YouTrackClient

PROJECT = "DEMO"
RESOLVE_COMMAND = "State Fixed"
ISSUE_ID = "DEMO-101"


async def test_full_cycle_contract_against_mocked_transport(monkeypatch):
    """No network, nothing to configure: proves the tool chain forms correct
    requests and parses YouTrack's responses at every step of the cycle."""
    summary = f"E2E contract {uuid.uuid4()}"
    comment_text = "E2E contract check-in comment"

    def handler(request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path

        if method == "POST" and path == "/api/issues":
            body = json.loads(request.content)
            assert body == {
                "project": {"shortName": PROJECT},
                "summary": summary,
                "description": "E2E contract check-in",
            }
            return httpx.Response(
                200,
                json={
                    "idReadable": ISSUE_ID,
                    "summary": summary,
                    "resolved": None,
                    "project": {"shortName": PROJECT, "name": "Demo"},
                    "reporter": {"login": "e2e-bot"},
                    "customFields": [{"name": "State", "value": {"name": "Open"}}],
                },
            )

        if method == "POST" and path == "/api/commands":
            body = json.loads(request.content)
            assert body == {
                "query": RESOLVE_COMMAND,
                "issues": [{"idReadable": ISSUE_ID}],
            }
            return httpx.Response(200, json={"issues": [{"idReadable": ISSUE_ID}]})

        if method == "POST" and path == f"/api/issues/{ISSUE_ID}/comments":
            body = json.loads(request.content)
            assert body == {"text": comment_text}
            return httpx.Response(
                200,
                json={
                    "id": "c-1",
                    "text": comment_text,
                    "created": 1_700_000_000_000,
                    "author": {"login": "e2e-bot", "fullName": "E2E Bot"},
                },
            )

        if method == "GET" and path == f"/api/issues/{ISSUE_ID}":
            return httpx.Response(
                200,
                json={
                    "idReadable": ISSUE_ID,
                    "summary": summary,
                    "resolved": 1_700_000_100_000,
                    "project": {"shortName": PROJECT, "name": "Demo"},
                    "reporter": {"login": "e2e-bot"},
                    "customFields": [{"name": "State", "value": {"name": "Fixed"}}],
                },
            )

        raise AssertionError(f"unexpected request: {method} {path}")

    client = YouTrackClient(
        "https://e2e.example.com", "perm-test", transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(server, "_client", client)

    try:
        created = await server.create_issue(PROJECT, summary, "E2E contract check-in")
        commanded = await server.run_command([ISSUE_ID], RESOLVE_COMMAND)
        commented = await server.add_comment(ISSUE_ID, comment_text)
        detail = await server.get_issue(ISSUE_ID)
    finally:
        monkeypatch.setattr(server, "_client", None)
        await client.aclose()

    assert created.startswith(f"Created {ISSUE_ID} [Open] {summary}")
    assert f"url: https://e2e.example.com/issue/{ISSUE_ID}" in created

    assert commanded == f"Applied '{RESOLVE_COMMAND}' to {ISSUE_ID}."

    assert commented == f"{ISSUE_ID}: comment added by e2e-bot: {comment_text}"

    assert detail.startswith(f"{ISSUE_ID} [Fixed] {summary}")


def _live_mode_configured() -> bool:
    """True once someone has explicitly pointed the suite at a real instance."""
    getenv = os.getenv
    return bool(getenv("YOUTRACK_E2E_URL")) and bool(getenv("YOUTRACK_E2E_TOKEN"))


@pytest.mark.skipif(
    not _live_mode_configured(),
    reason=(
        "live E2E only runs when YOUTRACK_E2E_URL/YOUTRACK_E2E_TOKEN are set; "
        "unset in this repo's CI today, so this is skipped by default (see #3627)"
    ),
)
async def test_full_cycle_live_against_real_instance(monkeypatch):
    """Optional: the same scenario against a real YouTrack instance, when one
    is explicitly configured via YOUTRACK_E2E_URL/YOUTRACK_E2E_TOKEN. Not part
    of the default CI run -- see module docstring."""
    getenv = os.getenv
    project = getenv("YOUTRACK_E2E_PROJECT", PROJECT)
    resolve_command = getenv("YOUTRACK_E2E_RESOLVE_COMMAND", RESOLVE_COMMAND)
    summary = f"E2E live contract {uuid.uuid4()}"
    comment_text = "E2E live contract check-in comment"

    client = YouTrackClient(getenv("YOUTRACK_E2E_URL"), getenv("YOUTRACK_E2E_TOKEN"))
    monkeypatch.setattr(server, "_client", client)

    try:
        created = await server.create_issue(project, summary, "E2E live contract check-in")
        issue_id = created.removeprefix("Created ").split(" ", 1)[0]

        commanded = await server.run_command([issue_id], resolve_command)
        assert commanded == f"Applied '{resolve_command}' to {issue_id}."

        commented = await server.add_comment(issue_id, comment_text)
        assert comment_text in commented

        detail = await server.get_issue(issue_id)
        assert issue_id in detail
    finally:
        monkeypatch.setattr(server, "_client", None)
        await client.aclose()
