"""grains CLI entrypoint (console script: `grains`)."""
from __future__ import annotations

import argparse

from . import deploy as deploy_cmd
from . import dev as dev_cmd
from . import init as init_cmd
from . import login as login_cmd
from . import pay as pay_cmd
from . import ship as ship_cmd
from . import verify as verify_cmd


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="grains", description="Grains local dev CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="scaffold a new agent in the target directory")
    p_init.add_argument("path", nargs="?", default=".")
    p_init.add_argument("--force", action="store_true", help="overwrite existing files")
    p_init.add_argument(
        "--template",
        choices=["crewai", "langgraph", "langchain", "none", "node"],
        default=None,
        help="force a template instead of auto-detecting the framework",
    )
    p_init.set_defaults(func=init_cmd.cmd_init)

    p_dev = sub.add_parser("dev", help="run the agent locally with a task API")
    p_dev.add_argument("path", nargs="?", default=".")
    p_dev.add_argument("--port", type=int, default=8787)
    p_dev.set_defaults(func=dev_cmd.cmd_dev)

    p_verify = sub.add_parser("verify", help="verify a payment receipt offline")
    p_verify.add_argument("path", help="path to a receipt JSON file")
    p_verify.set_defaults(func=verify_cmd.cmd_verify)

    p_pay = sub.add_parser("pay", help="submit a task, paying via x402 if the agent is priced")
    p_pay.add_argument("api_url", help="agents base URL, e.g. https://agents.grains.run")
    p_pay.add_argument("agent", help="agent name")
    p_pay.add_argument("--key", help="hex-encoded payer private key (or set GRAINS_PAYER_KEY)")
    p_pay.add_argument("--text", required=True, help="task text")
    p_pay.add_argument("--caller-token", default=None, help="grains_ct_... caller token, if required")
    p_pay.set_defaults(func=pay_cmd.cmd_pay)

    p_ship = sub.add_parser("ship", help="sign in, scaffold if needed, deploy, and wait for live")
    p_ship.add_argument("path", nargs="?", default=".")
    p_ship.add_argument("--api", help="control-plane URL (or GRAINS_API_URL)")
    p_ship.set_defaults(func=ship_cmd.cmd_ship)

    p_login = sub.add_parser("login", help="sign in with GitHub in your browser")
    p_login.add_argument("--api")
    p_login.set_defaults(func=login_cmd.cmd_login)

    p_logout = sub.add_parser("logout", help="forget the stored deploy token")
    p_logout.add_argument("--api")
    p_logout.set_defaults(func=login_cmd.cmd_logout)

    p_deploy = sub.add_parser("deploy", help="deploy the agent in this directory to Grains")
    p_deploy.add_argument("path", nargs="?", default=".")
    p_deploy.add_argument("--token", help="deploy token (or set GRAINS_DEPLOY_TOKEN)")
    p_deploy.add_argument("--api", help="control-plane URL (or GRAINS_API_URL)")
    p_deploy.set_defaults(func=deploy_cmd.cmd_deploy)

    p_logs = sub.add_parser("logs", help="recent logs for a deployed agent")
    p_logs.add_argument("name")
    p_logs.add_argument("--limit", type=int, default=50)
    p_logs.add_argument("--token")
    p_logs.add_argument("--api")
    p_logs.set_defaults(func=deploy_cmd.cmd_logs)

    p_balance = sub.add_parser("balance", help="earnings across your paid agents")
    p_balance.add_argument("--token")
    p_balance.add_argument("--api")
    p_balance.set_defaults(func=deploy_cmd.cmd_balance)

    p_agents = sub.add_parser("agents", help="list your agents")
    p_agents.add_argument("--token")
    p_agents.add_argument("--api")
    p_agents.set_defaults(func=deploy_cmd.cmd_agents)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
