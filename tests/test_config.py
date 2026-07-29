"""Config tests: the YouTrack token/url must come from the environment only."""

from __future__ import annotations

import pytest

from youtrack_mcp.config import load_config


def test_load_config_reads_from_environment(monkeypatch):
    monkeypatch.setenv("YOUTRACK_URL", "https://yt.example.com")
    monkeypatch.setenv("YOUTRACK_TOKEN", "perm-secret")

    cfg = load_config()

    assert cfg.url == "https://yt.example.com"
    assert cfg.token == "perm-secret"


def test_load_config_missing_vars_raises_clear_error(monkeypatch):
    monkeypatch.delenv("YOUTRACK_URL", raising=False)
    monkeypatch.delenv("YOUTRACK_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="YOUTRACK_URL") as exc_info:
        load_config()

    assert "YOUTRACK_TOKEN" in str(exc_info.value)


def test_load_config_missing_token_only(monkeypatch):
    monkeypatch.setenv("YOUTRACK_URL", "https://yt.example.com")
    monkeypatch.delenv("YOUTRACK_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="YOUTRACK_TOKEN"):
        load_config()
