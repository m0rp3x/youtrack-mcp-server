"""Unit tests for youtrack_mcp.redact — the value-masking helper used before
error response bodies are logged."""

import json

from youtrack_mcp.redact import REDACTED, redact_json, redact_text

FAKE_TOKEN = "perm-fake-value-not-real"


def test_redact_json_masks_top_level_keys():
    data = {"token": FAKE_TOKEN, "name": "agent-alpha"}
    assert redact_json(data) == {"token": REDACTED, "name": "agent-alpha"}


def test_redact_json_masks_nested_keys():
    data = {"user": {"login": "agent-alpha", "access_token": FAKE_TOKEN}, "ok": True}
    result = redact_json(data)
    assert result["user"]["access_token"] == REDACTED
    assert result["user"]["login"] == "agent-alpha"
    assert result["ok"] is True


def test_redact_json_masks_values_inside_lists():
    data = {"tokens": [{"token": FAKE_TOKEN + "-1"}, {"token": FAKE_TOKEN + "-2"}]}
    result = redact_json(data)
    assert all(t["token"] == REDACTED for t in result["tokens"])


def test_redact_json_is_case_insensitive_on_key_names():
    data = {"Token": FAKE_TOKEN, "PASSWORD": "does-not-matter", "Api_Key": "k-1"}
    result = redact_json(data)
    assert set(result.values()) == {REDACTED}


def test_redact_text_masks_json_body_and_preserves_structure():
    body = json.dumps({"error": "conflict", "token": FAKE_TOKEN})
    out = redact_text(body)
    assert FAKE_TOKEN not in out
    assert "conflict" in out  # non-masked fields stay visible for debugging
    assert REDACTED in out


def test_redact_text_falls_back_to_regex_for_non_json_body():
    body = f'Forbidden: token="{FAKE_TOKEN}" scope invalid'
    out = redact_text(body)
    assert FAKE_TOKEN not in out
    assert "Forbidden" in out
    assert "scope invalid" in out


def test_redact_text_leaves_plain_text_without_masked_fields_untouched():
    body = "Forbidden: Create Comment"
    assert redact_text(body) == body
