"""CLI-level tests for the structured license-limit signal (no network).

``AdminClient`` itself is never hit — ``_admin_client`` is monkeypatched to
return a stub whose ``provision_agent`` raises ``LicenseLimitError`` directly,
so these tests only exercise ``admin_cli.main()``'s exception handling.
"""

from __future__ import annotations

import pytest

from youtrack_mcp import admin_cli
from youtrack_mcp.admin import LicenseLimitError


class _StubClient:
    def __init__(self, status: str) -> None:
        self._status = status

    async def provision_agent(self, *args, **kwargs):
        raise LicenseLimitError(self._status, login=args[0], user_id="u-stub")

    async def aclose(self) -> None:
        pass


@pytest.mark.parametrize(
    ("status", "expected_exit_code"),
    [
        ("LICENSE_LIMIT_LIKELY", 2),
        ("ALREADY_BANNED", 3),
    ],
)
def test_create_agent_reports_license_status_structurally(
    monkeypatch, capsys, status, expected_exit_code
):
    monkeypatch.setattr(admin_cli, "_admin_client", lambda: _StubClient(status))
    monkeypatch.setattr(
        "sys.argv", ["youtrack-admin", "create-agent", "agent-x", "--name", "Agent X"]
    )

    with pytest.raises(SystemExit) as excinfo:
        admin_cli.main()

    assert excinfo.value.code == expected_exit_code
    err = capsys.readouterr().err
    assert f"status: {status}" in err  # machine-parseable, not just prose
