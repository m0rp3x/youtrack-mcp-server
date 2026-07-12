"""``youtrack-admin`` — provision and manage agent accounts.

Reads ``YOUTRACK_URL`` and ``YOUTRACK_ADMIN_TOKEN`` from the environment. The
admin token must belong to a user allowed to create/update users.

Examples::

    youtrack-admin create-agent agent-alpha --name "Agent Alpha"
    youtrack-admin create-agent researcher --role contributor --print-config
    youtrack-admin list-agents
    youtrack-admin revoke-agent agent-alpha            # ban
    youtrack-admin revoke-agent agent-alpha --delete   # hard delete
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from .admin import AdminClient, AdminError


def _admin_client() -> AdminClient:
    url = os.environ.get("YOUTRACK_URL", "").strip()
    token = os.environ.get("YOUTRACK_ADMIN_TOKEN", "").strip()
    if not url or not token:
        sys.exit(
            "error: YOUTRACK_URL and YOUTRACK_ADMIN_TOKEN must be set "
            "(the admin token needs permission to create users)."
        )
    return AdminClient(url, token)


def _mcp_config(url: str, login: str, token: str) -> str:
    block = {
        "mcpServers": {
            f"youtrack-{login}": {
                "command": "uvx",
                "args": ["youtrack-mcp"],
                "env": {"YOUTRACK_URL": url, "YOUTRACK_TOKEN": token},
            }
        }
    }
    return json.dumps(block, indent=2, ensure_ascii=False)


async def _create_agent(args: argparse.Namespace) -> None:
    client = _admin_client()
    try:
        agent = await client.provision_agent(
            args.login, args.name or args.login, role=args.role, email=args.email
        )
    finally:
        await client.aclose()

    print(f"✓ agent '{agent.login}' ({agent.name}) ready — role: {args.role}")
    print(f"  user id: {agent.user_id}")
    print(f"  YOUTRACK_TOKEN={agent.token}")
    print("  (store this token in the agent's MCP env; it is shown only once here)")
    if args.print_config:
        url = os.environ["YOUTRACK_URL"].strip()
        print("\n--- MCP client config ---")
        print(_mcp_config(url, agent.login, agent.token))
    print(
        "\nnote: role permissions take a few seconds to propagate; the agent's "
        "first write may 403 and succeed on retry."
    )


async def _list_agents(_: argparse.Namespace) -> None:
    client = _admin_client()
    try:
        users = await client.list_users()
    finally:
        await client.aclose()
    for u in sorted(users, key=lambda x: x.get("login", "")):
        roles = ", ".join(u.get("roles", []))
        flag = " [banned]" if u.get("banned") else ""
        print(f"{u.get('login'):20} {u.get('name', ''):20} roles: {roles or '(none)'}{flag}")


async def _revoke_agent(args: argparse.Namespace) -> None:
    client = _admin_client()
    try:
        user = await client.find_user(args.login)
        if user is None:
            sys.exit(f"error: no user with login '{args.login}'")
        if args.delete:
            await client.delete_user(user["id"])
            print(f"✓ deleted '{args.login}'")
        else:
            await client.ban_user(user["id"])
            print(f"✓ banned '{args.login}' (use --delete to remove entirely)")
    finally:
        await client.aclose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="youtrack-admin", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-agent", help="create/reuse an agent account + token")
    create.add_argument("login", help="unique login, e.g. agent-alpha")
    create.add_argument("--name", help="display name (defaults to the login)")
    create.add_argument(
        "--role",
        default="contributor",
        help="contributor (default) | observer | project-admin | admin",
    )
    create.add_argument("--email", help="optional email (placeholder is fine)")
    create.add_argument(
        "--print-config", action="store_true", help="also print a ready MCP config block"
    )
    create.set_defaults(func=_create_agent)

    listing = sub.add_parser("list-agents", help="list users and their global roles")
    listing.set_defaults(func=_list_agents)

    revoke = sub.add_parser("revoke-agent", help="ban (default) or delete an agent")
    revoke.add_argument("login")
    revoke.add_argument("--delete", action="store_true", help="hard-delete instead of banning")
    revoke.set_defaults(func=_revoke_agent)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        asyncio.run(args.func(args))
    except AdminError as exc:
        sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()
