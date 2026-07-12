# youtrack-mcp

A small [Model Context Protocol](https://modelcontextprotocol.io) server for
**JetBrains YouTrack**. It lets Claude (Claude Code / Claude Desktop), Cursor and
any other MCP client read and act on your issues — *"show my tasks"*, *"create a
bug in DEMO"*, *"mark DEMO-12 done"* — using a YouTrack permanent token.

Ships with two ready-to-use Claude Code **skills** (`youtrack`,
`youtrack-standup`) on top of the tools.

- ✅ No secrets in the repo — you pass `YOUTRACK_URL` / `YOUTRACK_TOKEN` via your client.
- ✅ Acts as the token's user, bounded by that user's YouTrack permissions.
- ✅ Async, typed, tested; MIT licensed.

## Tools

| Tool | What it does |
|------|--------------|
| `whoami` | Show which account the token belongs to (connectivity check). |
| `my_issues(query="", limit=30)` | Issues assigned to you; add search terms to narrow. |
| `search_issues(query, limit=30)` | Arbitrary YouTrack search. |
| `get_issue(issue_id)` | Full details of one issue (`DEMO-12`). |
| `create_issue(project, summary, description="")` | Create an issue. |
| `run_command(issue_ids, command, comment="")` | Apply a YouTrack command (`State Done`, `for me`, …). |
| `add_comment(issue_id, text)` | Comment on an issue. |
| `list_projects(include_archived=False)` | List projects and their short names. |

## Getting a token

In YouTrack: **your avatar → Profile → Account Security → New token…**, give it a
name and (optionally) scope it to the YouTrack service. Copy the `perm-…` value.
The server then acts with that user's permissions.

## Install & configure

The server is a normal Python package with a console script `youtrack-mcp`. Point
your MCP client at it and pass the two env vars.

### Claude Code

Add to your Claude Code MCP config (`.mcp.json` in a project, or user scope):

```json
{
  "mcpServers": {
    "youtrack": {
      "command": "uvx",
      "args": ["youtrack-mcp"],
      "env": {
        "YOUTRACK_URL": "https://your-youtrack.example.com",
        "YOUTRACK_TOKEN": "perm-XXXX.YYYY.ZZZZ"
      }
    }
  }
}
```

No `uv`? Use a cloned checkout instead:

```json
{
  "mcpServers": {
    "youtrack": {
      "command": "python",
      "args": ["-m", "youtrack_mcp.server"],
      "cwd": "/absolute/path/to/youtrack-mcp",
      "env": {
        "YOUTRACK_URL": "https://your-youtrack.example.com",
        "YOUTRACK_TOKEN": "perm-XXXX.YYYY.ZZZZ"
      }
    }
  }
}
```

### Claude Desktop

Edit `claude_desktop_config.json` (Settings → Developer → Edit Config) and add the
same `mcpServers` block as above, then restart Claude Desktop.

### Cursor / other MCP clients

Any client that speaks MCP over stdio works — configure a server whose command is
`uvx youtrack-mcp` (or `python -m youtrack_mcp.server`) with the two env vars.

## Skills (Claude Code)

The `skills/` folder contains Claude Code skills that drive the tools:

- **`youtrack`** — list/triage/create/comment/resolve workflows + a command cheatsheet.
- **`youtrack-standup`** — build a standup/status report from your issues.

Install by copying into a skills directory Claude Code loads, e.g.:

```bash
cp -r skills/youtrack skills/youtrack-standup ~/.claude/skills/
```

(or the project-local `.claude/skills/`). They're plain `SKILL.md` files — no build step.

## Usage examples

Once configured, just talk to your client:

- "What are my open tasks in YouTrack?" → `my_issues("#Unresolved")`
- "Create a bug in DEMO: login redirect loops" → `create_issue("DEMO", …)`
- "Mark DEMO-12 done and comment 'shipped in 1.4'" →
  `run_command(["DEMO-12"], "State Done", "shipped in 1.4")`
- "Give me a standup" → the `youtrack-standup` skill

## Development

```bash
git clone https://github.com/m0rp3x/youtrack-mcp
cd youtrack-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest -q          # unit tests (no network — httpx is stubbed)
ruff check .       # lint

# Smoke-test against a real instance:
export YOUTRACK_URL=https://your-youtrack.example.com
export YOUTRACK_TOKEN=perm-...
python -m youtrack_mcp.server     # serves MCP over stdio
```

To inspect the tools interactively, run it under the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector uvx youtrack-mcp
```

## Publishing (maintainers)

```bash
pip install build twine
python -m build            # -> dist/*.whl, *.tar.gz
twine upload dist/*        # publish to PyPI so users can `uvx youtrack-mcp`
```

## Security notes

- Never commit `.env`; only `.env.example` is tracked.
- Treat the token like a password. Scope it to the YouTrack service and rotate it
  if it leaks (Profile → Account Security → revoke).
- The server only makes the API calls listed above — no bulk export, no deletes.

## License

MIT — see [LICENSE](LICENSE).
