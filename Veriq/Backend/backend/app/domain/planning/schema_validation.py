"""Minimal, declarative scenario-configuration validator.

Deliberately not an expression evaluator and not a general JSON-Schema engine:
it supports exactly the keywords the scenario catalogue uses (object, scalar
properties, required, minimum/maximum, enum, additionalProperties).
"""

from __future__ import annotations

from typing import Any


def _check_value(key: str, spec: dict, value: Any) -> str | None:
    expected_type = spec.get("type")
    if expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return f"'{key}' must be an integer"
    elif expected_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return f"'{key}' must be a number"
    elif expected_type == "boolean":
        if not isinstance(value, bool):
            return f"'{key}' must be a boolean"
    elif expected_type == "string":
        if not isinstance(value, str):
            return f"'{key}' must be a string"
        if "maxLength" in spec and len(value) > int(spec["maxLength"]):
            return f"'{key}' must be at most {spec['maxLength']} characters"
        if spec.get("format") == "uri":
            from app.domain.runtime.dependencies import is_http_url

            if not is_http_url(value):
                return f"'{key}' must be an absolute http(s) URL"
    if "minimum" in spec and isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < spec["minimum"]:
            return f"'{key}' must be >= {spec['minimum']}"
    if "maximum" in spec and isinstance(value, (int, float)) and not isinstance(value, bool):
        if value > spec["maximum"]:
            return f"'{key}' must be <= {spec['maximum']}"
    if "enum" in spec and value not in spec["enum"]:
        allowed = ", ".join(str(item) for item in spec["enum"])
        return f"'{key}' must be one of: {allowed}"
    return None


def validate_scenario_config(schema: dict, config: dict | None) -> list[str]:
    """Return human-readable problems; an empty list means valid."""
    config = config or {}
    if not isinstance(config, dict):
        return ["scenario configuration must be a JSON object"]

    problems: list[str] = []
    for key in schema.get("required", []):
        if key not in config:
            problems.append(f"'{key}' is required")

    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        for key in config:
            if key not in properties:
                problems.append(f"'{key}' is not a supported configuration key")

    for key, value in config.items():
        spec = properties.get(key)
        if not isinstance(spec, dict):
            continue
        problem = _check_value(key, spec, value)
        if problem:
            problems.append(problem)
    return problems
