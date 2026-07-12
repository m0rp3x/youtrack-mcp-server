"""Provisioning helpers: create YouTrack accounts and tokens for agents.

This talks to the **Hub** REST API (``/hub/api/rest``) and therefore needs an
*admin* permanent token (a token owned by a user with the "Create User" /
"Update User" permissions), supplied as ``YOUTRACK_ADMIN_TOKEN``.

Typical use is one account per agent so that activity, assignments and "my
tasks" are attributed per agent. Each agent then runs its own MCP server
instance with its own ``YOUTRACK_TOKEN`` (see :mod:`youtrack_mcp.server`).

Note on permissions: after a role is granted, YouTrack takes a few seconds to
propagate it, so an agent's very first write may return 403 and succeed on
retry. The MCP tools surface the error; a retry resolves it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_TIMEOUT = 30.0
GLOBAL_PROJECT_ID = "0"

#: Friendly role name -> YouTrack built-in role key.
ROLE_KEYS = {
    "contributor": "contributor",
    "observer": "observer",
    "project-admin": "project-admin",
    "admin": "system-admin",
    "system-admin": "system-admin",
}

#: Services a token is scoped to. The permission model lives under the Hub
#: ("YouTrack Administration") service, so both are required for a token to
#: actually carry the user's YouTrack permissions.
TOKEN_SERVICE_NAMES = ("YouTrack", "YouTrack Administration")


@dataclass
class Agent:
    """Result of provisioning an agent account."""

    login: str
    name: str
    user_id: str
    token: str


class AdminError(RuntimeError):
    """Raised when a Hub admin API call fails."""


class AdminClient:
    """Small Hub REST client for user/role/token administration."""

    def __init__(
        self,
        base_url: str,
        admin_token: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {admin_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._service_ids: list[str] | None = None
        self._role_ids: dict[str, str] | None = None

    @property
    def hub_url(self) -> str:
        """Hub REST root, e.g. ``https://yt.example.com/hub/api/rest``."""
        return f"{self._base_url}/hub/api/rest"

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.hub_url + "/",
                headers=self._headers,
                timeout=self._timeout,
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, path: str, **kw: Any) -> Any:
        resp = await self._http().request(method, path, **kw)
        if resp.status_code >= 400:
            raise AdminError(f"{resp.status_code} {method} /{path}: {resp.text[:500]}")
        return resp.json() if resp.content else None

    # -- lookups -------------------------------------------------------------

    async def _token_service_ids(self) -> list[str]:
        if self._service_ids is None:
            data = await self._request(
                "GET", "services", params={"fields": "id,name", "$top": 100}
            )
            by_name = {s.get("name"): s.get("id") for s in data.get("services", data)}
            ids = [by_name[n] for n in TOKEN_SERVICE_NAMES if n in by_name]
            self._service_ids = ids or list(by_name.values())
        return self._service_ids

    async def _role_id(self, role_key: str) -> str:
        if self._role_ids is None:
            data = await self._request(
                "GET", "roles", params={"fields": "id,key", "$top": 100}
            )
            self._role_ids = {r["key"]: r["id"] for r in data.get("roles", data)}
        if role_key not in self._role_ids:
            raise AdminError(f"Unknown role key '{role_key}'. Available: {sorted(self._role_ids)}")
        return self._role_ids[role_key]

    async def _all_users(self) -> list[dict[str, Any]]:
        data = await self._request(
            "GET", "users", params={"fields": "id,login,name,banned", "$top": 1000}
        )
        return data.get("users", data)

    async def find_user(self, login: str) -> dict[str, Any] | None:
        """Return the user with an exact ``login``, or ``None``.

        Matching is done client-side: Hub's free-text ``query`` treats ``-`` as
        negation, which silently breaks logins like ``agent-alpha``.
        """
        for user in await self._all_users():
            if user.get("login") == login:
                return user
        return None

    async def global_roles(self, user_id: str) -> list[str]:
        """Return the names of the user's global (all-projects) roles."""
        data = await self._request(
            "GET",
            f"users/{user_id}/projectroles",
            params={"fields": "role(name),project(id)", "$top": 100},
        )
        return [
            (pr.get("role") or {}).get("name", "?")
            for pr in data.get("projectroles", data)
            if (pr.get("project") or {}).get("id") == GLOBAL_PROJECT_ID
        ]

    async def list_users(self) -> list[dict[str, Any]]:
        """List users, each annotated with a ``roles`` list of global role names.

        Roles are fetched per user because Hub does not expand ``projectroles``
        on the collection endpoint.
        """
        users = await self._all_users()
        for user in users:
            user["roles"] = await self.global_roles(user["id"])
        return users

    # -- mutations -----------------------------------------------------------

    async def create_user(
        self, login: str, name: str, email: str | None = None
    ) -> dict[str, Any]:
        """Create a Hub/YouTrack user (no password; token-only agent)."""
        body: dict[str, Any] = {"login": login, "name": name}
        if email:
            body["profile"] = {
                "email": {"type": "EmailUserProfileAttribute", "email": email, "verified": True}
            }
        return await self._request(
            "POST", "users", params={"fields": "id,login,name"}, json=body
        )

    async def ensure_global_role(self, user_id: str, role_key: str) -> None:
        """Grant a global (all-projects) role if the user doesn't have it yet."""
        existing = await self._request(
            "GET",
            f"users/{user_id}/projectroles",
            params={"fields": "role(key),project(id)", "$top": 100},
        )
        for pr in existing.get("projectroles", existing):
            if (pr.get("role") or {}).get("key") == role_key and (
                pr.get("project") or {}
            ).get("id") == GLOBAL_PROJECT_ID:
                return
        role_id = await self._role_id(role_key)
        await self._request(
            "POST",
            f"users/{user_id}/projectroles",
            params={"fields": "id"},
            json={"role": {"id": role_id}, "project": {"id": GLOBAL_PROJECT_ID}},
        )

    async def create_token(self, user_id: str, name: str) -> str:
        """Create a permanent token for a user and return its value."""
        scope = [{"id": sid} for sid in await self._token_service_ids()]
        data = await self._request(
            "POST",
            f"users/{user_id}/permanenttokens",
            params={"fields": "token"},
            json={"name": name, "scope": scope},
        )
        return data["token"]

    async def ban_user(self, user_id: str) -> None:
        """Ban (disable) a user without deleting their history."""
        await self._request(
            "POST", f"users/{user_id}", params={"fields": "id"}, json={"banned": True}
        )

    async def delete_user(self, user_id: str) -> None:
        """Permanently delete a user."""
        await self._request("DELETE", f"users/{user_id}")

    # -- orchestration -------------------------------------------------------

    async def provision_agent(
        self, login: str, name: str, *, role: str = "contributor", email: str | None = None
    ) -> Agent:
        """Create (or reuse) an agent account, grant a role, mint a token.

        Args:
            login: Unique login for the agent, e.g. ``agent-alpha``.
            name: Display name.
            role: Friendly role name (see :data:`ROLE_KEYS`); default ``contributor``.
            email: Optional email (placeholder is fine for token-only agents).
        """
        role_key = ROLE_KEYS.get(role, role)
        user = await self.find_user(login)
        if user is None:
            user = await self.create_user(login, name, email)
        user_id = user["id"]
        await self.ensure_global_role(user_id, role_key)
        token = await self.create_token(user_id, name=f"mcp-{login}")
        return Agent(login=login, name=name, user_id=user_id, token=token)
