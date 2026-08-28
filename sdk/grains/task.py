"""Task, Reply, and Charge — the SDK's core data shapes."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Reply:
    text: str
    data: dict


@dataclass
class Charge:
    # value is a decimal string (e.g. "1.50"), never a float — see spec/identity.md.
    value: str
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError(
                f"charge value must be a decimal string, not {type(self.value).__name__} "
                "(amounts are never floats)"
            )


class MemoryKV:
    """Exact-match state store (watermarks, counters) -- platform-held, so a
    stateless sandbox keeps state without holding any credentials. Distinct
    from remember()/facts(): state is machine-read, never distilled."""

    def __init__(self, task):
        self._task = task

    def get(self, key: str, default=None, scope: str = "global"):
        from .mcp import internal_call
        out = internal_call("/internal/memory", {"op": "state_get", "key": str(key), "scope": scope})
        if out is None or out.get("value") is None:
            return default
        return out["value"]

    def set(self, key: str, value, scope: str = "global") -> bool:
        from .mcp import internal_call
        out = internal_call("/internal/memory",
                            {"op": "state_set", "key": str(key), "value": str(value), "scope": scope})
        return bool(out and out.get("ok"))

    def delete(self, key: str, scope: str = "global") -> bool:
        from .mcp import internal_call
        out = internal_call("/internal/memory", {"op": "state_del", "key": str(key), "scope": scope})
        return bool(out and out.get("ok"))


class Task:
    def __init__(self, id: str, text: str, payload: dict | None = None,
                 session: str | None = None):
        self.id = id
        self.text = text
        self.payload = payload if payload is not None else {}
        self.session = session
        self.memory = MemoryKV(self)
        self.replies: list[Reply] = []
        self.charges: list[Charge] = []
        self.events: list[str] = []

    def reply(self, text: str, **data) -> Reply:
        r = Reply(text=text, data=data)
        self.replies.append(r)
        return r

    def mcp(self, name: str):
        """A proxy to a platform-bound MCP server (see grains.mcp). Credentials
        live in the platform; call_tool round-trips through the control plane."""
        from .mcp import MCPProxy
        return MCPProxy(name)

    def emit(self, chunk: str) -> None:
        """Stream a partial-output chunk. On a deployed agent the chunk is
        POSTed live to the control plane and becomes readable via GET task
        ?since=<seq> before the final reply lands (progressive UX: Telegram
        edits, a live web view). Locally (grains dev) there's no stream, so it
        is a no-op. The final reply() is still what callers treat as the answer."""
        chunk = str(chunk)
        from .mcp import emit_chunk
        emit_chunk(chunk)
        # Mirror into stdout (forwarded to the invocation log as agent[out],
        # reclassified as an emit line by the dashboard) so streamed chunks
        # appear in the Logs tab too, not only in the task's event stream.
        print(f"grains-emit {' '.join(chunk.split())[:160]}")

    def charge(self, value: str, currency: str = "USDC") -> Charge:
        c = Charge(value=value, currency=currency)
        self.charges.append(c)
        return c


    # ---- tiered memory ------------------------------------------------------

    def history(self, limit: int = 10) -> list[dict]:
        """Prior turns of THIS conversation (same agent + session), oldest
        first: [{"text": ..., "reply": ..., "at": ...}]. Raw tier -- derived
        from the task log, nothing to maintain. Empty when there's no session
        (direct API calls without a session key) or in local dev."""
        from .mcp import internal_call
        out = internal_call("/internal/history", {"limit": int(limit)})
        return (out or {}).get("turns", [])

    def remember(self, fact: str, scope: str = "global") -> str | None:
        """Store one distilled fact. scope: "session" (this conversation),
        "global" (this agent, all sessions), "universal" (every agent on the
        account -- requires the owner-granted write capability). Provenance
        (this task id) is attached automatically so every fact can answer
        'why do you believe this?'. Returns the fact id, or None locally."""
        from .mcp import internal_call
        out = internal_call("/internal/memory",
                            {"op": "remember", "fact": str(fact), "scope": scope})
        return (out or {}).get("id")

    def facts(self, scope: str | None = None, limit: int = 50) -> list[dict]:
        """Recall distilled facts: session + global + universal (or one scope),
        newest first: [{"id", "scope", "body", "at"}]."""
        from .mcp import internal_call
        out = internal_call("/internal/memory",
                            {"op": "facts", "scope": scope, "limit": int(limit)})
        return (out or {}).get("items", [])

    def forget(self, fact_id: str) -> bool:
        from .mcp import internal_call
        out = internal_call("/internal/memory", {"op": "forget", "id": str(fact_id)})
        return bool(out and out.get("ok"))

    def context(self, budget: int = 4000) -> str:
        """One prompt-ready block: recent conversation turns plus relevant
        facts (session > global > universal), server-assembled and trimmed to
        ~budget characters. The one-liner that makes an agent remember."""
        from .mcp import internal_call
        out = internal_call("/internal/memory", {"op": "context", "budget": int(budget)})
        return (out or {}).get("context", "")

    def schedule(self, cron: str | None) -> bool:
        """Set (or clear, with None) this agent's OWN schedule -- a 5-field
        cron expression, UTC. Lets a user ask an agent to run itself
        ("check this every morning"); the owner sees the change on the
        dashboard and can clear it. One schedule per agent."""
        from .mcp import internal_call
        out = internal_call("/internal/schedule", {"cron": cron})
        return bool(out and out.get("ok"))

    def http(self, name: str):
        """A proxy to a platform-bound HTTP API (http egress connector):

            r = task.http("github").request("GET", "/repos/o/r/issues")

        Returns {"status", "body", "json", ...}. The credential and base URL
        live in the platform; agent code only ever names the binding."""
        from .mcp import HTTPProxy
        return HTTPProxy(name)

    def request_access(self, provider: str, reason: str | None = None,
                       scopes: list[str] | None = None) -> dict:
        """Ask the owner for access this agent does not have:

            task.request_access("github", reason="to read your open PRs")

        Returns {"status": "pending"|..., "id", "existing"}. Asking is NOT
        getting: the request lands in the owner's queue -- on the dashboard,
        and in whatever authority plane they use (Salt) -- and a human answers
        it. Nothing this agent can do turns a pending row into a grant.

        Call it when egress refuses. An agent held to a [capabilities] manifest
        can only ask for what it declared, so asking is not a way around
        declaring."""
        from .mcp import internal_call
        out = internal_call("/internal/grant-request",
                            {"provider": provider, "reason": reason, "scopes": scopes})
        if not out or "request" not in out:
            detail = (out or {}).get("detail") or "could not ask for access"
            return {"status": "failed", "error": detail, "id": None, "existing": False}
        return {"status": out["request"]["status"], "id": out["request"]["id"],
                "existing": bool(out.get("existing"))}

    def hire(self, name: str, text: str, max_price: str | None = None,
             timeout: int = 120) -> dict:
        """Hire another agent to do a sub-task, under this agent's owner-set
        mandate (enable + caps + allowlist on Settings > Hiring). Blocks until
        the sub-task finishes (or `timeout` seconds) and returns
        {"status", "reply", "error", "task_id", "price"}. The spend is
        recorded on the hires ledger and the receipt chain links the tasks."""
        import time as _time

        from .mcp import internal_call
        out = internal_call("/internal/hire",
                            {"name": name, "text": text, "max_price": max_price})
        if not out or "sub_task_id" not in out:
            detail = (out or {}).get("detail") or "hire failed (not deployed, or mandate refused)"
            return {"status": "failed", "reply": None, "error": detail,
                    "task_id": None, "price": None}
        sub_id, price = out["sub_task_id"], out.get("price")
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            st = internal_call("/internal/hire_status", {"sub_task_id": sub_id}) or {}
            if st.get("status") in ("done", "failed"):
                return {"status": st["status"], "reply": st.get("reply"),
                        "error": st.get("error"), "task_id": sub_id, "price": price}
            _time.sleep(1.5)
        return {"status": "failed", "reply": None, "error": "hire timed out",
                "task_id": sub_id, "price": price}

    def wake_me(self, text, at=None, in_seconds=None, payload=None,
                session=None) -> str | None:
        """Hand the platform a note to deliver back to THIS agent later, then
        return immediately -- the agent is NOT kept alive in between. There is
        no process, no sandbox, nothing billed while the note waits: just a
        row and a wake time. When it comes due, a new task is dispatched with
        `text` (plus `payload`, tagged {"trigger": "wake", "wakeup_id": ...})
        in the same `session` as this call by default, so it reads as a
        continuation of this conversation rather than a fresh one.

        Pass exactly one of `at` (an ISO8601 timestamp) or `in_seconds`
        (seconds from now). Returns the wakeup id, or None locally (`grains
        dev` has no scheduler to hand the note to)."""
        from .mcp import internal_call
        out = internal_call("/internal/wake",
                            {"at": at, "in_seconds": in_seconds, "text": text,
                             "payload": payload, "session": session})
        return (out or {}).get("id")
