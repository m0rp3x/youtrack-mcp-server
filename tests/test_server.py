"""Server-level tests: MCP handshake / list_tools, without hitting YouTrack.

These exercise the protocol surface (tool registry, JSON schemas, entry point)
rather than any real YouTrack API call — no network, no token required.
"""

from youtrack_mcp.server import main, mcp

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
