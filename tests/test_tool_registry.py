from pydantic import BaseModel, Field

from tools import TOOLS
from tools.base import ToolWrapper, tool


def test_auto_discovery_finds_existing_tools():
    assert "calculator" in TOOLS
    assert "current_time" in TOOLS
    assert "wikipedia_search" in TOOLS


def test_tool_schema_has_openai_function_calling_shape():
    schema = TOOLS["calculator"].schema
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "calculator"
    assert "description" in fn
    params = fn["parameters"]
    assert params["type"] == "object"
    assert "expression" in params["properties"]
    assert "expression" in params["required"]


def test_tool_run_validates_args_and_calls_function():
    result = TOOLS["calculator"].run({"expression": "12*3+4"})
    assert result == "40"


def test_tool_supports_no_args_function():
    result = TOOLS["current_time"].run({})
    assert isinstance(result, str)
    assert len(result) > 0


def test_tool_decorator_supports_multi_arg_pydantic_model():
    """기존 tool.run(str(first_value)) 버그가 수정됐는지 검증."""

    class TwoArgs(BaseModel):
        a: int = Field(...)
        b: int = Field(...)

    @tool(TwoArgs, name="test_multi_arg_add", description="합산")
    def _add(a: int, b: int) -> int:
        return a + b

    try:
        wrapper = TOOLS["test_multi_arg_add"]
        assert isinstance(wrapper, ToolWrapper)
        assert wrapper.run({"a": 3, "b": 4}) == "7"
    finally:
        from tools.base import REGISTRY
        REGISTRY.pop("test_multi_arg_add", None)
        TOOLS.pop("test_multi_arg_add", None)
