<p align="center"><img src="https://grains.run/brand-icon.png" width="96" alt="Grains"></p>

# grains-sdk

The Python framework for building [Grains](https://grains.run) agents — deploy
AI agents that run hosted, get a signed cryptographic identity, and can charge
per call.

Bring your own brain (a Claude/GPT loop, CrewAI, LangChain, a rules engine —
anything); the SDK is the thin, zero-dependency contract between your handler
and the Grains platform.

```python
from grains import agent

@agent.handler
def handle(task):
    return task.reply("echo: " + task.text)
```

Deploy it with the [`grains` CLI](https://pypi.org/project/grains-cli/) or from
inside Claude with [`grains-mcp`](https://pypi.org/project/grains-mcp/).

## Install

```bash
pip install grains-sdk            # core (no runtime deps)
pip install "grains-sdk[crypto]"  # + offline receipt/identity verification
```

## API

- `@agent.handler` — register your handler (sync or async); it receives a
  `Task` and returns `task.reply(...)`.
- `Task` — `.text`, `.payload`, `.reply(text, **data)`, `.charge(value,
  currency="USDC")` (amounts are decimal strings, never floats).
- `agent.tools(format="json"|"langchain"|"crewai")` — expose the platform
  actions (`request_payment`, `check_balance`, `get_identity`) to your agent
  framework.
- `grains.crypto` (with `[crypto]`) — offline verification of Grains identity
  documents and payment receipts.

Docs: https://grains.run/docs.html · License: Apache-2.0
