from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import inspect
from typing import Any, get_type_hints
from types import UnionType
from typing import get_args, get_origin


ToolCallable = Callable[..., "ToolResult | Awaitable[ToolResult | dict[str, Any]] | dict[str, Any]"]


@dataclass
class ToolResult:
    name: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class RegisteredTool:
    name: str
    handler: ToolCallable
    description: str = ""
    tags: list[str] = field(default_factory=list)

    def input_schema(self) -> dict[str, Any]:
        signature = inspect.signature(self.handler)
        try:
            type_hints = get_type_hints(self.handler)
        except Exception:
            type_hints = {}
        properties: dict[str, Any] = {}
        required: list[str] = []
        allows_kwargs = False
        for name, parameter in signature.parameters.items():
            if parameter.kind is inspect.Parameter.VAR_KEYWORD:
                allows_kwargs = True
                continue
            if name in {"self", "args", "kwargs"}:
                continue
            properties[name] = _json_schema_for_annotation(type_hints.get(name, parameter.annotation))
            if parameter.default is inspect.Signature.empty:
                required.append(name)
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": allows_kwargs,
        }

    def public_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "parameters": self.input_schema(),
        }

    def validate_inputs(self, inputs: dict[str, Any]) -> list[str]:
        schema = self.input_schema()
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        errors: list[str] = []
        for name in required:
            if name not in inputs:
                errors.append(f"Missing required argument '{name}'.")
        if not schema.get("additionalProperties", False):
            for name in inputs:
                if name not in properties:
                    errors.append(f"Unknown argument '{name}'.")
        for name, value in inputs.items():
            if name not in properties:
                continue
            error = _validate_value_against_schema(name, value, properties[name])
            if error:
                errors.append(error)
        return errors


def tool_success(name: str, data: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None) -> ToolResult:
    return ToolResult(name=name, ok=True, data=data or {}, metadata=metadata or {})


def tool_error(name: str, error: str, metadata: dict[str, Any] | None = None) -> ToolResult:
    return ToolResult(name=name, ok=False, error=error, metadata=metadata or {})


def _json_schema_for_annotation(annotation: Any) -> dict[str, Any]:
    if annotation is inspect.Signature.empty or annotation is Any:
        return {"type": "object"}

    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in {list, tuple, set}:
        item_schema = _json_schema_for_annotation(args[0]) if args else {"type": "object"}
        return {"type": "array", "items": item_schema}
    if origin is dict:
        return {"type": "object"}
    if origin is UnionType or str(origin) == "typing.Union":
        non_none = [arg for arg in args if arg is not type(None)]
        if len(non_none) == 1:
            return _json_schema_for_annotation(non_none[0])
        return {"anyOf": [_json_schema_for_annotation(arg) for arg in non_none] or [{"type": "object"}]}
    if annotation in {str}:
        return {"type": "string"}
    if annotation in {int}:
        return {"type": "integer"}
    if annotation in {float}:
        return {"type": "number"}
    if annotation in {bool}:
        return {"type": "boolean"}
    return {"type": "object"}


def _validate_value_against_schema(name: str, value: Any, schema: dict[str, Any]) -> str | None:
    if "anyOf" in schema:
        branch_errors = [
            _validate_value_against_schema(name, value, branch)
            for branch in schema.get("anyOf", [])
            if isinstance(branch, dict)
        ]
        return None if any(error is None for error in branch_errors) else branch_errors[0]

    expected = schema.get("type")
    if expected == "string" and not isinstance(value, str):
        return f"Argument '{name}' must be a string."
    if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        return f"Argument '{name}' must be an integer."
    if expected == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        return f"Argument '{name}' must be a number."
    if expected == "boolean" and not isinstance(value, bool):
        return f"Argument '{name}' must be a boolean."
    if expected == "array" and not isinstance(value, list):
        return f"Argument '{name}' must be an array."
    if expected == "object" and not isinstance(value, dict):
        return f"Argument '{name}' must be an object."
    return None
