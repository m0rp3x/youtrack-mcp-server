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
