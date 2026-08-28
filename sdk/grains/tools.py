"""Agent tool definitions and framework adapters.

M1: tool executors are stubs — real payment/identity wiring lands with the
control plane (M2+). Definitions themselves are stable JSON Schema so agent
authors can start writing tool-using prompts today.
"""
from __future__ import annotations

TOOL_DEFS = [
    {
        "name": "request_payment",
        "description": "Request a payment from the caller for work this agent performed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount": {
                    "type": "string",
                    "description": "Decimal amount as a string, e.g. \"1.50\" (never a float).",
                },
                "currency": {
                    "type": "string",
                    "description": "Currency code.",
                    "default": "USDC",
                },
                "reason": {
                    "type": "string",
                    "description": "Human-readable reason for the charge.",
                },
            },
            "required": ["amount"],
        },
    },
    {
        "name": "check_balance",
        "description": "Check this agent's current wallet balance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "currency": {
                    "type": "string",
                    "description": "Currency code to check.",
                    "default": "USDC",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_identity",
        "description": "Get this agent's signed identity document (did:key, wallet address).",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


def _stub_executor(**_kwargs) -> dict:
    return {"status": "unavailable_in_local_dev"}


def get_tools(format: str = "json") -> list:
    if format == "json":
        return [dict(t) for t in TOOL_DEFS]
    if format == "langchain":
        return _wrap_langchain()
    if format == "crewai":
        return _wrap_crewai()
    raise ValueError(f"unknown tools format: {format!r}")


def _wrap_langchain() -> list:
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as e:
        raise ImportError(
            "the 'langchain' tools format requires the 'langchain-core' package "
            "(pip install langchain-core)"
        ) from e
    return [
        StructuredTool.from_function(
            func=_stub_executor,
            name=t["name"],
            description=t["description"],
        )
        for t in TOOL_DEFS
    ]


def _wrap_crewai() -> list:
    try:
        from crewai.tools import BaseTool
    except ImportError as e:
        raise ImportError(
            "the 'crewai' tools format requires the 'crewai' package (pip install crewai)"
        ) from e

    class _StubTool(BaseTool):
        def _run(self, **kwargs) -> dict:
            return _stub_executor(**kwargs)

    return [_StubTool(name=t["name"], description=t["description"]) for t in TOOL_DEFS]
