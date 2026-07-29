"""Tests for the MCP-level admin tools (provision_agent / list_agents /
revoke_agent) wired up in server.py.

Two things are peculiar to this module and drive the test shape:

* Whether the admin tools are registered at all is decided once, at import
  time, by ``if has_admin_token(): ...``. To exercise both branches we
  reimport the module with ``importlib.reload`` after toggling
  ``YOUTRACK_ADMIN_TOKEN`` -- that's the only way to re-run module-level code.
* The tools talk to the Hub over real httpx by default. We never want a real
  network call here, so tests monkeypatch ``_admin_client_or_init`` to return
  a stub instead of touching AdminClient/httpx at all.
"""

import importlib
import logging
from types import SimpleNamespace

import pytest

import youtrack_mcp.server as server


def _clear_env(monkeypatch):
    for var in ("YOUTRACK_URL", "YOUTRACK_TOKEN", "YOUTRACK_ADMIN_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def _reload_server():
    """Re-run server.py's module body, including the admin-tools `if` gate."""
    return importlib.reload(server)


@pytest.fixture(autouse=True)
def _restore_no_admin_server(monkeypatch):
    """Every test starts and ends with the module reloaded in its default
    (no admin token) shape, so ordering between test files can't leak a
    stale set of registered tools."""
    yield
    _clear_env(monkeypatch)
    _reload_server()


def _tool_names(mod):
    return {t.name for t in mod.mcp._tool_manager.list_tools()}


class _FakeAdminClient:
    def __init__(self):
        self.calls = []

    async def provision_agent(self, login, name):
        self.calls.append(("provision_agent", login, name))
        return SimpleNamespace(login=login, name=name, user_id="u1", token="perm-secret-token")

    async def list_users(self):
        return [
            {"login": "agent-a", "name": "Agent A", "roles": ["contributor"], "banned": False},
            {"login": "agent-b", "name": "Agent B", "roles": [], "banned": True},
        ]

    async def find_user(self, login):
        if login == "agent-a":
            return {"id": "u1", "login": "agent-a"}
        return None

    async def ban_user(self, user_id):
        self.calls.append(("ban_user", user_id))


def test_admin_tools_absent_without_token(monkeypatch):
    _clear_env(monkeypatch)
    mod = _reload_server()

    names = _tool_names(mod)
    assert names.isdisjoint({"provision_agent", "list_agents", "revoke_agent"})
    # regular tools are unaffected
    assert "whoami" in names
    assert "my_issues" in names


def test_admin_tools_present_with_token(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("YOUTRACK_ADMIN_TOKEN", "perm-admin")
    mod = _reload_server()

    names = _tool_names(mod)
    assert {"provision_agent", "list_agents", "revoke_agent"} <= names


async def test_provision_agent_delegates_and_returns_token(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("YOUTRACK_ADMIN_TOKEN", "perm-admin")
    mod = _reload_server()
    fake = _FakeAdminClient()
    monkeypatch.setattr(mod, "_admin_client_or_init", lambda: fake)

    tool = mod.mcp._tool_manager.get_tool("provision_agent")
    result = await tool.fn(login="agent-a", name="Agent A")

    assert result == {"login": "agent-a", "token": "perm-secret-token"}
    assert fake.calls == [("provision_agent", "agent-a", "Agent A")]


async def test_provision_agent_token_is_never_logged(monkeypatch, caplog):
    _clear_env(monkeypatch)
    monkeypatch.setenv("YOUTRACK_ADMIN_TOKEN", "perm-admin")
    mod = _reload_server()
    fake = _FakeAdminClient()
    monkeypatch.setattr(mod, "_admin_client_or_init", lambda: fake)
    caplog.set_level(logging.DEBUG)

    tool = mod.mcp._tool_manager.get_tool("provision_agent")
    await tool.fn(login="agent-a", name="Agent A")

    assert "perm-secret-token" not in caplog.text


async def test_list_agents_formats_users_and_flags_banned(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("YOUTRACK_ADMIN_TOKEN", "perm-admin")
    mod = _reload_server()
    fake = _FakeAdminClient()
    monkeypatch.setattr(mod, "_admin_client_or_init", lambda: fake)

    tool = mod.mcp._tool_manager.get_tool("list_agents")
    result = await tool.fn()

    assert "agent-a" in result
    assert "contributor" in result
    assert "agent-b" in result
    assert "[banned]" in result


async def test_revoke_agent_bans_known_login(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("YOUTRACK_ADMIN_TOKEN", "perm-admin")
    mod = _reload_server()
    fake = _FakeAdminClient()
    monkeypatch.setattr(mod, "_admin_client_or_init", lambda: fake)

    tool = mod.mcp._tool_manager.get_tool("revoke_agent")
    result = await tool.fn(login="agent-a")

    assert fake.calls == [("ban_user", "u1")]
    assert "Banned" in result
    assert "agent-a" in result


async def test_revoke_agent_reports_unknown_login_without_error(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("YOUTRACK_ADMIN_TOKEN", "perm-admin")
    mod = _reload_server()
    fake = _FakeAdminClient()
    monkeypatch.setattr(mod, "_admin_client_or_init", lambda: fake)

    tool = mod.mcp._tool_manager.get_tool("revoke_agent")
    result = await tool.fn(login="ghost")

    assert fake.calls == []
    assert "ghost" in result
