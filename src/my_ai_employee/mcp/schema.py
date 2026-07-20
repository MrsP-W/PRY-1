"""最小 JSON Schema 子集校验（MCP 工具参数，无外网）。"""

from __future__ import annotations

from typing import Any


class JsonSchemaValidationError(ValueError):
    """参数不符合声明的 JSON Schema。"""


def validate_json_schema(instance: object, schema: dict[str, Any], *, path: str = "$") -> None:
    """校验 instance 对 schema 的子集：type / required / properties / items / enum。"""
    if not isinstance(schema, dict):
        raise JsonSchemaValidationError(f"{path}: schema 必须是 object")

    expected_type = schema.get("type")
    if expected_type is not None:
        _assert_type(instance, expected_type, path)

    if "enum" in schema and instance not in schema["enum"]:
        raise JsonSchemaValidationError(f"{path}: 值不在 enum={schema['enum']!r}")

    if expected_type == "object" or (
        expected_type is None and ("properties" in schema or "required" in schema)
    ):
        if not isinstance(instance, dict):
            raise JsonSchemaValidationError(f"{path}: 期望 object")
        required = schema.get("required") or []
        if not isinstance(required, list):
            raise JsonSchemaValidationError(f"{path}: required 必须是 list")
        for key in required:
            if key not in instance:
                raise JsonSchemaValidationError(f"{path}: 缺少必填字段 {key!r}")
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict):
            raise JsonSchemaValidationError(f"{path}: properties 必须是 object")
        for key, value in instance.items():
            if key in properties and isinstance(properties[key], dict):
                validate_json_schema(value, properties[key], path=f"{path}.{key}")

    if expected_type == "array" and "items" in schema and isinstance(instance, list):
        items_schema = schema["items"]
        if isinstance(items_schema, dict):
            for idx, item in enumerate(instance):
                validate_json_schema(item, items_schema, path=f"{path}[{idx}]")


def _assert_type(instance: object, expected: object, path: str) -> None:
    mapping: dict[str, type | tuple[type, ...]] = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    if isinstance(expected, list):
        errors: list[str] = []
        for option in expected:
            try:
                _assert_type(instance, option, path)
                return
            except JsonSchemaValidationError as exc:
                errors.append(str(exc))
        raise JsonSchemaValidationError(f"{path}: 不匹配 anyOf types {expected}: {errors}")
    if not isinstance(expected, str):
        raise JsonSchemaValidationError(f"{path}: 非法 type {expected!r}")
    py_type = mapping.get(expected)
    if py_type is None:
        raise JsonSchemaValidationError(f"{path}: 不支持的 type {expected!r}")
    if expected == "number" and isinstance(instance, bool):
        raise JsonSchemaValidationError(f"{path}: 期望 number")
    if expected == "integer" and isinstance(instance, bool):
        raise JsonSchemaValidationError(f"{path}: 期望 integer")
    if not isinstance(instance, py_type):
        raise JsonSchemaValidationError(f"{path}: 期望 {expected}, 实际 {type(instance).__name__}")


__all__ = ["JsonSchemaValidationError", "validate_json_schema"]
