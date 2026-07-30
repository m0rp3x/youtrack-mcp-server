"""The MCP server: exposes YouTrack operations as tools over stdio.

Run directly (``youtrack-mcp`` / ``python -m youtrack_mcp.server``) or, more
usually, let your MCP client launch it. Configuration comes from the environment
(:mod:`youtrack_mcp.config`).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .admin import AdminClient
from .client import YouTrackClient
from .config import has_admin_token, load_admin_config, load_config
from .formatting import format_comment, format_issue_detail, format_issue_line, issue_url

mcp = FastMCP("youtrack")

_client: YouTrackClient | None = None
_admin_client: AdminClient | None = None


def _client_or_init() -> YouTrackClient:
    """Lazily build the shared client on first use (fails fast if misconfigured)."""
    global _client
    if _client is None:
        cfg = load_config()
        _client = YouTrackClient(cfg.url, cfg.token)
    return _client


def _admin_client_or_init() -> AdminClient:
    """Lazily build the shared Hub admin client on first use.

    Only called from inside the provisioning tools below, which are only
    registered when :func:`has_admin_token` is true -- so by the time this
    runs, ``load_admin_config`` succeeding is expected, not a fresh check.
    """
    global _admin_client
    if _admin_client is None:
        cfg = load_admin_config()
        _admin_client = AdminClient(cfg.url, cfg.admin_token)
    return _admin_client


@mcp.tool()
async def whoami() -> str:
    """Show which YouTrack account the configured token belongs to.

    Useful as a connectivity check before doing anything else.
    """
    me = await _client_or_init().me()
    return f"{me.get('login')} ({me.get('fullName')}) <{me.get('email') or 'no email'}>"


@mcp.tool()
async def my_issues(query: str = "", limit: int = 30) -> str:
    """List issues assigned to the token owner ("my tasks").

    Args:
        query: Optional extra YouTrack search terms to AND with ``for: me``,
            e.g. ``#Unresolved``, ``State: Open``, ``project: DEMO``.
        limit: Maximum number of issues to return.
    """
    full_query = f"for: me {query}".strip()
    issues = await _client_or_init().search_issues(full_query, top=limit)
    if not issues:
        return "No issues found."
    return "\n".join(format_issue_line(i) for i in issues)


@mcp.tool()
async def search_issues(query: str, limit: int = 30) -> str:
    """Search issues with a raw YouTrack query.

    Args:
        query: A YouTrack search query, e.g. ``project: DEMO #Unresolved Priority: Critical``.
        limit: Maximum number of issues to return.
    """
    issues = await _client_or_init().search_issues(query, top=limit)
    if not issues:
        return "No issues found."
    return "\n".join(format_issue_line(i) for i in issues)


@mcp.tool()
async def get_issue(issue_id: str) -> str:
    """Show full details of one issue.

    Args:
        issue_id: Readable id such as ``DEMO-12`` (internal ids also work).
    """
    issue = await _client_or_init().get_issue(issue_id)
    return format_issue_detail(issue)


@mcp.tool()
async def create_issue(project: str, summary: str, description: str = "") -> str:
    """Create a new issue.

    Args:
        project: Short name of the target project, e.g. ``DEMO``.
        summary: Issue title.
        description: Optional Markdown body.
    """
    client = _client_or_init()
    issue = await client.create_issue(project, summary, description or None)
    url = issue_url(client.base_url, issue)
    return "Created " + format_issue_line(issue) + f"\nurl: {url}"


@mcp.tool()
async def run_command(issue_ids: list[str], command: str, comment: str = "") -> str:
    """Apply a YouTrack command to one or more issues.

    Commands are the same mini-language used in the YouTrack UI, e.g.
    ``State Done`` (mark resolved), ``for me`` (assign to yourself),
    ``Priority Critical``, ``add Board Sprint 1``, ``tag urgent``.

    Args:
        issue_ids: Readable ids to act on, e.g. ``["DEMO-12", "DEMO-13"]``.
        command: The command to apply.
        comment: Optional comment to post alongside the command.
    """
    await _client_or_init().apply_command(command, issue_ids, comment or None)
    target = ", ".join(issue_ids)
    return f"Applied '{command}' to {target}."


@mcp.tool()
async def add_comment(issue_id: str, text: str) -> str:
    """Add a comment to an issue.

    Args:
        issue_id: Readable id such as ``DEMO-12``.
        text: Comment body (Markdown).
    """
    comment = await _client_or_init().add_comment(issue_id, text)
    return f"{issue_id}: " + format_comment(comment)


@mcp.tool()
async def list_projects(include_archived: bool = False) -> str:
    """List projects visible to the token owner (short name and name)."""
    projects = await _client_or_init().list_projects(include_archived=include_archived)
    if not projects:
        return "No projects visible."
    return "\n".join(f"{p.get('shortName')} — {p.get('name')}" for p in projects)


if has_admin_token():
    # Agent-provisioning tools. Registered only when YOUTRACK_ADMIN_TOKEN is
    # set, so a regular agent running with just a plain YOUTRACK_TOKEN never
    # even sees these in its tool list — only the orchestrator's own server
    # instance (holding the admin token) does.

    @mcp.tool()
    async def provision_agent(login: str, name: str) -> dict[str, str]:
        """Create (or reuse) a YouTrack account + token for an agent.

        Idempotent: calling this again with the same ``login`` reuses the
        existing account and role instead of creating a duplicate user.

        The returned token is shown to the caller exactly once, here, and is
        never logged or persisted by this server — capture it immediately
        and hand it to the agent as its own ``YOUTRACK_TOKEN``.

        Args:
            login: Unique login for the agent, e.g. ``agent-alpha``.
            name: Display name for the agent's account.
        """
        agent = await _admin_client_or_init().provision_agent(login, name)
        return {"login": agent.login, "token": agent.token}

    @mcp.tool()
    async def list_agents() -> str:
        """List provisioned agent accounts and their global roles."""
        users = await _admin_client_or_init().list_users()
        if not users:
            return "No agents provisioned."
        lines = []
        for user in sorted(users, key=lambda u: u.get("login", "")):
            roles = ", ".join(user.get("roles", [])) or "(none)"
            banned = " [banned]" if user.get("banned") else ""
            lines.append(f"{user.get('login')} ({user.get('name', '')}) roles: {roles}{banned}")
        return "\n".join(lines)

    @mcp.tool()
    async def revoke_agent(login: str) -> str:
        """Ban an agent's account, disabling it without deleting its history.

        Args:
            login: The agent's login, e.g. ``agent-alpha``.
        """
        client = _admin_client_or_init()
        user = await client.find_user(login)
        if user is None:
            return f"No agent with login '{login}'."
        await client.ban_user(user["id"])
        return f"Banned '{login}'."


def main() -> None:
    """Console-script entry point: serve MCP over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
