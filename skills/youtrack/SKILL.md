---
name: youtrack
description: Manage YouTrack issues (tasks) through the youtrack MCP server — list your tasks, triage, create, comment, and resolve. Use when the user asks to see "my tasks/issues", check what's assigned to them, create or update an issue, mark something done, or otherwise work with YouTrack. Requires the youtrack MCP server to be configured.
---

# YouTrack task management

You have a set of `youtrack` MCP tools backed by a permanent token. Everything
you do runs **as that token's user** and is limited by that user's YouTrack
permissions.

## Tools at a glance
- `whoami` — confirm which account the token belongs to (run first if unsure).
- `my_issues(query="", limit=30)` — issues assigned to the token owner. Add
  `query` to narrow, e.g. `#Unresolved`, `State: Open`, `project: DEMO`.
- `search_issues(query, limit=30)` — arbitrary YouTrack search.
- `get_issue(issue_id)` — full details of one issue (`DEMO-12`).
- `create_issue(project, summary, description="")` — new issue in a project.
- `run_command(issue_ids, command, comment="")` — apply a YouTrack command.
- `add_comment(issue_id, text)` — comment on an issue.
- `list_projects(include_archived=False)` — available projects + short names.

## Common workflows

**"What are my tasks?" / "What should I work on?"**
1. `my_issues("#Unresolved")`.
2. Present as a short prioritized list (id, state, summary). Offer to open any
   one with `get_issue`.

**"Create a task …"**
1. If the target project is unclear, `list_projects` and confirm the short name.
2. `create_issue(project, summary, description)`.
3. Echo the new readable id back to the user.

**"Mark DEMO-12 done" / "resolve it"**
- `run_command(["DEMO-12"], "State Done")`. Use the project's real resolved-state
  name if `Done` is rejected (`get_issue` shows the current State; typical values
  are `Done`, `Fixed`, `Resolved`).

**"Assign DEMO-12 to me"** → `run_command(["DEMO-12"], "for me")`.
**Bulk changes** → pass several ids: `run_command(["DEMO-1","DEMO-2"], "Priority Major")`.

## YouTrack command cheatsheet (for `run_command`)
- `State Done` / `State In Progress` — change workflow state.
- `for me` / `for <login>` — set assignee.
- `Priority Critical` — set a single-value field.
- `add Board Sprint 1` — add to an agile board sprint.
- `tag urgent` — add a tag.
- Chain several: `for me State In Progress Priority Major`.

## Guardrails
- **Deleting issues** is usually not allowed for a plain Contributor-level token;
  if a delete is requested and fails on permissions, say so rather than retrying.
- Before creating or resolving on the user's behalf in a shared/real project,
  confirm the project and summary if there's any ambiguity.
- If a tool errors with `401`/`Missing … environment variable`, the MCP server
  isn't configured — point the user to the README setup, don't guess a token.
