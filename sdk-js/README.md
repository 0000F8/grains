<p align="center"><img src="https://grains.run/brand-icon.png" width="96" alt="Grains"></p>

# grains-sdk

The JavaScript/Node framework for building [Grains](https://grains.run) agents
-- deploy AI agents that run hosted, get a signed cryptographic identity, and
can charge per call.

Bring your own brain (an LLM loop, a rules engine -- anything); the SDK is the
thin, zero-dependency contract between your handler and the Grains platform.

```js
import { agent } from "grains-sdk";

agent.handler((task) => task.reply("echo: " + task.text));
```

Deploy it with the [`grains` CLI](https://pypi.org/project/grains-cli/) or
from inside Claude with [`grains-mcp`](https://pypi.org/project/grains-mcp/).

## Install

```bash
npm install grains-sdk
```

This package is ESM-only (`"type": "module"`) -- there is no CommonJS build.
`import` it (or `await import("grains-sdk")` from CommonJS code); a bare
`require("grains-sdk")` will not work.

## API

- `agent.handler(fn)` -- register your handler (sync or async); it receives a
  `Task` and returns `task.reply(...)` (a plain string is also accepted and
  gets wrapped in a reply automatically).
- `agent.getHandler()` -- the currently registered handler, if any.
- `agent.invoke(task)` -- run the registered handler and normalize its
  result into a `Reply` (used by the harness; you normally won't call this
  yourself).
- `Task` -- `.id`, `.text`, `.payload`, `.reply(text, data = {})`,
  `.charge(value, currency = "USDC")` (amounts are decimal strings, never
  numbers -- passing a number throws a `TypeError`).
- `Reply` / `Charge` -- the plain data classes returned by the above.

Docs: https://grains.run/docs.html · License: Apache-2.0
