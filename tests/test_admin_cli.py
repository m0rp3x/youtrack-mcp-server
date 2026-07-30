"""CLI-level test for the license-limit signal (no network).

``AdminClient`` itself is never hit -- ``_admin_client`` is monkeypatched to
return a stub whose ``provision_agent`` raises ``LicenseLimitError`` directly,
so this only exercises ``admin_cli.main()``'s existing ``except AdminError``
handling: ``LicenseLimitError`` is a subclass of ``AdminError``, so no new
exception handling was added -- the CLI already turns any ``AdminError`` into
a non-zero exit via ``sys.exit(f"error: {exc}")``.
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


@pytest.mark.parametrize("status", ["LICENSE_LIMIT_LIKELY", "ALREADY_BANNED"])
def test_create_agent_exits_nonzero_on_license_limit_error(monkeypatch, status):
    monkeypatch.setattr(admin_cli, "_admin_client", lambda: _StubClient(status))
    monkeypatch.setattr(
        "sys.argv", ["youtrack-admin", "create-agent", "agent-x", "--name", "Agent X"]
    )

    with pytest.raises(SystemExit) as excinfo:
        admin_cli.main()

    # sys.exit() was called with a non-empty string message (truthy / != 0),
    # which the interpreter turns into process exit code 1 -- non-zero either
    # way. The message itself carries the machine-checkable status code.
    assert excinfo.value.code
    assert status in str(excinfo.value.code)
