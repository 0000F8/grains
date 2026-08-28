import pytest
from grains import agent

EXPECTED_NAMES = {"request_payment", "check_balance", "get_identity"}


def test_json_format_returns_three_tools():
    tools = agent.tools(format="json")
    assert len(tools) == 3
    assert {t["name"] for t in tools} == EXPECTED_NAMES


def test_json_format_default():
    assert agent.tools() == agent.tools(format="json")


def test_json_tools_have_valid_schema_keys():
    for tool in agent.tools(format="json"):
        assert set(tool.keys()) == {"name", "description", "input_schema"}
        assert isinstance(tool["name"], str)
        assert isinstance(tool["description"], str)
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema


def test_langchain_format_raises_import_error_when_missing():
    with pytest.raises(ImportError, match="langchain-core"):
        agent.tools(format="langchain")


def test_crewai_format_raises_import_error_when_missing():
    with pytest.raises(ImportError, match="crewai"):
        agent.tools(format="crewai")


def test_unknown_format_raises_value_error():
    with pytest.raises(ValueError):
        agent.tools(format="bogus")
