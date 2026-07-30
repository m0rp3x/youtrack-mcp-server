"""Runtime configuration, read from environment variables.

The MCP client (Claude Code, Claude Desktop, Cursor, …) is responsible for
passing ``YOUTRACK_URL`` and ``YOUTRACK_TOKEN`` in the server's ``env`` block.
Secrets are never read from or written to the repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Resolved YouTrack connection settings."""

    url: str
    token: str


def load_config() -> Config:
    """Build a :class:`Config` from the environment.

    Raises:
        RuntimeError: if ``YOUTRACK_URL`` or ``YOUTRACK_TOKEN`` is missing.
    """
    url = os.environ.get("YOUTRACK_URL", "").strip()
    token = os.environ.get("YOUTRACK_TOKEN", "").strip()
    missing = [name for name, val in (("YOUTRACK_URL", url), ("YOUTRACK_TOKEN", token)) if not val]
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): "
            + ", ".join(missing)
            + ". Set them in your MCP client config (see README) or export them for local runs."
        )
    return Config(url=url, token=token)


@dataclass(frozen=True)
class AdminConfig:
    """Resolved Hub admin settings, used for agent-provisioning tools."""

    url: str
    admin_token: str


def has_admin_token() -> bool:
    """Return True if YOUTRACK_ADMIN_TOKEN is set (non-empty).

    Used at server start-up to decide whether to register the agent-
    provisioning tools (provision_agent / list_agents / revoke_agent) at
    all -- a regular agent running with only a plain YOUTRACK_TOKEN never
    sees them.
    """
    return bool(os.getenv("YOUTRACK_ADMIN_TOKEN", "").strip())


def load_admin_config() -> AdminConfig:
    """Build an AdminConfig from the environment variables.

    Raises:
        RuntimeError: if YOUTRACK_URL or YOUTRACK_ADMIN_TOKEN is missing.

    Only call this once an admin client is actually needed (e.g. inside
    a provisioning tool call) -- most server instances legitimately run
    without an admin token, so do not call this unconditionally at
    import time; use has_admin_token() to decide whether to register
    the provisioning tools at all.
    """
    url = os.getenv("YOUTRACK_URL", "").strip()
    admin_token = os.getenv("YOUTRACK_ADMIN_TOKEN", "").strip()
    missing = [
        name
        for name, val in (("YOUTRACK_URL", url), ("YOUTRACK_ADMIN_TOKEN", admin_token))
        if not val
    ]
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): "
            + ", ".join(missing)
            + ". Set YOUTRACK_ADMIN_TOKEN to an admin permanent token (a Hub "
            "user allowed to create/update users) to enable provision_agent / "
            "list_agents / revoke_agent -- see README."
        )
    return AdminConfig(url=url, admin_token=admin_token)
