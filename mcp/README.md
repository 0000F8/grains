<p align="center"><img src="https://grains.run/brand-icon.png" width="96" alt="Grains"></p>

# grains-mcp

An MCP server for **Grains** — build and deploy a hosted agent to grains.run
without leaving Claude.

It's a thin client over the Grains control-plane API. Every tool call acts as
one Grains user, authenticated by that user's **deploy token**.

## Tools

| Tool | What it does |
|---|---|
| `grains_scaffold` | Generate `grains_app.py` + `grains.toml` for a new agent (framework: none/crewai/langchain/langgraph). Pure local — Claude writes the files. |
| `grains_deploy` | Create the agent (if new) and deploy the given files. Returns status + the agent's signed identity (did). |
| `grains_invoke` | Send a task to a deployed agent and return its reply. |
| `grains_logs` | Recent agent logs. |
| `grains_list_agents` / `grains_agent_status` | List / inspect your agents. |
| `grains_secret_set` | Set an agent secret (e.g. `OPENAI_API_KEY`). Value is never echoed back. |
| `grains_set_price` | Make an agent public / set its per-message price (decimal string). |

## Setup

**Hosted (recommended)** — nothing to install, no token to paste; Claude Code
opens your browser to sign in with GitHub (OAuth 2.1 + PKCE, dynamic client
registration):

```bash
claude mcp add --transport http grains https://mcp.grains.run/mcp
```

Or with a deploy token (from [api.grains.run/welcome](https://api.grains.run/welcome))
as a header, skipping the browser flow:

```bash
claude mcp add --transport http grains https://mcp.grains.run/mcp \
  --header "Authorization: Bearer grains_dt_your_token_here"
```

**Local** — run this same package on your machine (needs
[uv](https://docs.astral.sh/uv/)):

```bash
claude mcp add grains \
  --env GRAINS_API_URL=https://api.grains.run \
  --env GRAINS_DEPLOY_TOKEN=grains_dt_your_token_here \
  -- uvx grains-mcp
```

<details>
<summary>Claude Desktop or another MCP client? Paste this JSON instead.</summary>

```json
{
  "mcpServers": {
    "grains": {
      "command": "uvx",
      "args": ["grains-mcp"],
      "env": {
        "GRAINS_API_URL": "https://api.grains.run",
        "GRAINS_DEPLOY_TOKEN": "grains_dt_your_token_here"
      }
    }
  }
}
```

</details>

Then, in Claude: *"scaffold a URL-summarizer agent and deploy it to Grains."*
Claude calls `grains_scaffold`, writes the files, calls `grains_deploy`, and
you can `grains_invoke` it — all in one conversation.

## Transports

- **stdio** (default) — for the Claude Code config above.
- **streamable-http** — `grains-mcp --http --port 8080`, for hosting at
  `mcp.grains.run` (hosted OAuth-backed deployment is a follow-up; today the
  server authenticates with the deploy token from its env).
