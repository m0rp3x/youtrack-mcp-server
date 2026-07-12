# Contributing

Thanks for your interest! This is a small, focused project.

## Dev setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check .
```

## Guidelines

- Keep the client (`youtrack_mcp/client.py`) a thin REST wrapper; put anything
  user-facing (formatting) in `youtrack_mcp/formatting.py`.
- Every new tool goes in `youtrack_mcp/server.py` with a clear docstring — the
  docstring **is** the tool description the LLM sees.
- Add or update tests; network is stubbed with `httpx.MockTransport`, so tests
  stay offline and fast.
- Run `ruff check .` before opening a PR.

## Reporting issues

Include your YouTrack version, the tool you called, and the (redacted) error.
Never paste real tokens.
