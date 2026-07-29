"""Config tests: env parsing, admin-token gating, and error messages.

No network involved -- these only exercise `youtrack_mcp.config`.
"""

import pytest

from youtrack_mcp.config import (
    has_admin_token,
    load_admin_config,
    load_config,
)


def _clear(monkeypatch):
    for var in ("YOUTRACK_URL", "YOUTRACK_TOKEN", "YOUTRACK_ADMIN_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def test_load_config_reads_env(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("YOUTRACK_URL", "https://yt.example.com")
    monkeypatch.setenv("YOUTRACK_TOKEN", "perm-token")
    cfg = load_config()
    assert cfg.url == "https://yt.example.com"
    assert cfg.token == "perm-token"


def test_load_config_missing_raises_clear_error(monkeypatch):
    _clear(monkeypatch)
    with pytest.raises(RuntimeError, match="YOUTRACK_URL"):
        load_config()


def test_has_admin_token_false_when_unset(monkeypatch):
    _clear(monkeypatch)
    assert has_admin_token() is False


def test_has_admin_token_false_when_blank(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("YOUTRACK_ADMIN_TOKEN", "   ")
    assert has_admin_token() is False


def test_has_admin_token_true_when_set(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("YOUTRACK_ADMIN_TOKEN", "perm-admin")
    assert has_admin_token() is True


def test_load_admin_config_reads_env(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("YOUTRACK_URL", "https://yt.example.com")
    monkeypatch.setenv("YOUTRACK_ADMIN_TOKEN", "perm-admin")
    cfg = load_admin_config()
    assert cfg.url == "https://yt.example.com"
    assert cfg.admin_token == "perm-admin"


def test_load_admin_config_missing_raises_clear_error_not_crash(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("YOUTRACK_URL", "https://yt.example.com")
    # YOUTRACK_ADMIN_TOKEN intentionally left unset.
    with pytest.raises(RuntimeError, match="YOUTRACK_ADMIN_TOKEN"):
        load_admin_config()
