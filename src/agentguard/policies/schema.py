"""Strict JSON Schema subset: unsupported keywords fail configuration."""

import json
import math

KEYS = {
    "object": {"properties", "required", "additionalProperties", "minProperties", "maxProperties"},
    "array": {"items", "minItems", "maxItems"},
    "string": {"minLength", "maxLength"},
    "integer": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"},
    "number": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"},
    "boolean": set(),
    "null": set(),
}


def validate_schema(schema, depth=0):
    if depth > 16 or type(schema) is not dict or schema.get("type") not in KEYS:
        raise ValueError("Unsupported parameter schema")
    kind = schema["type"]
    if set(schema) - (KEYS[kind] | {"type", "enum", "description", "title"}):
        raise ValueError("Unsupported schema keyword")
    for key in ("description", "title"):
        if key in schema and type(schema[key]) is not str:
            raise ValueError("Invalid schema annotation")
    if "enum" in schema and (type(schema["enum"]) is not list or not schema["enum"]):
        raise ValueError("Invalid enum")
    for key, value in schema.items():
        if key.startswith(("min", "max")) and key not in {"minimum", "maximum"}:
            if type(value) is not int or value < 0:
                raise ValueError("Invalid size constraint")
        if key in {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"}:
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Invalid numeric constraint")
    if kind == "object":
        props, required = schema.get("properties", {}), schema.get("required", [])
        if (
            schema.get("additionalProperties") is not False
            or type(props) is not dict
            or type(required) is not list
            or any(type(key) is not str or key not in props for key in required)
            or len(set(required)) != len(required)
        ):
            raise ValueError("Objects require closed properties and valid required fields")
        for child in props.values():
            validate_schema(child, depth + 1)
    if kind == "array":
        validate_schema(schema.get("items"), depth + 1)


def _equal(left, right):
    if type(left) is not type(right):
        return type(left) in (int, float) and type(right) in (int, float) and left == right
    if type(left) is dict:
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    if type(left) is list:
        return len(left) == len(right) and all(
            _equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def matches_schema(value, schema):
    """Validate native JSON without casting, defaults, or argument mutation."""
    kind = schema["type"]
    accepted = {
        "object": (dict,),
        "array": (list,),
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
        "null": (type(None),),
    }
    if type(value) not in accepted[kind]:
        return False
    if "enum" in schema and not any(_equal(value, item) for item in schema["enum"]):
        return False
    if kind == "object":
        props = schema.get("properties", {})
        if set(value) - props.keys() or not set(schema.get("required", [])).issubset(value):
            return False
        if not all(matches_schema(child, props[key]) for key, child in value.items()):
            return False
    if kind == "array" and not all(matches_schema(child, schema["items"]) for child in value):
        return False
    if kind in {"object", "array", "string"}:
        suffix = {"object": "Properties", "array": "Items", "string": "Length"}[kind]
        if len(value) < schema.get("min" + suffix, 0):
            return False
        if "max" + suffix in schema and len(value) > schema["max" + suffix]:
            return False
    if kind in {"number", "integer"}:
        if not math.isfinite(value):
            return False
        for key, fails in (
            ("minimum", lambda limit: value < limit),
            ("maximum", lambda limit: value > limit),
            ("exclusiveMinimum", lambda limit: value <= limit),
            ("exclusiveMaximum", lambda limit: value >= limit),
        ):
            if key in schema and fails(schema[key]):
                return False
    return True


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
