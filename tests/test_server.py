"""Server-level tests for MCP tool wiring (no real network).

Includes both YouTrack-tool-behavior tests (create_issue/list_projects, using
a mocked HTTP transport) and MCP handshake/list_tools protocol-surface tests
(tool registry, JSON schemas, entry point — no network, no token required).
"""

import httpx

import youtrack_mcp.server as server
from youtrack_mcp.client import YouTrackClient
from youtrack_mcp.server import main, mcp


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


async def test_list_projects_reports_short_name_and_hides_archived(monkeypatch):
    """list_projects surfaces each project's shortName and, by default, drops
    archived projects (the filtering itself is client-level; here we check the
    tool wires it through and the text output actually contains shortName)."""
    monkeypatch.setenv("YOUTRACK_URL", "https://yt.example.com/")
    monkeypatch.setenv("YOUTRACK_TOKEN", "perm-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"shortName": "DEMO", "name": "Demo project", "archived": False},
                {"shortName": "OLD", "name": "Retired project", "archived": True},
            ],
        )

    fake_client = YouTrackClient(
        "https://yt.example.com/", "perm-test", transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(server, "_client", fake_client)

    try:
        result = await server.list_projects()
    finally:
        monkeypatch.setattr(server, "_client", None)
        await fake_client.aclose()

    assert "DEMO" in result
    assert "OLD" not in result


async def test_list_projects_include_archived_true_shows_all(monkeypatch):
    monkeypatch.setenv("YOUTRACK_URL", "https://yt.example.com/")
    monkeypatch.setenv("YOUTRACK_TOKEN", "perm-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"shortName": "DEMO", "name": "Demo project", "archived": False},
                {"shortName": "OLD", "name": "Retired project", "archived": True},
            ],
        )

    fake_client = YouTrackClient(
        "https://yt.example.com/", "perm-test", transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(server, "_client", fake_client)

    try:
        result = await server.list_projects(include_archived=True)
    finally:
        monkeypatch.setattr(server, "_client", None)
        await fake_client.aclose()

    assert "DEMO" in result
    assert "OLD" in result


# The full set of real (non-stub) tools registered on the running server, as
# required by the task acceptance criteria.
EXPECTED_TOOL_NAMES = {
    "whoami",
    "my_issues",
    "search_issues",
    "get_issue",
    "create_issue",
    "run_command",
    "add_comment",
    "list_projects",
}

# Expected "required" parameters per tool JSON schema (derived from the
# non-defaulted arguments of each tool function in youtrack_mcp/server.py).
EXPECTED_REQUIRED_PARAMS = {
    "whoami": [],
    "my_issues": [],
    "search_issues": ["query"],
    "get_issue": ["issue_id"],
    "create_issue": ["project", "summary"],
    "run_command": ["issue_ids", "command"],
    "add_comment": ["issue_id", "text"],
    "list_projects": [],
}


async def test_server_starts_and_lists_tools():
    """The server object builds and responds to list_tools (MCP handshake)."""
    tools = await mcp.list_tools()
    assert len(tools) > 0


async def test_registered_tool_names_match_real_operations():
    """Exactly the real YouTrack operations are registered as callable tools
    (no stubs, no leftovers, no missing tools)."""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOL_NAMES


async def test_tool_schemas_declare_expected_required_params():
    """Each real tool exposes a JSON schema with the correct required params."""
    tools = await mcp.list_tools()
    by_name = {t.name: t for t in tools}

    for tool_name, expected_required in EXPECTED_REQUIRED_PARAMS.items():
        schema = by_name[tool_name].inputSchema
        assert schema["type"] == "object"
        assert sorted(schema.get("required", [])) == sorted(expected_required), (
            f"{tool_name}: expected required={expected_required!r}, "
            f"got {schema.get('required')!r}"
        )


async def test_tool_schemas_declare_all_parameters_with_types():
    """Every declared parameter (required or optional) has a JSON schema type,
    so MCP clients can build correct call forms."""
    tools = await mcp.list_tools()
    by_name = {t.name: t for t in tools}

    expected_properties = {
        "whoami": set(),
        "my_issues": {"query", "limit"},
        "search_issues": {"query", "limit"},
        "get_issue": {"issue_id"},
        "create_issue": {"project", "summary", "description"},
        "run_command": {"issue_ids", "command", "comment"},
        "add_comment": {"issue_id", "text"},
        "list_projects": {"include_archived"},
    }

    for tool_name, expected_props in expected_properties.items():
        schema = by_name[tool_name].inputSchema
        properties = schema.get("properties", {})
        assert set(properties) == expected_props
        for prop_name, prop_schema in properties.items():
            assert "type" in prop_schema, f"{tool_name}.{prop_name} missing a type"


def test_main_entry_point_is_callable():
    """The console-script entry point exists and wraps mcp.run()."""
    assert callable(main)
