---
name: youtrack-standup
description: Generate a standup / status update from YouTrack — what was recently resolved, what is in progress, and what is blocked or unassigned. Use when the user asks for a "standup", "status update", "what did I do", "what's in progress", or a summary of their YouTrack work. Requires the youtrack MCP server.
---

# YouTrack standup / status

Produce a concise status report from the `youtrack` MCP tools. Keep it skimmable.

## Gather
Run these `search_issues` / `my_issues` queries (adjust `project:` or drop
`for: me` for a team-wide view):

1. **Done recently** — `my_issues("State: Done resolved date: {Today} .. {Today}")`
   or, for the last few days, `resolved date: {minus 3d} .. {Today}`.
2. **In progress** — `my_issues("State: {In Progress}")`.
3. **To do / open** — `my_issues("#Unresolved State: -{In Progress}")`.
4. **Blocked** (if a `Blocked`/`On Hold` state or tag exists) —
   `my_issues("State: Blocked")` or `my_issues("tag: blocked")`.

## Report format
```
📅 Standup — <account> (<date>)

✅ Done
  - DEMO-12  Fix login redirect
🔧 In progress
  - DEMO-18  Rework token refresh   (Priority: Critical)
📋 Up next
  - DEMO-20  Add rate limiting
🚧 Blocked
  - DEMO-9   Waiting on API keys
```

## Notes
- If a query returns nothing, omit that section rather than printing "none".
- Show the readable id + summary; add Priority/assignee only when it adds signal.
- Date macros like `{Today}`, `{This week}`, `{minus 7d}` are understood by
  YouTrack search — prefer them over hardcoded dates.
- For a team report, drop `for: me` and group by assignee.
