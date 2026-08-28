"""grains-sdk: `@agent.handler`, `Task`, and tool adapters. Stdlib only."""
from __future__ import annotations

import inspect
from typing import Callable

from .task import Charge, Reply, Task
from .tools import get_tools

__all__ = ["agent", "Task", "Reply", "Charge"]


class _Agent:
    """Process-wide handler registry — exactly one handler per process.

    Re-registering (calling @agent.handler again) replaces the previous
    handler, matching a single Lambda/worker process running one agent.
    """

    def __init__(self):
        self._handler: Callable | None = None

    def handler(self, func: Callable) -> Callable:
        self._handler = func
        return func

    def get_handler(self) -> Callable | None:
        return self._handler

    def tools(self, format: str = "json") -> list:
        return get_tools(format)

    async def invoke(self, task: Task) -> Reply:
        """Run the registered handler (sync or async) and normalize its result."""
        handler = self._handler
        if handler is None:
            raise RuntimeError("no handler registered; use @agent.handler")
        if inspect.iscoroutinefunction(handler):
            result = await handler(task)
        else:
            result = handler(task)
        if isinstance(result, Reply):
            return result
        if isinstance(result, str):
            return task.reply(result)
        if result is None:
            if task.replies:
                return task.replies[-1]
            raise TypeError(
                "handler returned None and recorded no reply - did you forget "
                "`return task.reply(...)`?"
            )
        raise TypeError(f"handler must return a Reply or str, got {type(result).__name__}")


agent = _Agent()
