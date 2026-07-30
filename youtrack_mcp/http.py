"""Shared HTTP plumbing used by both REST clients (YouTrack and Hub).

Kept dependency-free of :mod:`youtrack_mcp.client` / :mod:`youtrack_mcp.admin`
so neither client has to import the other just to build request headers.
"""

from __future__ import annotations


def bearer_headers(token: str) -> dict[str, str]:
    """Build the standard JSON+Bearer header set used for every REST call.

    Both :class:`youtrack_mcp.client.YouTrackClient` (YouTrack REST API) and
    :class:`youtrack_mcp.admin.AdminClient` (Hub REST API) authenticate the
    same way — a permanent token as a Bearer credential, JSON in and out.
    """
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
