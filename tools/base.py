from typing import Callable

from pydantic import BaseModel

REGISTRY: dict[str, "ToolWrapper"] = {}


def _clean_schema(schema: dict) -> dict:
    """Pydantic의 model_json_schema()에서 OpenAI function calling이 필요로 하지 않는 메타필드 제거."""
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
    return schema


class ToolWrapper:
    def __init__(
        self,
        name: str,
        description: str,
        args_model: type[BaseModel] | None,
        func: Callable,
    ):
        self.name = name
        self.args_model = args_model
        self.func = func
        if args_model is not None:
            parameters = _clean_schema(args_model.model_json_schema())
        else:
            parameters = {"type": "object", "properties": {}, "required": []}
        self.schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }

    def run(self, args: dict) -> str:
        if self.args_model is None:
            return str(self.func())
        validated = self.args_model(**args)
        return str(self.func(**validated.model_dump()))


def tool(args_model: type[BaseModel] | None = None, *, description: str | None = None, name: str | None = None):
    def decorator(func: Callable) -> ToolWrapper:
        tool_name = name or func.__name__
        tool_description = description or (func.__doc__ or "").strip()
        wrapped = ToolWrapper(
            name=tool_name,
            description=tool_description,
            args_model=args_model,
            func=func,
        )
        if tool_name in REGISTRY:
            raise ValueError(f"중복된 tool 이름: {tool_name}")
        REGISTRY[tool_name] = wrapped
        return wrapped

    return decorator
