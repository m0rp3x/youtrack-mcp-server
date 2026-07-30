"""Turn YouTrack JSON into compact, LLM-friendly text.

Assignee, State, Priority, … are all *custom fields* in YouTrack, so they arrive
in a generic ``customFields`` list rather than as top-level keys. These helpers
pull the interesting ones out and render one-line and detailed views.
"""

from __future__ import annotations

from typing import Any


def _custom_field(issue: dict[str, Any], name: str) -> Any:
    """Return the raw ``value`` of a named custom field, or ``None``."""
    for field in issue.get("customFields", []):
        if field.get("name") == name:
            return field.get("value")
    return None


def _display(value: Any) -> str | None:
    """Render a custom-field value (dict / list / scalar) as a short string."""
    if value is None:
        return None
    if isinstance(value, list):
        parts = [p for p in (_display(v) for v in value) if p]
        return ", ".join(parts) or None
    if isinstance(value, dict):
        for key in ("name", "fullName", "login", "presentation", "text"):
            if value.get(key):
                return str(value[key])
        return None
    return str(value)


def state_of(issue: dict[str, Any]) -> str:
    """Best-effort human state: the ``State`` field, else resolved/open."""
    return _display(_custom_field(issue, "State")) or (
        "Resolved" if issue.get("resolved") else "Open"
    )


def format_issue_line(issue: dict[str, Any]) -> str:
    """One-line summary: ``DEMO-12 [Open] Fix login · assignee: klod``."""
    assignee = _display(_custom_field(issue, "Assignee")) or "unassigned"
    return (
        f"{issue.get('idReadable', '?')} "
        f"[{state_of(issue)}] "
        f"{issue.get('summary', '(no summary)')} "
        f"· assignee: {assignee}"
    )


def format_issue_detail(issue: dict[str, Any]) -> str:
    """Multi-line view with metadata and description."""
    lines = [format_issue_line(issue)]
    project = issue.get("project") or {}
    if project:
        lines.append(f"project: {project.get('name')} ({project.get('shortName')})")
    reporter = issue.get("reporter") or {}
    if reporter.get("login"):
        lines.append(f"reporter: {reporter['login']}")
    for name in ("Priority", "Type", "Due Date"):
        value = _display(_custom_field(issue, name))
        if value:
            lines.append(f"{name.lower()}: {value}")
    description = (issue.get("description") or "").strip()
    if description:
        lines.append("")
        lines.append(description)
    return "\n".join(lines)


def issue_url(base_url: str, issue: dict[str, Any]) -> str:
    """Build the browser URL for an issue, e.g. ``https://yt.example.com/issue/DEMO-42``.

    Args:
        base_url: Instance base URL (``YOUTRACK_URL``), with or without a
            trailing slash.
        issue: Issue JSON as returned by the YouTrack API; must contain
            ``idReadable``.
    """
    return f"{base_url.rstrip('/')}/issue/{issue.get('idReadable', '')}"


def format_comment(comment: dict[str, Any]) -> str:
    """Render a created comment for confirmation output."""
    author = (comment.get("author") or {}).get("login", "?")
    return f"comment added by {author}: {comment.get('text', '').strip()}"
