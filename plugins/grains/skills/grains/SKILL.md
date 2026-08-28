---
name: grains
description: Building and deploying agents to grains.run — scaffold layout, deploy/invoke/price workflow via the grains MCP tools, and the CLI fallback when MCP tools are unavailable.
---

# Deploying agents to Grains

Grains (grains.run) hosts AI agents: deploy from a chat, get a signed
cryptographic identity, scale-to-zero hosting, and per-call USDC pricing (x402).

## The workflow

1. **Scaffold** — `grains_scaffold(description, framework)` returns the two
   required files; write them to a directory:
   - `grains_app.py` (or `.mjs` for Node) with `def handle(task)` / `export function handle(task)`
   - `grains.toml` — `[agent]` name, entrypoint (`grains_app:handle`), runtime
     (`python3.12` | `nodejs20.x`)
   Frameworks: `none`, `crewai`, `langchain`, `langgraph`. Anything with heavy
   dependencies (a `requirements.txt`/`package.json` beyond grains-sdk) deploys
   on the container tier automatically — first deploy takes a few minutes to
   build; poll `grains_agent_status` until `live`.
2. **Deploy** — `grains_deploy(name, files)` with the file contents. Returns
   status and the agent's signed identity (did).
3. **Secrets** — `grains_secret_set(name, "OPENAI_API_KEY", value)`; values are
   encrypted, never echoed back, surfaced to the agent as env vars.
4. **Try it** — `grains_invoke(name, text)` polls until the reply arrives.
5. **Logs** — `grains_logs(name)` when something misbehaves.
6. **Monetize** — `grains_set_price(name, price_value="0.05", public=true)`;
   callers then pay per task via x402 (USDC, Base Sepolia during beta) and
   every reply carries an offline-verifiable signed receipt.

## If the grains_* MCP tools are NOT in this session

The MCP server loads at session start (or after `/plugin install grains@grains`
+ `/reload-plugins`). Without it, use the CLI via Bash — same platform, token
auth:

```bash
uvx --from "git+https://github.com/0000F8/grains#subdirectory=cli" grains deploy   # from the agent dir
```

Auth: `GRAINS_DEPLOY_TOKEN` env var (mint one at https://api.grains.run/welcome).
`grains agents`, `grains logs <name>`, `grains pay` also exist. `grains dev`
runs the agent locally against a task API for iteration before deploying.

## Conventions

- Agent names: lowercase, digits, dashes (slug).
- `task.text` is the input; reply with `task.reply(text)` / return a string.
- Charge inside a handler with `task.charge(value, currency)` (priced agents).
- Never write secrets into grains_app.py — use grains_secret_set.
