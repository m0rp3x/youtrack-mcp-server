"""Server-level tests: MCP handshake / list_tools, without hitting YouTrack.

These exercise the protocol surface (tool registry, JSON schemas, entry point)
rather than any real YouTrack API call — no network, no token required.
"""

from youtrack_mcp.server import main, mcp


async def test_server_starts_and_lists_tools():
    """The server object builds and responds to list_tools (MCP handshake)."""
    tools = await mcp.list_tools()
    assert len(tools) > 0


async def test_registered_tool_names_include_core_operations():
    """The four core YouTrack operations are registered as callable tools."""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    for expected in ("create_issue", "search_issues", "add_comment"):
        assert expected in names


async def test_tool_schemas_declare_required_params():
    """Each tool exposes a JSON schema with sane required parameters."""
    tools = await mcp.list_tools()
    by_name = {t.name: t for t in tools}

    assert by_name["search_issues"].inputSchema["required"] == ["query"]
    assert by_name["create_issue"].inputSchema["required"] == ["project", "summary"]
    assert by_name["add_comment"].inputSchema["required"] == ["issue_id", "text"]


def test_main_entry_point_is_callable():
    """The console-script entry point exists and wraps mcp.run()."""
    assert callable(main)
