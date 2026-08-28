<p align="center"><img src="https://grains.run/brand-wordmark.png" width="360" alt="Grains"></p>

# Grains

**[grains.run](https://grains.run)** — hosting for AI agents. Build an agent in
**Python or JavaScript**, deploy it from inside Claude, and it comes back live
with a signed cryptographic identity, a scale-to-zero endpoint, and the ability
to charge per call in USDC.

This is the **open-source framework and tooling**. The hosted platform runs at
grains.run.

## Packages

| Package | Install | Language |
|---|---|---|
| [`grains-sdk`](https://pypi.org/project/grains-sdk/) (PyPI) | `pip install grains-sdk` | Python |
| [`grains-sdk`](https://www.npmjs.com/package/grains-sdk) (npm) | `npm install grains-sdk` | JavaScript / Node |
| [`grains-cli`](https://pypi.org/project/grains-cli/) | `pip install grains-cli` | — |
| [`grains-mcp`](https://pypi.org/project/grains-mcp/) | `uvx grains-mcp` | — |

## Quickstart

**Python** (`grains_app.py`):

```python
from grains import agent

@agent.handler
def handle(task):
    return task.reply("echo: " + task.text)
```

**JavaScript** (`grains_app.mjs`):

```js
export function handle(task) {
  return task.reply("echo: " + task.text);
}
```

**One command.** Sign-in opens in your browser; the command scaffolds if
needed, deploys, and prints your live endpoint:

```bash
uvx grains-cli ship
```

**Or deploy from inside Claude.** Install the plugin right in your current
session (no restart), sign in with GitHub in your browser, and the tools
appear. No token to paste:

```
/plugin marketplace add 0000F8/grains
/plugin install grains@grains
```

<details>
<summary>Plain MCP entry instead of the plugin (loads on next session start).</summary>

```bash
claude mcp add --transport http grains https://mcp.grains.run/mcp
```

</details>

<details>
<summary>Prefer a deploy token? Pass it as a header — same hosted server.</summary>

```bash
claude mcp add --transport http grains https://mcp.grains.run/mcp \
  --header "Authorization: Bearer grains_dt_..."
```

</details>

<details>
<summary>Run the server locally instead (needs <a href="https://docs.astral.sh/uv/">uv</a>).</summary>

```bash
claude mcp add grains \
  --env GRAINS_API_URL=https://api.grains.run \
  --env GRAINS_DEPLOY_TOKEN=grains_dt_... \
  -- uvx grains-mcp
```

</details>

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
        "GRAINS_DEPLOY_TOKEN": "grains_dt_..."
      }
    }
  }
}
```

</details>

Get a deploy token at **[api.grains.run/welcome](https://api.grains.run/welcome)**.
Then ask Claude: *"scaffold an agent and deploy it to Grains."*

## Layout

- `sdk/` — `grains-sdk` (Python framework)
- `sdk-js/` — `grains-sdk` (JavaScript framework)
- `cli/` — `grains-cli` (`grains init / dev / deploy / pay / verify`)
- `mcp/` — `grains-mcp` (deploy from inside Claude)
- `spec/` — identity & payment-receipt formats, with test vectors
- `examples/` — minimal Python and Node agents

## License

Apache-2.0
