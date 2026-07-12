"""Unit tests for the pure formatting helpers (no network)."""

from youtrack_mcp.formatting import (
    format_issue_detail,
    format_issue_line,
    state_of,
)

ISSUE = {
    "idReadable": "DEMO-12",
    "summary": "Fix login redirect",
    "description": "Steps to reproduce...",
    "resolved": None,
    "project": {"shortName": "DEMO", "name": "Demo project"},
    "reporter": {"login": "yura", "fullName": "Юра"},
    "customFields": [
        {"name": "State", "value": {"name": "In Progress"}},
        {"name": "Assignee", "value": {"login": "klod", "fullName": "Клод"}},
        {"name": "Priority", "value": {"name": "Critical"}},
    ],
}


def test_state_from_custom_field():
    assert state_of(ISSUE) == "In Progress"


def test_state_falls_back_to_resolved_flag():
    assert state_of({"resolved": 1730000000000}) == "Resolved"
    assert state_of({"resolved": None}) == "Open"


def test_issue_line_has_id_state_and_assignee():
    line = format_issue_line(ISSUE)
    assert "DEMO-12" in line
    assert "[In Progress]" in line
    assert "Fix login redirect" in line
    assert "Клод" in line  # assignee shown by full name


def test_unassigned_issue():
    line = format_issue_line({"idReadable": "DEMO-1", "summary": "x", "resolved": None})
    assert "unassigned" in line


def test_issue_detail_includes_metadata_and_description():
    detail = format_issue_detail(ISSUE)
    assert "Demo project (DEMO)" in detail
    assert "reporter: yura" in detail
    assert "priority: Critical" in detail
    assert "Steps to reproduce" in detail
