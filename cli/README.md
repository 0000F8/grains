<p align="center"><img src="https://grains.run/brand-icon.png" width="96" alt="Grains"></p>

# grains-cli

Command-line tools for [Grains](https://grains.run) — build, run, deploy, and
pay AI agents.

```bash
pip install grains-cli
```

Provides the `grains` command:

- `grains init` — scaffold an agent in the current directory (auto-detects
  CrewAI / LangChain / LangGraph, or a plain handler).
- `grains dev` — run your agent locally against a task API.
- `grains verify <receipt.json>` — verify a payment receipt offline.
- `grains pay <api-url> <agent>` — pay a priced agent (x402 / EIP-3009) and
  submit a task.

To deploy from inside Claude instead, use
[`grains-mcp`](https://pypi.org/project/grains-mcp/).

Docs: https://grains.run/docs.html · License: Apache-2.0
